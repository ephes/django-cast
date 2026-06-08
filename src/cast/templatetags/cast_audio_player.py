"""Template tags for the custom audio player."""

from typing import Any

from django import template
from django.utils.html import json_script

from .. import appsettings
from ..player import build_player_payload

register = template.Library()


@register.simple_tag
def cast_audio_player_mode() -> str:
    """Return the configured audio player mode (``"podlove"`` or ``"custom"``)."""
    return appsettings.CAST_AUDIO_PLAYER


@register.inclusion_tag("cast/audio/_custom_player.html", takes_context=True)
def cast_custom_player(context: dict[str, Any], audio: Any, post: Any, transport_share: bool = True) -> dict[str, Any]:
    """Render the inlined JSON payload + the custom player elements for ``audio``.

    The id is computed here so it is correct (the naive
    ``payload|json_script:"..."|add:pk`` filter chain does not work — ``add``
    would apply to the rendered ``<script>`` output, not the id argument).

    ``transport_share=False`` suppresses the player's built-in in-transport share
    button (it renders ``data-share="none"``). A host that owns a page-level share
    UI uses this so only one share entry point is visible; the player's read-only
    ``getShareState()`` API stays available so the host UI can still read the
    current time.
    """
    request = context.get("request")
    payload = build_player_payload(audio, post=post, request=request)
    player_id = f"cast-player-{audio.pk}"
    payload_id = f"cast-player-data-{audio.pk}"
    return {
        "player_script": json_script(payload, payload_id),
        "player_id": player_id,
        "payload_id": payload_id,
        "transport_share": transport_share,
    }
