from __future__ import annotations

import json
from typing import Any, Callable

from django.urls import reverse
from django.utils.text import slugify
from rest_framework import status
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ...models import Blog, Post
from ...models.snippets import PostCategory
from .body import (
    author_blocks_to_overview,
    author_blocks_to_section,
    get_choosable_image,
    section_to_author_blocks,
)
from .errors import (
    EditorFlatError,
    EditorNotFound,
    EditorPermissionDenied,
    EditorRevisionConflict,
    EditorValidationError,
    editor_exception_handler,
)
from .serializers import ParentSerializer, PostCreateSerializer, PostUpdateSerializer


class HasWagtailAdminAccess(BasePermission):
    message = "You do not have access to the Wagtail admin."

    def has_permission(self, request: Request, view: APIView) -> bool:
        if request.user and request.user.has_perm("wagtailadmin.access_admin"):
            return True
        raise EditorPermissionDenied(self.message, parent_id=None)


class EditorAPIView(APIView):
    """Base view for the content editing API; renders structured error envelopes."""

    permission_classes = (IsAuthenticated, HasWagtailAdminAccess)

    def get_exception_handler(self) -> Callable[..., Any]:
        return editor_exception_handler


class ParentsListView(EditorAPIView):
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


class PostEditorMixin:
    body_section_order = ("overview", "detail")

    def _get_parent(self, parent_id: int):
        blog = Blog.objects.filter(pk=parent_id).first()
        if blog is None:
            raise EditorValidationError(
                {"parent": [{"code": "not_found", "message": f"Parent {parent_id} does not exist."}]}
            )
        return blog.specific

    def _get_post(self, pk: int, user: Any, *, denied_message: str):
        post = Post.objects.filter(pk=pk).first()
        if post is None:
            raise EditorNotFound("Post not found.")
        post = post.specific
        if not post.permissions_for_user(user).can_edit():
            raise EditorPermissionDenied(denied_message, parent_id=None)
        return post

    def _check_unique_slug(self, parent: Any, slug: str, *, exclude_id: int | None = None) -> None:
        from wagtail.models import Page

        siblings = Page.objects.child_of(parent).filter(slug=slug)
        if exclude_id is not None:
            siblings = siblings.exclude(pk=exclude_id)
        if siblings.exists():
            raise EditorValidationError(
                {"slug": [{"code": "duplicate", "message": f"Slug {slug!r} is already used here."}]}
            )

    def _resolve_cover_image(self, cover: dict[str, Any] | None, user: Any):
        if not cover:
            return None, ""
        image = get_choosable_image(cover["id"], user)
        if image is None:
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

    def _resolve_categories(self, ids: list[int]):
        if not ids:
            return []
        found_by_id = {category.pk: category for category in PostCategory.objects.filter(pk__in=ids)}
        if len(found_by_id) != len(set(ids)):
            missing = sorted(set(ids) - set(found_by_id))
            raise EditorValidationError(
                {"categories": [{"code": "not_found", "message": f"Unknown category ids: {missing}."}]}
            )
        return [found_by_id[category_id] for category_id in ids]

    def _section_value(self, post: Post, section_type: str) -> list[dict]:
        for block in post.body.raw_data:
            if block.get("type") == section_type:
                value = block.get("value")
                if isinstance(value, list):
                    return value
        return []

    def _body_sections_with_replacements(self, post: Post, replacements: dict[str, list[dict]]) -> str:
        sections = []
        remaining = dict(replacements)
        for section in post.body.raw_data:
            section_data = dict(section)
            section_type = section_data["type"]
            if section_type in replacements:
                section_data["value"] = replacements[section_type]
                remaining.pop(section_type, None)
            sections.append(section_data)
        section_order = {section_type: index for index, section_type in enumerate(self.body_section_order)}
        for section_type, value in sorted(remaining.items(), key=lambda item: section_order[item[0]]):
            new_section = {"type": section_type, "value": value}
            current_order = section_order[section_type]
            insert_index = 0
            for index, section in enumerate(sections):
                existing_order = section_order.get(section["type"])
                if existing_order is not None and existing_order > current_order:
                    insert_index = index
                    break
                insert_index = index + 1
            sections.insert(insert_index, new_section)
        return json.dumps(sections)

    def _serialize(
        self, post: Post, *, user: Any, content_post: Post | None = None, revision: Any | None = None
    ) -> dict:
        content_post = content_post or post.get_latest_revision_as_object()
        latest_revision_id = revision.id if revision is not None else post.latest_revision_id
        cover = None
        if content_post.cover_image_id is not None:
            cover = {"id": content_post.cover_image_id, "alt_text": content_post.cover_alt_text}

        return {
            "id": post.id,
            "type": content_post._meta.label,
            "title": content_post.title,
            "slug": content_post.slug,
            "parent": {"id": post.get_parent().id},
            "visible_date": content_post.visible_date,
            "tags": [tag.name for tag in content_post.tags.all()],
            "categories": [category.pk for category in content_post.categories.all()],
            "cover_image": cover,
            "overview": section_to_author_blocks(
                self._section_value(content_post, "overview"), path_prefix="overview", user=user
            ),
            "detail": section_to_author_blocks(
                self._section_value(content_post, "detail"), path_prefix="detail", user=user
            ),
            "latest_revision_id": latest_revision_id,
            "live": post.live,
            "status": "live" if post.live and not post.has_unpublished_changes else "draft",
            "preview_url": reverse("wagtailadmin_pages:view_draft", args=[post.id]),
            "edit_url": reverse("wagtailadmin_pages:edit", args=[post.id]),
            "api_url": reverse("cast:api:editor_post_detail", kwargs={"pk": post.id}),
        }

    def _public_url(self, post: Post, request: Request) -> str | None:
        url = post.get_url(request=request)
        return url or post.get_full_url(request=request)


class PostCreateView(PostEditorMixin, EditorAPIView):
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
        body_sections = [{"type": "overview", "value": overview_value}]
        if "detail" in data:
            body_sections.append(
                {"type": "detail", "value": author_blocks_to_section(data["detail"], user=user, path_prefix="detail")}
            )

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
            body=json.dumps(body_sections),
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
            # in memory; flush them so the created page row and first revision agree.
            post.save()
        revision = post.save_revision(user=user)

        return Response(
            self._serialize(post, user=user, content_post=post, revision=revision),
            status=status.HTTP_201_CREATED,
        )


class PostDetailView(PostEditorMixin, EditorAPIView):
    def get(self, request: Request, *args: Any, pk: int, **kwargs: Any) -> Response:
        post = self._get_post(pk, request.user, denied_message="You cannot view this draft.")
        return Response(self._serialize(post, user=request.user))

    def patch(self, request: Request, *args: Any, pk: int, **kwargs: Any) -> Response:
        serializer = PostUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        user = request.user
        if data.get("publish"):
            raise EditorValidationError(
                {"publish": [{"code": "unsupported", "message": "Publishing is not available in this API version."}]}
            )
        if not (set(data) - {"base_revision_id", "publish"}):
            raise EditorValidationError(
                {"non_field_errors": [{"code": "required", "message": "Provide at least one field to update."}]}
            )

        post = self._get_post(pk, user, denied_message="You cannot edit this draft.")
        current_revision_id = post.latest_revision_id
        submitted_base_revision_id = data["base_revision_id"]
        edit_url = reverse("wagtailadmin_pages:edit", args=[post.id])
        if current_revision_id != submitted_base_revision_id:
            raise EditorRevisionConflict(
                current_revision_id=current_revision_id,
                submitted_base_revision_id=submitted_base_revision_id,
                edit_url=edit_url,
            )

        draft = post.get_latest_revision().as_object()
        if "title" in data:
            draft.title = data["title"]
        if "slug" in data:
            self._check_unique_slug(draft.get_parent(), data["slug"], exclude_id=draft.id)
            draft.slug = data["slug"]
        if "visible_date" in data:
            draft.visible_date = data["visible_date"]
        if "cover_image" in data:
            draft.cover_image, draft.cover_alt_text = self._resolve_cover_image(data["cover_image"], user)
        if "tags" in data:
            draft.tags.set(data["tags"])
        if "categories" in data:
            draft.categories.set(self._resolve_categories(data["categories"]))
        body_replacements = {}
        if "overview" in data:
            body_replacements["overview"] = author_blocks_to_overview(
                data["overview"], user=user, existing_section=self._section_value(draft, "overview")
            )
        if "detail" in data:
            body_replacements["detail"] = author_blocks_to_section(
                data["detail"], user=user, path_prefix="detail", existing_section=self._section_value(draft, "detail")
            )
        if body_replacements:
            draft.body = self._body_sections_with_replacements(draft, body_replacements)

        revision = draft.save_revision(user=user)
        post.refresh_from_db()
        return Response(self._serialize(post, user=user, content_post=draft, revision=revision))


class PostPublishView(PostEditorMixin, EditorAPIView):
    def post(self, request: Request, *args: Any, pk: int, **kwargs: Any) -> Response:
        user = request.user
        post = self._get_post(pk, user, denied_message="You cannot publish this draft.")
        if not post.permissions_for_user(user).can_publish():
            raise EditorPermissionDenied("You cannot publish this post.", parent_id=None)
        if post.live and not post.has_unpublished_changes:
            raise EditorFlatError(
                "no_unpublished_draft",
                "This post is already live and has no unpublished draft revision.",
                status_code=status.HTTP_409_CONFLICT,
            )

        revision = post.get_latest_revision()
        if revision is None:
            raise EditorFlatError(
                "no_revision",
                "This post has no draft revision to publish.",
                status_code=status.HTTP_409_CONFLICT,
            )

        revision.publish(user=user)
        post = Post.objects.get(pk=post.pk).specific
        data = self._serialize(post, user=user, content_post=post, revision=revision)
        data["published_revision_id"] = revision.id
        data["public_url"] = self._public_url(post, request)
        return Response(data)
