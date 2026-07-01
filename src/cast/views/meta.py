from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET

from ..audio_access import request_may_view_page
from ..models import Blog, Episode
from ..site_lookup import get_site_specific_page_or_404


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
    context = {"episode": episode}
    return render(request, "cast/twitter/card_player.html", context=context)
