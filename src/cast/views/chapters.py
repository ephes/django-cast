from __future__ import annotations

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404

from cast.audio_access import authorize_audio_access
from cast.models import Audio
from cast.player import build_chapters


def chapters_json(request: HttpRequest, pk: int) -> HttpResponse:
    """Return Podcasting 2.0 chapters JSON for an audio object."""
    audio = get_object_or_404(Audio, pk=pk)
    authorize_audio_access(request, audio=audio, explicit_anchor_id=request.GET.get("episode_id"))
    chapters = build_chapters(audio)
    chapter_data: list[dict[str, int | str]] = [
        {"startTime": chapter["start"], "title": chapter["title"]} for chapter in chapters
    ]
    data: dict[str, str | list[dict[str, int | str]]] = {"version": "1.2.0", "chapters": chapter_data}
    return JsonResponse(data, content_type="application/json+chapters")
