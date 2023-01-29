from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_GET

from ..models import Blog, Episode


@require_GET
def twitter_player(request: HttpRequest, blog_slug: str, episode_slug: str) -> HttpResponse:
    """
    This view is used to render the twitter card player. This is a
    podlove player consisting of just the play button. But it needs
    the episode data from the server.
    """
    blog = get_object_or_404(Blog, slug=blog_slug)
    episode = get_object_or_404(Episode, slug=episode_slug)
    if episode.blog != blog:
        raise Http404("Episode not found")

    player_url = reverse("cast:twitter-player", kwargs={"episode_slug": episode.slug, "blog_slug": episode.blog.slug})
    player_url = request.build_absolute_uri(player_url)
    context = {"episode": episode, "player_url": player_url}
    return render(request, "cast/twitter/card_player.html", context=context)
