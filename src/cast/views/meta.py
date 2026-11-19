from typing import Any

from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET

from ..audio_access import prevent_private_media_caching, request_may_view_page
from ..models import Blog, Episode
from ..site_lookup import get_site_specific_page_or_404


def twitter_player_config(episode: Episode) -> dict[str, Any]:
    """
    Build the Podlove player config for the twitter card player.

    The template serializes it with ``json_script``, so page data never ends
    up inside JavaScript string literals.
    """
    audio = episode.podcast_audio
    duration = ""
    m4a_url = ""
    if audio is not None:
        duration = audio.duration_str
        if audio.m4a:
            m4a_url = audio.m4a.url
    blog = episode.blog
    return {
        "version": 5,
        "show": {"title": blog.title, "url": blog.full_url},
        "duration": duration,
        "audio": [{"url": m4a_url, "mimeType": "audio/mp4"}],
    }


@require_GET
def twitter_player(request: HttpRequest, blog_slug: str, episode_slug: str) -> HttpResponse:
    """
    This view is used to render the twitter card player. This is a
    podlove player consisting of just the play button. But it needs
    the episode data from the server.
    """
    blog = get_site_specific_page_or_404(Blog, request, slug=blog_slug)
    episode = get_object_or_404(Episode.objects.live().descendant_of(blog), slug=episode_slug)
    if not request_may_view_page(episode, request):
        raise Http404("Episode not found")
    context = {"episode": episode, "player_config": twitter_player_config(episode)}
    response = render(request, "cast/twitter/card_player.html", context=context)
    return prevent_private_media_caching(response, granting_page=episode)
