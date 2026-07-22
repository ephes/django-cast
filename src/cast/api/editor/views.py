from __future__ import annotations

import json
from typing import Any, Callable, cast

from django.db import transaction
from django.db.models import F, Q, Subquery
from django.http import HttpResponse
from django.urls import reverse
from django.utils.text import slugify
from rest_framework import status
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ...models import Audio, Blog, Episode, Podcast, Post, Season
from ...models.snippets import PostCategory
from .body import (
    author_blocks_to_overview,
    author_blocks_to_section,
    get_choosable_audio,
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
from .scopes import HasEditorScope
from .serializers import (
    EpisodeCreateSerializer,
    EpisodeUpdateSerializer,
    ParentSerializer,
    PostCreateSerializer,
    PostLookupSerializer,
    PostUpdateSerializer,
)


class HasWagtailAdminAccess(BasePermission):
    message = "You do not have access to the Wagtail admin."

    def has_permission(self, request: Request, view: APIView) -> bool:
        if request.user and request.user.has_perm("wagtailadmin.access_admin"):
            return True
        raise EditorPermissionDenied(self.message, parent_id=None)


class EditorAPIView(APIView):
    """Base view for the content editing API; renders structured error envelopes."""

    permission_classes = (IsAuthenticated, HasWagtailAdminAccess, HasEditorScope)
    required_scopes: dict[str, str | None] = {}

    def get_exception_handler(self) -> Callable[..., Any]:
        return editor_exception_handler


def _if_match_revision_id(request: Request) -> int | None:
    value = request.headers.get("If-Match")
    if value is None:
        return None
    value = value.strip()
    if not (value.startswith('"') and value.endswith('"')):
        raise EditorValidationError(
            {"If-Match": [{"code": "invalid", "message": 'If-Match must be a quoted revision id such as "123".'}]}
        )
    revision_id = value[1:-1]
    if not (revision_id.isascii() and revision_id.isdigit()):
        raise EditorValidationError(
            {"If-Match": [{"code": "invalid", "message": 'If-Match must be a quoted revision id such as "123".'}]}
        )
    return int(revision_id)


def _submitted_base_revision_id(request: Request, data: dict[str, Any]) -> int:
    body_revision_id = cast(int | None, data.get("base_revision_id"))
    header_revision_id = _if_match_revision_id(request)
    if body_revision_id is None and header_revision_id is None:
        raise EditorValidationError({"base_revision_id": [{"code": "required", "message": "This field is required."}]})
    if body_revision_id is not None and header_revision_id is not None and body_revision_id != header_revision_id:
        raise EditorValidationError(
            {
                "If-Match": [
                    {
                        "code": "mismatch",
                        "message": "If-Match must match base_revision_id when both are supplied.",
                    }
                ]
            }
        )
    if body_revision_id is None:
        assert header_revision_id is not None
        return header_revision_id
    return body_revision_id


def _previous_page_revision_id(post: Post, revision_id: int | None) -> int | None:
    """Return the immediately preceding revision id for this page."""
    if revision_id is None:
        return None
    target_created_at = post.revisions.filter(pk=revision_id).values("created_at")[:1]
    previous = (
        post.revisions.filter(
            Q(created_at__lt=Subquery(target_created_at))
            | Q(created_at=Subquery(target_created_at), pk__lt=revision_id)
        )
        .order_by("-created_at", "-pk")
        .values_list("pk", flat=True)
        .first()
    )
    return cast(int | None, previous)


class ParentsListView(EditorAPIView):
    required_scopes = {"GET": None}

    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        user = request.user
        post_api_url = reverse("cast:api:editor_post_create")
        episode_api_url = reverse("cast:api:editor_episode_create")
        parents = []
        # Blog.objects includes Podcast rows: Podcast is concrete MTI over Blog
        # (Podcast has a blog_ptr), so .specific() resolves each row to its
        # Blog/Podcast type and both are listed.
        for blog in Blog.objects.all().specific():
            if blog.permissions_for_user(user).can_add_subpage():
                # A podcast's primary content type is an episode, so point it at the
                # episode create endpoint; plain blogs point at the post endpoint.
                parents.append(
                    {
                        "id": blog.id,
                        "title": blog.title,
                        "type": blog._meta.label,  # "cast.Blog" or "cast.Podcast"
                        "api_url": episode_api_url if blog.is_podcast else post_api_url,
                    }
                )
        return Response(ParentSerializer(parents, many=True).data)


class PostEditorMixin:
    body_section_order = ("overview", "detail")
    detail_url_name = "cast:api:editor_post_detail"

    def _get_parent(self, parent_id: int) -> Blog:
        blog = Blog.objects.filter(pk=parent_id).first()
        if blog is None:
            raise EditorValidationError(
                {"parent": [{"code": "not_found", "message": f"Parent {parent_id} does not exist."}]}
            )
        return blog.specific

    def _get_post(self, pk: int, user: Any, *, denied_message: str, for_update: bool = False) -> Post:
        posts = Post.objects.select_for_update() if for_update else Post.objects
        post = posts.filter(pk=pk).first()
        if post is None:
            raise EditorNotFound("Post not found.")
        post = post.specific
        if not post.permissions_for_user(user).can_edit():
            raise EditorPermissionDenied(denied_message, parent_id=None)
        return post

    def _lock_parent_for_slug_check(self, parent: Any, *, noun: str) -> Any:
        """Serialize a sibling slug decision and reload current tree metadata.

        The caller must keep its transaction open from this lock through the
        revision write. An actual no-op write is portable where
        ``SELECT FOR UPDATE`` is not: PostgreSQL locks this parent row and SQLite
        takes its database write lock.
        """
        from wagtail.models import Page

        updated = Page.objects.filter(pk=parent.pk).update(numchild=F("numchild"))
        if updated != 1:
            raise EditorNotFound(f"{noun} parent not found.")
        return self._get_parent(parent.pk)

    def _check_unique_slug(self, parent: Any, slug: str, *, exclude_id: int | None = None) -> None:
        from wagtail.models import Page

        siblings = Page.objects.child_of(parent)
        if exclude_id is not None:
            siblings = siblings.exclude(pk=exclude_id)
        # Wagtail validates edits against persisted Page.slug values, while editor
        # lookup follows the latest draft. Reserve both namespaces so an API write
        # can never create a draft that the Wagtail admin cannot validate. The JSON
        # key lookup keeps the rest of each revision (including the body) out of
        # Python.
        if siblings.filter(Q(latest_revision__content__slug=slug) | Q(slug=slug)).exists():
            raise EditorValidationError(
                {"slug": [{"code": "duplicate", "message": f"Slug {slug!r} is already used here."}]}
            )

    @staticmethod
    def _has_approved_schedule(post: Post, *, for_update: bool = False) -> bool:
        """Return whether Wagtail has approved any revision for scheduled publication.

        PATCH already holds the page-row lock before calling this with
        ``for_update=True``. Locking existing revision rows as well means schedule
        cancellation and approval cannot race the draft-only decision; creating a
        new scheduled revision must update the same locked page row before it can
        become the page's current revision.
        """
        if not for_update:
            return post.revisions.filter(approved_go_live_at__isnull=False).exists()
        locked_schedules = post.revisions.select_for_update().values_list("id", "approved_go_live_at")
        return any(approved_go_live_at is not None for _, approved_go_live_at in locked_schedules)

    def _enforce_draft_only(self, post: Post, *, required: bool, noun: str) -> None:
        if not required:
            return
        if post.live:
            raise EditorFlatError(
                "published_post",
                f"This {noun} is already live; the requested draft-only update was refused.",
                status_code=status.HTTP_409_CONFLICT,
            )
        if self._has_approved_schedule(post, for_update=True):
            raise EditorFlatError(
                "scheduled_post",
                f"This {noun} is scheduled for publication; the requested draft-only update was refused.",
                status_code=status.HTTP_409_CONFLICT,
            )

    def _resolve_cover_image(self, cover: dict[str, Any] | None, user: Any) -> tuple[Any | None, str]:
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

    def _resolve_categories(self, ids: list[int]) -> list[PostCategory]:
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

        if self._has_approved_schedule(post):
            publication_status = "scheduled"
        elif post.live and not post.has_unpublished_changes:
            publication_status = "live"
        else:
            publication_status = "draft"

        data = {
            "id": post.id,
            "type": content_post._meta.label,
            "title": content_post.title,
            "slug": content_post.slug,
            "page_slug": post.slug,
            "seo_title": content_post.seo_title,
            "search_description": content_post.search_description,
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
            "previous_revision_id": _previous_page_revision_id(post, latest_revision_id),
            "live": post.live,
            "status": publication_status,
            "preview_url": reverse("wagtailadmin_pages:view_draft", args=[post.id]),
            "edit_url": reverse("wagtailadmin_pages:edit", args=[post.id]),
            "api_url": reverse(self.detail_url_name, kwargs={"pk": post.id}),
        }
        data.update(self._extra_serialized_fields(content_post, user=user))
        return data

    def _extra_serialized_fields(self, content_post: Post, *, user: Any) -> dict:
        """Hook for subclasses to add type-specific fields to the serialized response."""
        return {}

    def _public_url(self, post: Post, request: Request) -> str | None:
        url = post.get_url(request=request)
        return url or post.get_full_url(request=request)

    def _reject_unpublishable_episode(self, content: Post) -> None:
        """Enforce the episode publish gate on the revision content about to go live.

        An ``Episode`` is a ``Post``, so this shared check runs for both the post and
        episode publish endpoints; it stops a podcast-audio-less episode from being
        published through either path (mirrors ``CustomEpisodeForm.clean``).
        """
        if isinstance(content, Episode) and content.podcast_audio_id is None:
            raise EditorValidationError(
                {
                    "podcast_audio": [
                        {"code": "required", "message": "An episode must have an audio file to be published."}
                    ]
                }
            )

    def _publish(self, page: Post, *, user: Any, request: Request, publish_denied_message: str, noun: str) -> dict:
        if not page.permissions_for_user(user).can_publish():
            raise EditorPermissionDenied(publish_denied_message, parent_id=None)
        if page.live and not page.has_unpublished_changes:
            raise EditorFlatError(
                "no_unpublished_draft",
                f"This {noun} is already live and has no unpublished draft revision.",
                status_code=status.HTTP_409_CONFLICT,
            )

        revision = page.get_latest_revision()
        if revision is None:
            raise EditorFlatError(
                "no_revision",
                f"This {noun} has no draft revision to publish.",
                status_code=status.HTTP_409_CONFLICT,
            )

        self._reject_unpublishable_episode(revision.as_object())
        revision.publish(user=user)
        page = Post.objects.get(pk=page.pk).specific
        data = self._serialize(page, user=user, content_post=page, revision=revision)
        data["published_revision_id"] = revision.id
        data["public_url"] = self._public_url(page, request)
        return data


class PostCreateView(PostEditorMixin, EditorAPIView):
    required_scopes = {"GET": None, "POST": "write"}

    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        expected = {"parent", "slug"}
        errors: dict[str, list[dict[str, str]]] = {}
        unknown = sorted(set(request.query_params) - expected)
        if unknown:
            errors["non_field_errors"] = [
                {"code": "unknown", "message": f"Unknown query parameter(s): {', '.join(unknown)}."}
            ]
        lookup_data = {}
        for field in expected:
            values = request.query_params.getlist(field)
            if len(values) != 1:
                errors[field] = [
                    {"code": "cardinality", "message": f"Query parameter {field!r} must occur exactly once."}
                ]
            else:
                lookup_data[field] = values[0]
        if errors:
            raise EditorValidationError(errors)

        serializer = PostLookupSerializer(data=lookup_data)
        serializer.is_valid(raise_exception=True)
        parent_id = serializer.validated_data["parent"]
        slug = serializer.validated_data["slug"]

        parent = Blog.objects.filter(pk=parent_id).first()
        if parent is None:
            raise EditorNotFound("Post not found.")
        matches = []
        for candidate in Post.objects.child_of(parent):
            post = candidate.specific
            content_post = post.get_latest_revision_as_object()
            if content_post.slug == slug:
                matches.append((post, content_post))
        if not matches:
            raise EditorNotFound("Post not found.")
        if any(not post.permissions_for_user(request.user).can_edit() for post, _ in matches):
            raise EditorPermissionDenied("You cannot view this draft.", parent_id=None)
        if len(matches) > 1:
            raise EditorFlatError(
                "ambiguous_lookup",
                "More than one editable post has this latest draft slug under the requested parent.",
                status_code=status.HTTP_409_CONFLICT,
            )
        post, content_post = matches[0]
        return Response(self._serialize(post, user=request.user, content_post=content_post))

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
        with transaction.atomic():
            parent = self._lock_parent_for_slug_check(parent, noun="Post")
            self._check_unique_slug(parent, slug)
            post = Post(
                title=title,
                slug=slug,
                seo_title=data["seo_title"],
                search_description=data["search_description"],
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
    required_scopes = {"GET": None, "PATCH": "write"}

    def get(self, request: Request, *args: Any, pk: int, **kwargs: Any) -> Response:
        post = self._get_post(pk, request.user, denied_message="You cannot view this draft.")
        return Response(self._serialize(post, user=request.user))

    @transaction.atomic
    def patch(self, request: Request, *args: Any, pk: int, **kwargs: Any) -> Response:
        serializer = PostUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        submitted_base_revision_id = _submitted_base_revision_id(request, data)
        user = request.user
        if data.get("publish"):
            raise EditorValidationError(
                {"publish": [{"code": "unsupported", "message": "Publishing is not available in this API version."}]}
            )
        if not (set(data) - {"base_revision_id", "publish", "require_unpublished"}):
            raise EditorValidationError(
                {"non_field_errors": [{"code": "required", "message": "Provide at least one field to update."}]}
            )

        post = self._get_post(pk, user, denied_message="You cannot edit this draft.", for_update=True)
        current_revision_id = post.latest_revision_id
        edit_url = reverse("wagtailadmin_pages:edit", args=[post.id])
        if current_revision_id != submitted_base_revision_id:
            raise EditorRevisionConflict(
                current_revision_id=current_revision_id,
                submitted_base_revision_id=submitted_base_revision_id,
                edit_url=edit_url,
            )
        self._enforce_draft_only(post, required=data["require_unpublished"], noun="post")

        draft = post.get_latest_revision().as_object()
        if "title" in data:
            draft.title = data["title"]
        if "slug" in data:
            parent = self._lock_parent_for_slug_check(draft.get_parent(), noun="Post")
            self._check_unique_slug(parent, data["slug"], exclude_id=draft.id)
            draft.slug = data["slug"]
            if not post.live:
                post.slug = data["slug"]
                post.save(update_fields=["slug", "url_path"])
        if "seo_title" in data:
            draft.seo_title = data["seo_title"]
        if "search_description" in data:
            draft.search_description = data["search_description"]
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
    required_scopes = {"POST": "publish"}

    def post(self, request: Request, *args: Any, pk: int, **kwargs: Any) -> Response:
        user = request.user
        post = self._get_post(pk, user, denied_message="You cannot publish this draft.")
        data = self._publish(
            post, user=user, request=request, publish_denied_message="You cannot publish this post.", noun="post"
        )
        return Response(data)


class PreviewMixin:
    required_scopes: dict[str, str | None] = {"GET": None}

    def _render_preview(self, page: Post, request: Request) -> HttpResponse:
        draft = page.get_latest_revision_as_object()
        return draft.make_preview_request(original_request=request._request)


class PostPreviewView(PreviewMixin, PostEditorMixin, EditorAPIView):
    def get(self, request: Request, *args: Any, pk: int, **kwargs: Any) -> HttpResponse:
        post = self._get_post(pk, request.user, denied_message="You cannot preview this draft.")
        return self._render_preview(post, request)


class EpisodeEditorMixin(PostEditorMixin):
    """Shared episode helpers: ``Podcast``-parent enforcement and episode-specific fields."""

    detail_url_name = "cast:api:editor_episode_detail"

    def _get_parent(self, parent_id: int) -> Podcast:
        parent = super()._get_parent(parent_id)
        if not isinstance(parent, Podcast):
            raise EditorValidationError(
                {"parent": [{"code": "invalid", "message": "An episode parent must be a podcast."}]}
            )
        return parent

    def _get_episode(self, pk: int, user: Any, *, denied_message: str, for_update: bool = False) -> Episode:
        # ``.specific()`` resolves the typed subclass row in the same query, so a
        # plain ``Post`` and a missing page both fall through to the not-found path.
        episodes = Post.objects.select_for_update() if for_update else Post.objects
        episode = episodes.filter(pk=pk).specific().first()
        if not isinstance(episode, Episode):
            raise EditorNotFound("Episode not found.")
        if not episode.permissions_for_user(user).can_edit():
            raise EditorPermissionDenied(denied_message, parent_id=None)
        return episode

    def _resolve_podcast_audio(self, ref: dict[str, Any] | None, user: Any) -> Audio | None:
        if not ref:
            return None
        audio = get_choosable_audio(ref["id"], user)
        if audio is None:
            # Collapse missing and not-accessible into one error so we never leak the
            # existence of audio the caller cannot choose (mirrors cover image handling).
            raise EditorValidationError(
                {"podcast_audio.id": [{"code": "not_found", "message": "Referenced media is not available."}]}
            )
        return audio

    def _resolve_season(self, ref: dict[str, Any] | None, podcast: Podcast) -> Season | None:
        if not ref:
            return None
        # Filter by podcast in the query so a missing season and a season belonging to
        # another podcast collapse into one neutral error: distinguishing them would let
        # a caller enumerate Season ids of podcasts they cannot access (the same
        # non-disclosure rule applied to podcast_audio/cover_image above).
        season = Season.objects.filter(pk=ref["id"], podcast_id=podcast.id).first()
        if season is None:
            raise EditorValidationError(
                {
                    "season": [
                        {"code": "invalid", "message": "The selected season must belong to this episode's podcast."}
                    ]
                }
            )
        return season

    def _apply_episode_metadata(
        self, episode: Episode, data: dict, user: Any, *, get_podcast: Callable[[], Podcast]
    ) -> None:
        """Apply the episode-specific scalar/reference fields present in ``data`` to ``episode``.

        ``get_podcast`` is resolved lazily so a PATCH that does not touch ``season`` never
        pays the extra parent/subclass queries needed to validate the season constraint.
        """
        if "podcast_audio" in data:
            episode.podcast_audio = self._resolve_podcast_audio(data["podcast_audio"], user)
        if "season" in data:
            episode.season = self._resolve_season(data["season"], get_podcast())
        if "episode_number" in data:
            episode.episode_number = data["episode_number"]
        if "episode_type" in data:
            episode.episode_type = data["episode_type"]
        if "keywords" in data:
            episode.keywords = data["keywords"]
        if "explicit" in data:
            episode.explicit = data["explicit"]
        if "block" in data:
            episode.block = data["block"]

    def _extra_serialized_fields(self, content_post: Episode, *, user: Any) -> dict:
        podcast_audio = None
        if content_post.podcast_audio_id is not None:
            podcast_audio = {"id": content_post.podcast_audio_id}
        season = None
        if content_post.season_id is not None:
            season = {"id": content_post.season_id}
        return {
            "podcast_audio": podcast_audio,
            "episode_number": content_post.episode_number,
            "episode_type": content_post.episode_type,
            "season": season,
            "keywords": content_post.keywords,
            "explicit": content_post.explicit,
            "block": content_post.block,
        }


class EpisodeCreateView(EpisodeEditorMixin, EditorAPIView):
    required_scopes = {"POST": "write"}

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = EpisodeCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        user = request.user

        if data["publish"]:
            raise EditorValidationError(
                {"publish": [{"code": "unsupported", "message": "Publishing is not available in this API version."}]}
            )

        parent = self._get_parent(data["parent"]["id"])
        if not parent.permissions_for_user(user).can_add_subpage():
            raise EditorPermissionDenied("You cannot add episodes under this page.", parent_id=parent.id)

        title = data["title"]
        slug = data.get("slug") or slugify(title)

        cover_image, cover_alt_text = self._resolve_cover_image(data.get("cover_image"), user)
        categories = self._resolve_categories(data["categories"])
        overview_value = author_blocks_to_overview(data["overview"], user=user)
        body_sections = [{"type": "overview", "value": overview_value}]
        if "detail" in data:
            body_sections.append(
                {"type": "detail", "value": author_blocks_to_section(data["detail"], user=user, path_prefix="detail")}
            )

        episode = Episode(
            title=title,
            slug=slug,
            seo_title=data["seo_title"],
            search_description=data["search_description"],
            owner=user,
            live=False,
            cover_image=cover_image,
            cover_alt_text=cover_alt_text,
            body=json.dumps(body_sections),
        )
        self._apply_episode_metadata(episode, data, user, get_podcast=lambda: parent)
        if data.get("visible_date") is not None:
            episode.visible_date = data["visible_date"]
        with transaction.atomic():
            parent = self._lock_parent_for_slug_check(parent, noun="Episode")
            self._check_unique_slug(parent, slug)
            parent.add_child(instance=episode)
            if data["tags"]:
                episode.tags.add(*data["tags"])
            if categories:
                episode.categories.set(categories)
            if data["tags"] or categories:
                episode.save()
            revision = episode.save_revision(user=user)

        return Response(
            self._serialize(episode, user=user, content_post=episode, revision=revision),
            status=status.HTTP_201_CREATED,
        )


class EpisodeDetailView(EpisodeEditorMixin, EditorAPIView):
    required_scopes = {"GET": None, "PATCH": "write"}

    def get(self, request: Request, *args: Any, pk: int, **kwargs: Any) -> Response:
        episode = self._get_episode(pk, request.user, denied_message="You cannot view this draft.")
        return Response(self._serialize(episode, user=request.user))

    @transaction.atomic
    def patch(self, request: Request, *args: Any, pk: int, **kwargs: Any) -> Response:
        serializer = EpisodeUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        submitted_base_revision_id = _submitted_base_revision_id(request, data)
        user = request.user
        if data.get("publish"):
            raise EditorValidationError(
                {"publish": [{"code": "unsupported", "message": "Publishing is not available in this API version."}]}
            )
        if not (set(data) - {"base_revision_id", "publish", "require_unpublished"}):
            raise EditorValidationError(
                {"non_field_errors": [{"code": "required", "message": "Provide at least one field to update."}]}
            )

        episode = self._get_episode(pk, user, denied_message="You cannot edit this draft.", for_update=True)
        current_revision_id = episode.latest_revision_id
        edit_url = reverse("wagtailadmin_pages:edit", args=[episode.id])
        if current_revision_id != submitted_base_revision_id:
            raise EditorRevisionConflict(
                current_revision_id=current_revision_id,
                submitted_base_revision_id=submitted_base_revision_id,
                edit_url=edit_url,
            )
        self._enforce_draft_only(episode, required=data["require_unpublished"], noun="episode")

        # ``parent`` is immutable on PATCH, so the season constraint resolves against
        # the episode's existing podcast parent — fetched lazily only when a season is sent.
        draft = episode.get_latest_revision().as_object()
        if "title" in data:
            draft.title = data["title"]
        if "slug" in data:
            parent = self._lock_parent_for_slug_check(draft.get_parent(), noun="Episode")
            self._check_unique_slug(parent, data["slug"], exclude_id=draft.id)
            draft.slug = data["slug"]
            if not episode.live:
                episode.slug = data["slug"]
                episode.save(update_fields=["slug", "url_path"])
        if "seo_title" in data:
            draft.seo_title = data["seo_title"]
        if "search_description" in data:
            draft.search_description = data["search_description"]
        if "visible_date" in data:
            draft.visible_date = data["visible_date"]
        if "cover_image" in data:
            draft.cover_image, draft.cover_alt_text = self._resolve_cover_image(data["cover_image"], user)
        if "tags" in data:
            draft.tags.set(data["tags"])
        if "categories" in data:
            draft.categories.set(self._resolve_categories(data["categories"]))
        self._apply_episode_metadata(draft, data, user, get_podcast=lambda: episode.get_parent().specific)
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
        episode.refresh_from_db()
        return Response(self._serialize(episode, user=user, content_post=draft, revision=revision))


class EpisodePublishView(EpisodeEditorMixin, EditorAPIView):
    required_scopes = {"POST": "publish"}

    def post(self, request: Request, *args: Any, pk: int, **kwargs: Any) -> Response:
        user = request.user
        episode = self._get_episode(pk, user, denied_message="You cannot publish this draft.")
        data = self._publish(
            episode,
            user=user,
            request=request,
            publish_denied_message="You cannot publish this episode.",
            noun="episode",
        )
        return Response(data)


class EpisodePreviewView(PreviewMixin, EpisodeEditorMixin, EditorAPIView):
    def get(self, request: Request, *args: Any, pk: int, **kwargs: Any) -> HttpResponse:
        episode = self._get_episode(pk, request.user, denied_message="You cannot preview this draft.")
        return self._render_preview(episode, request)
