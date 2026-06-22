from __future__ import annotations

import json
from typing import Any, Callable

from django.http import Http404
from django.urls import reverse
from django.utils.text import slugify
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from wagtail.images import get_image_model
from wagtail.images.permissions import permission_policy as image_permission_policy

from ...models import Blog, Post
from ...models.snippets import PostCategory
from .body import author_blocks_to_overview, overview_to_author_blocks
from .errors import EditorPermissionDenied, EditorValidationError, editor_exception_handler
from .serializers import ParentSerializer, PostCreateSerializer


class EditorAPIView(APIView):
    """Base view for the content editing API; renders structured error envelopes."""

    def get_exception_handler(self) -> Callable[..., Any]:
        return editor_exception_handler


class ParentsListView(EditorAPIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        user = request.user
        api_url = reverse("cast:api:editor_post_create")
        parents = []
        # Blog.objects includes Podcast rows: Podcast is concrete MTI over Blog
        # (Podcast has a blog_ptr), so .specific() resolves each row to its
        # Blog/Podcast type and both are listed.
        for blog in Blog.objects.all().specific():
            if blog.permissions_for_user(user).can_add_subpage():
                parents.append(
                    {
                        "id": blog.id,
                        "title": blog.title,
                        "type": blog._meta.label,  # "cast.Blog" or "cast.Podcast"
                        "api_url": api_url,
                    }
                )
        return Response(ParentSerializer(parents, many=True).data)


class PostCreateView(EditorAPIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = PostCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        user = request.user

        if data["publish"]:
            raise EditorValidationError(
                {"publish": [{"code": "unsupported", "message": "Publishing is not available in this API version."}]}
            )

        parent = self._get_parent(data["parent"]["id"])
        if not parent.permissions_for_user(user).can_add_subpage():
            raise EditorPermissionDenied("You cannot add posts under this page.", parent_id=parent.id)

        title = data["title"]
        slug = data.get("slug") or slugify(title)
        self._check_unique_slug(parent, slug)

        cover_image, cover_alt_text = self._resolve_cover_image(data.get("cover_image"), user)
        categories = self._resolve_categories(data["categories"])
        overview_value = author_blocks_to_overview(data["overview"], user=user)

        # Assign body as a JSON string (the proven pattern in tests/conftest.py);
        # the StreamField parses it on access. ``overview_value`` is the list of
        # internal block dicts produced by author_blocks_to_overview().
        post = Post(
            title=title,
            slug=slug,
            owner=user,
            live=False,
            cover_image=cover_image,
            cover_alt_text=cover_alt_text,
            body=json.dumps([{"type": "overview", "value": overview_value}]),
        )
        if data.get("visible_date") is not None:
            post.visible_date = data["visible_date"]
        parent.add_child(instance=post)
        if data["tags"]:
            post.tags.add(*data["tags"])
        if categories:
            post.categories.set(categories)
        if data["tags"] or categories:
            # ClusterTaggableManager / ParentalManyToManyField accumulate changes
            # in memory; flush them to the DB before saving the revision.
            post.save()
        revision = post.save_revision(user=user)

        return Response(self._serialize(post, parent, revision), status=status.HTTP_201_CREATED)

    # --- helpers -------------------------------------------------------

    def _get_parent(self, parent_id: int):
        blog = Blog.objects.filter(pk=parent_id).first()
        if blog is None:
            raise EditorValidationError(
                {"parent": [{"code": "not_found", "message": f"Parent {parent_id} does not exist."}]}
            )
        return blog.specific

    def _check_unique_slug(self, parent, slug: str) -> None:
        from wagtail.models import Page

        if Page.objects.child_of(parent).filter(slug=slug).exists():
            raise EditorValidationError(
                {"slug": [{"code": "duplicate", "message": f"Slug {slug!r} is already used here."}]}
            )

    def _resolve_cover_image(self, cover, user):
        if not cover:
            return None, ""
        image = get_image_model().objects.filter(pk=cover["id"]).first()
        if image is None or not image_permission_policy.user_has_permission_for_instance(user, "choose", image):
            # Collapse missing and not-accessible into one error so we never leak
            # the existence of images the caller cannot choose.
            raise EditorValidationError(
                {
                    "cover_image.id": [
                        {"code": "not_found", "message": f"Image {cover['id']} does not exist or is not accessible."}
                    ]
                }
            )
        return image, cover.get("alt_text", "")

    def _resolve_categories(self, ids):
        if not ids:
            return []
        found = list(PostCategory.objects.filter(pk__in=ids))
        if len(found) != len(set(ids)):
            missing = sorted(set(ids) - {c.pk for c in found})
            raise EditorValidationError(
                {"categories": [{"code": "not_found", "message": f"Unknown category ids: {missing}."}]}
            )
        return found

    def _serialize(self, post, parent, revision) -> dict:
        return {
            "id": post.id,
            "type": post._meta.label,
            "title": post.title,
            "slug": post.slug,
            "parent": {"id": parent.id},
            "latest_revision_id": revision.id,
            "live": post.live,
            "status": "draft",
            "preview_url": reverse("wagtailadmin_pages:view_draft", args=[post.id]),
            "edit_url": reverse("wagtailadmin_pages:edit", args=[post.id]),
            "api_url": reverse("cast:api:editor_post_detail", kwargs={"pk": post.id}),
        }


class PostDetailView(EditorAPIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request: Request, *args: Any, pk: int, **kwargs: Any) -> Response:
        post = Post.objects.filter(pk=pk).first()
        if post is None:
            raise Http404("Post not found.")
        post = post.specific
        if not post.permissions_for_user(request.user).can_edit():
            raise EditorPermissionDenied("You cannot view this draft.", parent_id=None)

        overview_value = []
        for block in post.body:
            if block.block_type == "overview":
                overview_value = block.value.raw_data
                break

        cover = None
        if post.cover_image_id is not None:
            cover = {"id": post.cover_image_id, "alt_text": post.cover_alt_text}

        return Response(
            {
                "id": post.id,
                "type": post._meta.label,
                "title": post.title,
                "slug": post.slug,
                "parent": {"id": post.get_parent().id},
                "visible_date": post.visible_date,
                "tags": list(post.tags.values_list("name", flat=True)),
                "categories": list(post.categories.values_list("pk", flat=True)),
                "cover_image": cover,
                "overview": overview_to_author_blocks(overview_value),
                "latest_revision_id": post.latest_revision_id,
                "live": post.live,
                "status": "live" if post.live else "draft",
                "preview_url": reverse("wagtailadmin_pages:view_draft", args=[post.id]),
                "edit_url": reverse("wagtailadmin_pages:edit", args=[post.id]),
                "api_url": reverse("cast:api:editor_post_detail", kwargs={"pk": post.id}),
            }
        )
