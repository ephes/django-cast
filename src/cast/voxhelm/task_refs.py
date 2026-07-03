from __future__ import annotations

import re


def build_audio_task_ref(
    audio_id: int,
    *,
    diarization_enabled: bool = False,
    diarization_speaker_count: int | None = None,
) -> str:
    task_ref = f"cast-audio-{audio_id}"
    if not diarization_enabled:
        return task_ref
    task_ref = f"{task_ref}-diarized"
    if diarization_speaker_count is not None:
        task_ref = f"{task_ref}-{diarization_speaker_count}-speakers"
    return task_ref


def append_diarization_speaker_count_to_task_ref(task_ref: str, speaker_count: int | None) -> str:
    if speaker_count is None:
        return task_ref
    suffix = f"-{speaker_count}-speakers"
    if task_ref.endswith(suffix):
        return task_ref
    if re.search(r"-diarized-\d+-speakers$", task_ref):
        return re.sub(r"-\d+-speakers$", suffix, task_ref)
    return f"{task_ref}{suffix}"


def ensure_diarized_task_ref(task_ref: str) -> str:
    if re.search(r"-diarized(?:-\d+-speakers)?$", task_ref):
        return task_ref
    return f"{task_ref}-diarized"


def strip_diarized_task_ref(task_ref: str) -> str:
    return re.sub(r"-diarized(?:-\d+-speakers)?$", "", task_ref)


def resolve_audio_task_ref(
    audio_id: int,
    *,
    task_ref: str | None = None,
    diarization_enabled: bool = False,
    diarization_speaker_count: int | None = None,
) -> str:
    if task_ref is None:
        return build_audio_task_ref(
            audio_id,
            diarization_enabled=diarization_enabled,
            diarization_speaker_count=diarization_speaker_count,
        )
    if not diarization_enabled:
        return strip_diarized_task_ref(task_ref)
    return append_diarization_speaker_count_to_task_ref(
        ensure_diarized_task_ref(task_ref),
        diarization_speaker_count,
    )
