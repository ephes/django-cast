from typing import Any

from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from ..audio_access import prevent_private_media_caching, request_may_view_page
from ..models import Episode
from ..player import build_sources
from ..site_lookup import get_site_specific_episode_or_404


def twitter_player_config(episode: Episode) -> dict[str, Any] | None:
    """Build the Twitter card's Podlove config when an audio source is available."""
    audio = episode.podcast_audio
    if audio is None:
        return None
    for source in build_sources(audio, request=None):
        if source["src"]:
            blog = episode.blog
            return {
                "version": 5,
                "show": {"title": blog.title, "url": blog.full_url},
                "duration": audio.duration_str,
                "audio": [{"url": source["src"], "mimeType": source["type"]}],
            }
    return None


@require_GET
def twitter_player(request: HttpRequest, blog_slug: str, episode_slug: str) -> HttpResponse:
    """
    This view is used to render the twitter card player. This is a
    podlove player consisting of just the play button. But it needs
    the episode data from the server.
    """
    episode = get_site_specific_episode_or_404(request, blog_slug=blog_slug, episode_slug=episode_slug)
    if not request_may_view_page(episode, request):
        raise Http404("Episode not found")
    context = {"episode": episode, "player_config": twitter_player_config(episode)}
    response = render(request, "cast/twitter/card_player.html", context=context)
    return prevent_private_media_caching(response, granting_page=episode)
