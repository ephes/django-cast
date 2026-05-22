from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST
from wagtail.admin import messages
from wagtail.models import Site
from wagtail.permission_policies.collections import CollectionOwnershipPermissionPolicy

from ..models import Audio, Episode
from ..models.transcript_generation import TranscriptGeneration
from ..voxhelm import (
    VoxhelmError,
    enqueue_audio_transcript_generation,
    get_transcript_generation_status_context,
)

audio_permission_policy = CollectionOwnershipPermissionPolicy(Audio, auth_model=Audio, owner_field_name="user")


def user_can_generate_transcript_for_audio(*, request: HttpRequest, audio: Audio) -> bool:
    return audio_permission_policy.user_has_permission_for_instance(request.user, "change", audio)


def user_can_generate_transcript_for_episode(*, request: HttpRequest, episode: Episode) -> bool:
    if episode.permissions_for_user(request.user).can_edit() is False:
        return False
    podcast_audio = episode.podcast_audio
    if not isinstance(podcast_audio, Audio):
        return False
    return user_can_generate_transcript_for_audio(request=request, audio=podcast_audio)


def resolve_site_for_audio(*, request: HttpRequest, audio: Audio) -> Site | None:
    site_ids = {site.pk for episode in audio.episodes.all() if (site := episode.get_site()) is not None}
    if len(site_ids) == 1:
        return Site.objects.filter(pk=site_ids.pop()).first()
    return Site.find_for_request(request)


def _get_redirect_url(request: HttpRequest, default_url: str) -> str:
    next_url = request.POST.get("next") or request.GET.get("next")
    if isinstance(next_url, str) and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return next_url
    return default_url


def _add_generation_queued_message(
    request: HttpRequest, *, title: str, generation: TranscriptGeneration, enqueued: bool
) -> None:
    if not enqueued:
        messages.info(request, _("Transcript generation is already in progress for '%(title)s'.") % {"title": title})
        return
    messages.success(
        request,
        _("Transcript generation queued for '%(title)s'.") % {"title": title},
        buttons=[messages.button(reverse("castaudio:edit", args=(generation.audio_id,)), _("View status"))],
    )


def _add_generation_configuration_error_message(request: HttpRequest, exc: ImproperlyConfigured) -> None:
    messages.error(
        request,
        _(
            "Transcript generation failed: %(message)s Check Voxhelm configuration in Settings -> Voxhelm settings, "
            "Django settings, or deployment environment variables."
        )
        % {"message": exc},
    )


def _add_generation_error_message(request: HttpRequest, exc: VoxhelmError) -> None:
    messages.error(request, _("Transcript generation failed: %(message)s") % {"message": exc})


@login_required
@require_POST
def generate_episode_transcript(request: HttpRequest, episode_id: int) -> HttpResponse:
    episode = get_object_or_404(Episode.objects.specific(), pk=episode_id)
    redirect_url = _get_redirect_url(request, reverse("wagtailadmin_pages:edit", args=(episode.pk,)))
    if not user_can_generate_transcript_for_episode(request=request, episode=episode):
        raise PermissionDenied
    audio = episode.podcast_audio
    if not isinstance(audio, Audio):
        raise PermissionDenied
    site = episode.get_site() or Site.find_for_request(request)
    try:
        result = enqueue_audio_transcript_generation(audio=audio, request_or_site=site, requested_by=request.user)
    except ImproperlyConfigured as exc:
        _add_generation_configuration_error_message(request, exc)
        return redirect(redirect_url)
    except VoxhelmError as exc:
        _add_generation_error_message(request, exc)
        return redirect(redirect_url)
    _add_generation_queued_message(
        request,
        title=episode.title,
        generation=result.generation,
        enqueued=result.enqueued,
    )
    return redirect(redirect_url)


@login_required
@require_POST
def generate_audio_transcript(request: HttpRequest, audio_id: int) -> HttpResponse:
    audio = get_object_or_404(Audio, pk=audio_id)
    redirect_url = _get_redirect_url(request, reverse("castaudio:edit", args=(audio.pk,)))
    if not user_can_generate_transcript_for_audio(request=request, audio=audio):
        raise PermissionDenied
    try:
        result = enqueue_audio_transcript_generation(
            audio=audio,
            request_or_site=resolve_site_for_audio(request=request, audio=audio),
            requested_by=request.user,
        )
    except ImproperlyConfigured as exc:
        _add_generation_configuration_error_message(request, exc)
        return redirect(redirect_url)
    except VoxhelmError as exc:
        _add_generation_error_message(request, exc)
        return redirect(redirect_url)
    _add_generation_queued_message(
        request,
        title=audio.title or str(audio.pk),
        generation=result.generation,
        enqueued=result.enqueued,
    )
    return redirect(redirect_url)


def get_audio_transcript_status_context(*, audio: Audio) -> dict[str, str | bool]:
    return get_transcript_generation_status_context(audio=audio)
