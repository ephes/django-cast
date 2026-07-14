from typing import Any

from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from modelsearch.backends.base import BaseSearchResults
from wagtail.permission_policies.collections import CollectionOwnershipPermissionPolicy

from ..forms import AudioForm
from ..models import Audio
from ..search_utils import normalize_modelsearch_query, safe_modelsearch_results
from ..voxhelm import voxhelm_configured
from . import AuthenticatedHttpRequest
from .media import MediaAdminConfig, MediaAdminViews
from .voxhelm import get_audio_transcript_status_context, user_can_generate_transcript_for_audio

audio_permission_policy = CollectionOwnershipPermissionPolicy(Audio, auth_model=Audio, owner_field_name="user")


def delete_old_audio_files(audio: Audio, changed_audio_files: set[str]) -> None:
    for file_format in changed_audio_files:
        # if providing a new audio file, delete the old one.
        # NB Doing this via original_file.delete() clears the file field,
        # which definitely isn't what we want...
        original_file = getattr(audio, file_format)
        if original_file.name != "":
            original_file.storage.delete(original_file.name)


def get_audio_data(audio: Audio) -> dict[str, Any]:
    """
    helper function: given a audio, return the json to pass back to the
    chooser panel - move to model FIXME
    """
    return {
        "id": audio.id,
        "title": audio.title,
        "edit_link": reverse("castaudio:edit", args=(audio.id,)),
    }


def _search_audio(base_audios: Any, raw_query_string: str) -> tuple[Any | BaseSearchResults, str | None]:
    return safe_modelsearch_results(base_audios, raw_query_string), normalize_modelsearch_query(
        raw_query_string
    ) or None


def _delete_old_audio_files(audio_id: int, form: Any) -> None:
    changed_audio_files = set(form.changed_data).intersection(Audio.audio_formats)
    if len(changed_audio_files) > 0:
        old_audio = get_object_or_404(Audio, id=audio_id)
        delete_old_audio_files(old_audio, changed_audio_files)


def _extra_audio_edit_context(request: HttpRequest, audio: Audio) -> dict[str, Any]:
    return {
        "generate_transcript_url": reverse("cast-voxhelm:generate_audio", args=(audio.pk,)),
        "user_can_generate_transcript": voxhelm_configured(request_or_site=request)
        and user_can_generate_transcript_for_audio(request=request, audio=audio),
        **get_audio_transcript_status_context(audio=audio),
    }


def _create_audio(user: Any) -> Audio:
    return Audio(user=user)


def _audio_message_arg(audio: Audio) -> Any:
    return audio.title


def _audio_edit_form_initial(audio: Audio) -> dict[str, Any]:
    return {"chaptermarks": audio.chapters_as_text}


def _audio_file_for_size(audio: Audio) -> Any:
    return audio.m4a


audio_admin_config = MediaAdminConfig(
    model=Audio,
    permission_policy=audio_permission_policy,
    get_form=lambda: AudioForm,
    url_namespace="castaudio",
    template_dir="cast/audio",
    plural_context_name="audios",
    singular_context_name="audio",
    chosen_step="audio_chosen",
    get_chosen_data=get_audio_data,
    create_instance=_create_audio,
    search=_search_audio,
    ordering="-created",
    show_popular_tags=True,
    index_search_placeholder=_("Search audio files"),
    index_fallback_placeholder=_("Search media"),
    added_message=_("Audio file '{0}' added."),
    add_error_message=_("The audio file could not be saved due to errors."),
    updated_message=_("Audio file '{0}' updated"),
    update_error_message=_("The media could not be saved due to errors."),
    deleted_message=_("Audio '{0}' deleted."),
    chooser_upload_error_message=_("The audio could not be saved due to errors."),
    file_missing_message=_("The file could not be found. Please change the source or delete the audio file"),
    message_arg=_audio_message_arg,
    edit_form_initial=_audio_edit_form_initial,
    delete_old_files=_delete_old_audio_files,
    get_file_for_size=_audio_file_for_size,
    extra_edit_context=_extra_audio_edit_context,
)

_views = MediaAdminViews(audio_admin_config)

index = _views.index
chooser = _views.chooser


def add(request: AuthenticatedHttpRequest) -> HttpResponse:
    return _views.add(request)


def edit(request: HttpRequest, audio_id: int) -> HttpResponse:
    return _views.edit(request, audio_id)


def delete(request: HttpRequest, audio_id: int) -> HttpResponse:
    return _views.delete(request, audio_id)


def chosen(request: HttpRequest, audio_id: int) -> HttpResponse:
    return _views.chosen(request, audio_id)


def chooser_upload(request: AuthenticatedHttpRequest) -> HttpResponse:
    return _views.chooser_upload(request)
