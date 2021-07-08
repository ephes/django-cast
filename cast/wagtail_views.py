from django.shortcuts import render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.vary import vary_on_headers

from wagtailmedia.utils import paginate
from wagtail.admin.models import popular_tags_for_model
from wagtailmedia.permissions import permission_policy
from wagtail.admin.auth import PermissionPolicyChecker
from wagtail.admin.forms.search import SearchForm

from .models import Video

permission_checker = PermissionPolicyChecker(permission_policy)


@permission_checker.require_any("add", "change", "delete")
@vary_on_headers("X-Requested-With")
def video_index(request):
    ordering = "-created"
    videos = Video.objects.all().order_by(ordering)

    # Search
    query_string = None
    if "q" in request.GET:
        form = SearchForm(request.GET, placeholder=_("Search video files"))
        if form.is_valid():
            query_string = form.cleaned_data["q"]
            videos = videos.search(query_string)
    else:
        form = SearchForm(placeholder=_("Search media"))

    # Pagination
    paginator, media = paginate(request, videos)

    collections = permission_policy.collections_user_has_any_permission_for(
        request.user, ["add", "change"]
    )
    if len(collections) < 2:
        collections = None

    # Create response
    print("fooobarbz")
    print(request.headers.get("x-requested-with"))
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return render(
            request,
            "wagtailmedia/media/results.html",
            {
                "ordering": ordering,
                "media_files": media,
                "query_string": query_string,
                "is_searching": bool(query_string),
            },
        )
    else:
        return render(
            request,
            "cast/wagtail/wagtail_video_index.html",
            {
                "ordering": ordering,
                "media_files": media,
                "query_string": query_string,
                "is_searching": bool(query_string),
                "search_form": form,
                "popular_tags": popular_tags_for_model(Video),
                "user_can_add": permission_policy.user_has_permission(
                    request.user, "add"
                ),
                "collections": collections,
                "current_collection": None,
            },
        )
