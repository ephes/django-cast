from __future__ import annotations

import logging
import subprocess
import uuid
from collections.abc import Callable
from typing import Any, Protocol, cast
from urllib.parse import urlsplit, urlunsplit

from django.conf import settings
from django.core.cache import cache
from django.db.models import Q, QuerySet
from django.urls import NoReverseMatch, reverse
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response
from wagtail.images import get_image_model
from wagtail.images.forms import get_image_form
from wagtail.images.permissions import permission_policy as image_permission_policy
from wagtail.models import Collection
from wagtail.permission_policies.collections import CollectionOwnershipPermissionPolicy

from ...forms import AudioForm, get_video_form
from ...media_probe import media_probe_budget
from ...models import Audio, Video
from ...models.audio import AudioDurationProbeError, AudioDurationProbeTimeout
from ..views import StandardResultsSetPagination
from .errors import EditorFlatError, EditorValidationError
from .views import EditorAPIView

logger = logging.getLogger(__name__)

audio_permission_policy = CollectionOwnershipPermissionPolicy(Audio, auth_model=Audio, owner_field_name="user")
video_permission_policy = CollectionOwnershipPermissionPolicy(Video, auth_model=Video, owner_field_name="user")

EDITOR_MEDIA_PROBE_SECONDS = 10
EDITOR_MEDIA_UPLOAD_LOCK_SECONDS = 7200
AUDIO_FILE_FIELDS = ("m4a", "mp3", "oga", "opus")


class CollectionMemberForm(Protocol):
    def is_valid(self) -> bool: ...  # pragma: no cover

    def save(self, commit: bool = ...) -> Any: ...  # pragma: no cover

    def save_m2m(self) -> None: ...  # pragma: no cover


class CollectionMemberFormClass(Protocol):
    def __call__(
        self, *args: Any, instance: Any, user: Any, **kwargs: Any
    ) -> CollectionMemberForm: ...  # pragma: no cover


class CollectionMediaPermissionPolicy(Protocol):
    def collections_user_has_permission_for(
        self, user: Any, action: str
    ) -> QuerySet[Collection]: ...  # pragma: no cover

    def user_has_permission_for_instance(self, user: Any, action: str, instance: Any) -> bool: ...  # pragma: no cover


def _relative_field_url(field: Any) -> str | None:
    if not field:
        return None
    try:
        url = field.url
    except ValueError:
        return None
    parsed = urlsplit(url)
    if parsed.scheme or parsed.netloc:
        return urlunsplit(("", "", parsed.path, parsed.query, parsed.fragment))
    return url


def _collection_ref(obj: Any) -> dict[str, Any] | None:
    collection = getattr(obj, "collection", None)
    if collection is None:
        return None
    return {"id": collection.id, "name": collection.name}


def _tag_names(obj: Any) -> list[str]:
    return [tag.name for tag in obj.tags.all()]


def _can_edit(user: Any, obj: Any, *, policy: CollectionMediaPermissionPolicy) -> bool:
    return bool(policy.user_has_permission_for_instance(user, "change", obj))


def _edit_url(user: Any, obj: Any, *, policy: CollectionMediaPermissionPolicy, route_name: str) -> str | None:
    if not _can_edit(user, obj, policy=policy):
        return None
    try:
        return reverse(route_name, args=[obj.pk])
    except NoReverseMatch:
        return None


def serialize_image(image: Any, *, user: Any) -> dict[str, Any]:
    return {
        "id": image.id,
        "type": image._meta.label,
        "title": image.title,
        "file": _relative_field_url(image.file),
        "width": image.width,
        "height": image.height,
        "collection": _collection_ref(image),
        "tags": _tag_names(image),
        "edit_url": _edit_url(user, image, policy=image_permission_policy, route_name="wagtailimages:edit"),
    }


def serialize_audio(audio: Audio, *, user: Any) -> dict[str, Any]:
    return {
        "id": audio.id,
        "type": audio._meta.label,
        "title": audio.title,
        "subtitle": audio.subtitle,
        "transcript_diarization_mode": audio.transcript_diarization_mode,
        "file_formats": audio.file_formats,
        "mp3": _relative_field_url(audio.mp3),
        "m4a": _relative_field_url(audio.m4a),
        "oga": _relative_field_url(audio.oga),
        "opus": _relative_field_url(audio.opus),
        "collection": _collection_ref(audio),
        "tags": _tag_names(audio),
        "edit_url": _edit_url(user, audio, policy=audio_permission_policy, route_name="castaudio:edit"),
    }


def serialize_video(video: Video, *, user: Any) -> dict[str, Any]:
    return {
        "id": video.id,
        "type": video._meta.label,
        "title": video.title,
        "original": _relative_field_url(video.original),
        "poster": _relative_field_url(video.poster),
        "collection": _collection_ref(video),
        "tags": _tag_names(video),
        "edit_url": _edit_url(user, video, policy=video_permission_policy, route_name="castvideo:edit"),
    }


def _ancestor_paths(collection: Collection) -> list[str]:
    return [collection.path[:depth] for depth in range(collection.steplen, len(collection.path), collection.steplen)]


def _collection_item(
    collection: Collection, *, ancestors_by_path: dict[str, Collection] | None = None
) -> dict[str, Any]:
    if ancestors_by_path is None:
        ancestor_objects = list(collection.get_ancestors())
    else:
        ancestor_objects = [
            ancestors_by_path[path] for path in _ancestor_paths(collection) if path in ancestors_by_path
        ]
    ancestors = [{"id": ancestor.id, "name": ancestor.name} for ancestor in ancestor_objects]
    names = [ancestor["name"] for ancestor in ancestors] + [collection.name]
    return {
        "id": collection.id,
        "name": collection.name,
        "breadcrumb": " / ".join(names),
        "ancestors": ancestors,
    }


def _reject_unsupported_query_params(request: Request, allowed: set[str]) -> None:
    unsupported = sorted(set(request.query_params) - allowed)
    if unsupported:
        raise EditorValidationError(
            {
                name: [
                    {
                        "code": "unsupported_parameter",
                        "message": f"Query parameter {name!r} is not supported.",
                    }
                ]
                for name in unsupported
            }
        )


def _parse_collection_id(value: Any) -> int:
    try:
        collection_id = int(value)
    except (TypeError, ValueError):
        raise EditorValidationError(
            {"collection": [{"code": "invalid", "message": "Collection must be an integer ID."}]}
        )
    if isinstance(value, bool) or collection_id < 1:
        raise EditorValidationError(
            {"collection": [{"code": "invalid", "message": "Collection must be an integer ID."}]}
        )
    return collection_id


def _usable_image_collections(user: Any) -> QuerySet[Collection]:
    addable = image_permission_policy.collections_user_has_permission_for(user, "add")
    choosable = image_permission_policy.collections_user_has_permission_for(user, "choose")
    return addable.filter(pk__in=choosable.values("pk")).order_by("path", "id")


def _usable_owned_media_collections(user: Any, *, policy: CollectionMediaPermissionPolicy) -> QuerySet[Collection]:
    return policy.collections_user_has_permission_for(user, "add").order_by("path", "id")


def _resolve_collection(request: Request, usable: QuerySet[Collection]) -> Collection:
    supplied = request.data.get("collection")
    if supplied not in (None, ""):
        collection_id = _parse_collection_id(supplied)
        collection = usable.filter(pk=collection_id).first()
        if collection is None:
            raise EditorValidationError(
                {
                    "collection": [
                        {
                            "code": "collection_permission_denied",
                            "message": "Collection is not available for this upload.",
                        }
                    ]
                }
            )
        return collection

    collections = list(usable[:2])
    if not collections:
        raise EditorFlatError(
            "no_upload_collection", "No upload collection is available.", status_code=status.HTTP_403_FORBIDDEN
        )
    if len(collections) > 1:
        raise EditorValidationError(
            {"collection": [{"code": "ambiguous", "message": "Select a collection for this upload."}]}
        )
    return collections[0]


def _form_errors(form: Any) -> dict[str, list[dict[str, str]]]:
    errors: dict[str, list[dict[str, str]]] = {}
    error_data = form.errors.as_data()
    for field, field_errors in error_data.items():
        key = "non_field_errors" if field == "__all__" else field
        errors[key] = []
        for error in field_errors:
            code = error.code or "invalid"
            message = "; ".join(error.messages)
            errors[key].append({"code": code, "message": message})
    return errors


def _delete_field_file(field: Any) -> None:
    if getattr(field, "name", ""):
        field.delete(save=False)


def _cleanup_media_object(obj: Any, field_names: tuple[str, ...]) -> bool:
    try:
        for field_name in field_names:
            _delete_field_file(getattr(obj, field_name))
        if getattr(obj, "pk", None) is not None:
            obj.delete()
    except Exception:
        logger.exception("Editor media cleanup failed for %s pk=%s", obj._meta.label, getattr(obj, "pk", None))
        return False
    return True


def _flat_error(code: str, detail: str, *, http_status: int) -> Response:
    return Response({"code": code, "detail": detail}, status=http_status)


def _editor_media_probe_seconds() -> float:
    return float(getattr(settings, "CAST_EDITOR_MEDIA_PROBE_SECONDS", EDITOR_MEDIA_PROBE_SECONDS))


class EditorMediaListMixin:
    pagination_class = StandardResultsSetPagination
    allowed_query_params = {"q", "tag", "page", "pageSize", "format"}
    serializer_func: Callable[..., dict[str, Any]]

    def _paginate(self, queryset: QuerySet, request: Request) -> Response:
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request, view=self)
        assert page is not None
        data = [self.serializer_func(obj, user=request.user) for obj in page]
        return paginator.get_paginated_response(data)

    def _apply_tags(self, queryset: QuerySet, request: Request) -> QuerySet:
        for tag in request.query_params.getlist("tag"):
            queryset = queryset.filter(tags__name=tag)
        return queryset


class EditorImageListCreateView(EditorMediaListMixin, EditorAPIView):
    parser_classes = (MultiPartParser, FormParser)
    serializer_func = staticmethod(serialize_image)

    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        _reject_unsupported_query_params(request, self.allowed_query_params)
        queryset = image_permission_policy.instances_user_has_permission_for(request.user, "choose").select_related(
            "collection", "uploaded_by_user"
        )
        q = request.query_params.get("q")
        if q:
            queryset = queryset.filter(title__icontains=q)
        queryset = self._apply_tags(queryset, request).prefetch_related("tags")
        return self._paginate(queryset.order_by("-created_at", "-id"), request)

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        collection = _resolve_collection(request, _usable_image_collections(request.user))
        image_model = get_image_model()
        image = image_model(uploaded_by_user=request.user, collection=collection)
        form_data = request.data.copy()
        form_data["collection"] = str(collection.pk)
        form_class = get_image_form(image_model)
        form = form_class(form_data, request.FILES, instance=image, user=request.user)
        if not form.is_valid():
            raise EditorValidationError(_form_errors(form))
        image = form.save(commit=False)
        image.uploaded_by_user = request.user
        image.collection = collection
        image.save()
        form.save_m2m()
        return Response(serialize_image(image, user=request.user), status=status.HTTP_201_CREATED)


class EditorAudioListCreateView(EditorMediaListMixin, EditorAPIView):
    parser_classes = (MultiPartParser, FormParser)
    serializer_func = staticmethod(serialize_audio)

    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        _reject_unsupported_query_params(request, self.allowed_query_params)
        queryset = audio_permission_policy.instances_user_has_permission_for(request.user, "choose").select_related(
            "collection", "user"
        )
        q = request.query_params.get("q")
        if q:
            queryset = queryset.filter(Q(title__icontains=q) | Q(subtitle__icontains=q))
        queryset = self._apply_tags(queryset, request).prefetch_related("tags")
        return self._paginate(queryset.order_by("-created", "-id"), request)

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return _with_upload_lock(request.user, lambda: self._post_locked(request))

    def _post_locked(self, request: Request) -> Response:
        collection = _resolve_collection(
            request, _usable_owned_media_collections(request.user, policy=audio_permission_policy)
        )
        if request.data.get("transcript_diarization_mode") == Audio.TranscriptDiarizationMode.ENABLED:
            raise EditorValidationError(
                {
                    "transcript_diarization_mode": [
                        {"code": "unsupported", "message": "Enabled diarization is not supported here."}
                    ]
                }
            )
        submitted_files = [field for field in AUDIO_FILE_FIELDS if field in request.FILES]
        if not submitted_files:
            raise EditorValidationError(
                {"non_field_errors": [{"code": "required", "message": "Submit one audio file."}]}
            )
        if len(submitted_files) > 1:
            raise EditorValidationError(
                {"non_field_errors": [{"code": "too_many_files", "message": "Submit only one audio file."}]}
            )
        audio = Audio(user=request.user, collection=collection)
        form = AudioForm(request.data, request.FILES, instance=audio, user=request.user)
        if not form.is_valid():
            raise EditorValidationError(_form_errors(form))
        try:
            with media_probe_budget(_editor_media_probe_seconds()):
                audio = form.save()
        except (subprocess.TimeoutExpired, AudioDurationProbeTimeout):
            if not _cleanup_media_object(audio, AUDIO_FILE_FIELDS):
                return _flat_error("cleanup_failed", "Upload cleanup failed.", http_status=500)
            return _flat_error("probe_timeout", "Audio probing exceeded the editor upload budget.", http_status=422)
        except AudioDurationProbeError:
            logger.exception("Editor audio probing failed for upload title=%r", audio.title)
            if not _cleanup_media_object(audio, AUDIO_FILE_FIELDS):
                return _flat_error("cleanup_failed", "Upload cleanup failed.", http_status=500)
            return _flat_error("probe_failed", "Audio probing failed.", http_status=422)
        if not audio_permission_policy.user_has_permission_for_instance(request.user, "choose", audio):
            if not _cleanup_media_object(audio, AUDIO_FILE_FIELDS):
                return _flat_error("cleanup_failed", "Upload cleanup failed.", http_status=500)
            return _flat_error("post_save_permission_denied", "Uploaded audio is not selectable.", http_status=403)
        return Response(serialize_audio(audio, user=request.user), status=status.HTTP_201_CREATED)


class EditorVideoListCreateView(EditorMediaListMixin, EditorAPIView):
    parser_classes = (MultiPartParser, FormParser)
    serializer_func = staticmethod(serialize_video)

    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        _reject_unsupported_query_params(request, self.allowed_query_params)
        queryset = video_permission_policy.instances_user_has_permission_for(request.user, "choose").select_related(
            "collection", "user"
        )
        q = request.query_params.get("q")
        if q:
            queryset = queryset.filter(title__icontains=q)
        queryset = self._apply_tags(queryset, request).prefetch_related("tags")
        return self._paginate(queryset.order_by("-created", "-id"), request)

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return _with_upload_lock(request.user, lambda: self._post_locked(request))

    def _post_locked(self, request: Request) -> Response:
        collection = _resolve_collection(
            request, _usable_owned_media_collections(request.user, policy=video_permission_policy)
        )
        video = Video(user=request.user, collection=collection)
        form_data = request.data.copy()
        form_data["collection"] = str(collection.pk)
        form_class = cast(CollectionMemberFormClass, get_video_form())
        form = form_class(form_data, request.FILES, instance=video, user=request.user)
        if not form.is_valid():
            raise EditorValidationError(_form_errors(form))
        with media_probe_budget(_editor_media_probe_seconds()):
            video = form.save()
        if not video_permission_policy.user_has_permission_for_instance(request.user, "choose", video):
            if not _cleanup_media_object(video, ("original", "poster")):
                return _flat_error("cleanup_failed", "Upload cleanup failed.", http_status=500)
            return _flat_error("post_save_permission_denied", "Uploaded video is not selectable.", http_status=403)
        return Response(serialize_video(video, user=request.user), status=status.HTTP_201_CREATED)


def _with_upload_lock(user: Any, callback: Callable[[], Response]) -> Response:
    key = f"cast:editor-media-upload:{user.pk}"
    owner = uuid.uuid4().hex
    timeout = int(getattr(settings, "CAST_EDITOR_MEDIA_UPLOAD_LOCK_SECONDS", EDITOR_MEDIA_UPLOAD_LOCK_SECONDS))
    if not cache.add(key, owner, timeout=timeout):
        return _flat_error("rate_limited", "Another audio or video upload is already in progress.", http_status=429)
    try:
        return callback()
    finally:
        if cache.get(key) == owner:
            cache.delete(key)


class EditorMediaCollectionsView(EditorAPIView):
    pagination_class = StandardResultsSetPagination
    allowed_query_params = {"type", "page", "pageSize", "format"}

    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        _reject_unsupported_query_params(request, self.allowed_query_params)
        media_type = request.query_params.get("type")
        if media_type is None:
            raise EditorValidationError(
                {"type": [{"code": "required", "message": "This query parameter is required."}]}
            )
        if media_type == "image":
            queryset = _usable_image_collections(request.user)
        elif media_type == "audio":
            queryset = _usable_owned_media_collections(request.user, policy=audio_permission_policy)
        elif media_type == "video":
            queryset = _usable_owned_media_collections(request.user, policy=video_permission_policy)
        else:
            raise EditorValidationError({"type": [{"code": "invalid_choice", "message": "Unsupported media type."}]})

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset.order_by("path", "id"), request, view=self)
        assert page is not None
        ancestor_path_set = {path for collection in page for path in _ancestor_paths(collection)}
        ancestors_by_path = {
            collection.path: collection for collection in Collection.objects.filter(path__in=ancestor_path_set)
        }
        return paginator.get_paginated_response(
            [_collection_item(collection, ancestors_by_path=ancestors_by_path) for collection in page]
        )
