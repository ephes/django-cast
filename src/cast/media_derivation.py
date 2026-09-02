"""Explicit persistence boundaries for derived media metadata."""

from __future__ import annotations

import logging
import warnings
from copy import deepcopy
from typing import TYPE_CHECKING, Any

from django import VERSION as DJANGO_VERSION
from django.db import router, transaction
from django.utils import deprecation

from .media_validation import validate_audio_upload, validate_video_upload

if TYPE_CHECKING:
    from .models.audio import Audio
    from .models.transcript import Transcript
    from .models.video import Video

logger = logging.getLogger(__name__)

TRANSCRIPT_SPEAKER_MAPPING_ARTIFACT_FIELDS = ("podlove", "dote", "vtt")
MODEL_SAVE_ARGUMENT_NAMES = ("force_insert", "force_update", "using", "update_fields")
MODEL_SAVE_ARGUMENT_DEFAULTS = {
    "force_insert": False,
    "force_update": False,
    "using": None,
    "update_fields": None,
}
POSITIONAL_SAVE_DEPRECATION_WARNING: type[Warning] = getattr(
    deprecation,
    "RemovedInDjango60Warning",
    DeprecationWarning,
)


def _normalize_positional_model_save_arguments(args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    """Apply the installed Django version's ``Model.save()`` positional-argument contract."""
    if DJANGO_VERSION >= (6, 0):
        total_len_args = len(args) + 1
        raise TypeError(f"Model.save() takes 1 positional argument but {total_len_args} were given")

    if DJANGO_VERSION >= (5, 1):
        warnings.warn(
            "Passing positional arguments to save() is deprecated",
            POSITIONAL_SAVE_DEPRECATION_WARNING,
            stacklevel=4,
        )

    total_len_args = len(args) + 1
    max_len_args = len(MODEL_SAVE_ARGUMENT_NAMES) + 1
    if total_len_args > max_len_args:
        raise TypeError(
            f"Model.save() takes from 1 to {max_len_args} positional arguments but {total_len_args} were given"
        )

    normalized = dict(kwargs)
    for argument_name, argument_value in zip(MODEL_SAVE_ARGUMENT_NAMES, args, strict=False):
        if argument_name in normalized and (
            DJANGO_VERSION < (5, 1) or normalized[argument_name] is not MODEL_SAVE_ARGUMENT_DEFAULTS[argument_name]
        ):
            raise TypeError(f"Model.save() got multiple values for argument '{argument_name}'")
        normalized[argument_name] = argument_value
    return normalized


def normalize_model_save_arguments(
    model: Any, args: tuple[Any, ...], kwargs: dict[str, Any]
) -> tuple[dict[str, Any], str]:
    """Normalize Django's deprecated positional save arguments and resolve the write alias."""
    normalized = _normalize_positional_model_save_arguments(args, kwargs) if args else dict(kwargs)
    using = normalized.get("using")
    if not using:
        state = getattr(model, "_state", None)
        using = getattr(state, "db", None) or router.db_for_write(
            type(model),
            instance=model if state is not None else None,
        )
    normalized["using"] = using
    return normalized, using


def save_audio_with_derivations(
    audio: Audio,
    *args: Any,
    generate_duration: bool = True,
    cache_file_sizes: bool = True,
    **kwargs: Any,
) -> None:
    """Persist an Audio and synchronously derive requested metadata."""
    save_kwargs, using = normalize_model_save_arguments(audio, args, kwargs)
    if generate_duration:
        for audio_format, field in audio.uploaded_audio_files:
            if not getattr(field, "_committed", True):
                validate_audio_upload(field.file, audio_format=audio_format)

    with transaction.atomic(using=using):
        audio.save(duration=False, cache_file_sizes=False, **save_kwargs)

        update_fields = []
        if generate_duration and audio.duration is None:
            logger.info("save audio duration")
            audio.create_duration()
            if audio.duration is not None:
                update_fields.append("duration")

        if cache_file_sizes:
            old_data = deepcopy(audio.data)
            audio.size_to_metadata()
            if old_data != audio.data:
                update_fields.append("data")

        if update_fields:
            update_save_kwargs: dict[str, object] = {
                "duration": False,
                "cache_file_sizes": False,
                "update_fields": update_fields,
                "using": using,
            }
            audio.save(**update_save_kwargs)


def save_video_with_derivations(
    video: Video,
    *args: Any,
    generate_poster: bool = True,
    **kwargs: Any,
) -> Video | None:
    """Persist a Video and synchronously derive its poster when requested."""
    save_kwargs, using = normalize_model_save_arguments(video, args, kwargs)
    if generate_poster and not getattr(video.original, "_committed", True):
        validate_video_upload(video.original.file)

    with transaction.atomic(using=using):
        result = video.save(poster=False, **save_kwargs)
        if generate_poster:
            logger.info("generate video poster")
            poster_name_before = video.poster.name or ""
            video.create_poster()
            poster_name_after = video.poster.name or ""
            if poster_name_after and poster_name_after != poster_name_before:
                update_save_kwargs: dict[str, object] = {
                    "poster": False,
                    "update_fields": ["poster"],
                    "using": using,
                }
                result = video.save(**update_save_kwargs)
    return result


def should_sync_transcript_speaker_mappings(update_fields: Any) -> bool:
    """Return whether a Transcript write changes mapping source artifacts."""
    if update_fields is None:
        return True
    return bool(set(update_fields).intersection((*TRANSCRIPT_SPEAKER_MAPPING_ARTIFACT_FIELDS, "audio")))


def save_transcript_with_derivations(transcript: Transcript, *args: Any, **kwargs: Any) -> None:
    """Persist a Transcript and synchronize its durable speaker mappings."""
    save_kwargs, using = normalize_model_save_arguments(transcript, args, kwargs)
    update_fields = save_kwargs.get("update_fields")
    with transaction.atomic(using=using):
        transcript.save(sync_speaker_mappings=False, **save_kwargs)
        if should_sync_transcript_speaker_mappings(update_fields):
            transcript.sync_speaker_mappings()
