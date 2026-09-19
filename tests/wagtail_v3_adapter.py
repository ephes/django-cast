"""Test-only revision-aware adapter over Wagtail 8's v3 update and publish helpers."""

from typing import Any, Literal

import swapper
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Query, Router, Schema, Status
from wagtail.actions import action_registry
from wagtail.api.v3.auth import BearerTokenAuth
from wagtail.api.v3.form_data import build_page_update_form
from wagtail.api.v3.permissions import require_any_permission
from wagtail.api.v3.routers.pages import PageUpdateSchema
from wagtail.api.v3.schemas.pages import PageTypeInjectingBody

from cast.content.blocks import ConversionContext
from cast.content.convert import author_blocks_to_section
from cast.content.errors import ContentValidationError
from cast.content.sections import body_sections_with_replacements, section_value

Page = swapper.load_model("wagtailcore", "Page")

router = Router(auth=BearerTokenAuth(), tags=["Cast v3 experiment"])


class RevisionUpdateMeta(Schema):
    type: str


class RevisionUpdateResult(Schema):
    id: int
    meta: RevisionUpdateMeta
    base_revision_id: int
    latest_revision_id: int


class AdapterError(Schema):
    code: Literal["invalid_base_revision", "publish_not_supported", "empty_body_update"]
    detail: str


class RevisionConflict(Schema):
    code: Literal["revision_conflict"]
    current_revision_id: int | None
    submitted_base_revision_id: int


class DraftStateConflict(Schema):
    code: Literal["published_post", "scheduled_post"]
    detail: str


class RevisionPublishResult(Schema):
    id: int
    meta: RevisionUpdateMeta
    revision_id: int
    live: bool
    live_revision_id: int | None


class AuthorBodyUpdate(Schema):
    overview: list[dict[str, Any]] | None = None
    detail: list[dict[str, Any]] | None = None


class BodyValidationError(Schema):
    code: Literal["validation_error"]
    errors: dict[str, list[dict[str, str]]]


def _base_revision_id(request: HttpRequest) -> int | None:
    """Parse the strong integer ETag used by this disposable experiment."""
    value = request.headers.get("If-Match", "").strip()
    if len(value) < 3 or value[0] != '"' or value[-1] != '"':
        return None
    revision_id = value[1:-1]
    return int(revision_id) if revision_id.isdecimal() else None


@router.patch(
    "/{page_id}/",
    response={200: RevisionUpdateResult, 400: AdapterError, 409: RevisionConflict | DraftStateConflict},
    url_name="cast_revision_update",
    summary="Revision-aware Cast page update experiment",
)
@require_any_permission(Page, ("change",))
@transaction.atomic
def revision_aware_update(
    request: HttpRequest,
    page_id: int,
    data: PageUpdateSchema = PageTypeInjectingBody(...),
    require_unpublished: bool = Query(False),
):
    base_revision_id = _base_revision_id(request)
    if base_revision_id is None:
        return Status(
            400,
            {
                "code": "invalid_base_revision",
                "detail": 'Supply the base revision as a quoted integer in the "If-Match" header.',
            },
        )
    if data.meta.action is not None:
        return Status(
            400,
            {
                "code": "publish_not_supported",
                "detail": "This experiment only evaluates draft updates.",
            },
        )

    page = get_object_or_404(Page.objects.select_for_update(), pk=page_id).specific
    current_revision_id = page.latest_revision_id
    if current_revision_id != base_revision_id:
        return Status(
            409,
            {
                "code": "revision_conflict",
                "current_revision_id": current_revision_id,
                "submitted_base_revision_id": base_revision_id,
            },
        )
    if require_unpublished and page.live:
        return Status(
            409,
            {
                "code": "published_post",
                "detail": "This page is already live; the requested draft-only update was refused.",
            },
        )
    if require_unpublished:
        # Match the editor API's guard: an actor can approve any existing,
        # previously unscheduled revision, so lock them all before checking.
        # Creating a new revision updates the already locked page row. SQLite
        # does not prove those PostgreSQL serialization assumptions.
        locked_schedules = page.revisions.select_for_update().values_list("approved_go_live_at", flat=True)
        if any(approved_go_live_at is not None for approved_go_live_at in locked_schedules):
            return Status(
                409,
                {
                    "code": "scheduled_post",
                    "detail": "This page is scheduled for publication; the requested draft-only update was refused.",
                },
            )

    draft = page.get_latest_revision().as_object()
    form = build_page_update_form(draft, data, request.user)
    action_class = action_registry.get_action_class(type(draft), "edit")
    action = action_class(form.instance, user=request.user, form=form, publish=False)
    action.execute()

    return {
        "id": page.pk,
        "meta": {"type": page._meta.label},
        "base_revision_id": base_revision_id,
        "latest_revision_id": action.revision.pk,
    }


@router.post(
    "/{page_id}/actions/publish/",
    response={200: RevisionPublishResult, 400: AdapterError, 409: RevisionConflict},
    url_name="cast_revision_publish",
    summary="Revision-bound Cast page publish experiment",
)
@require_any_permission(Page, ("publish",))
@transaction.atomic
def revision_bound_publish(request: HttpRequest, page_id: int):
    selected_revision_id = _base_revision_id(request)
    if selected_revision_id is None:
        return Status(
            400,
            {
                "code": "invalid_base_revision",
                "detail": 'Supply the selected revision as a quoted integer in the "If-Match" header.',
            },
        )

    # A draft writer must update this locked row to make its revision latest.
    # SQLite ignores the lock, so the sequential tests do not prove that race.
    page = get_object_or_404(Page.objects.select_for_update(), pk=page_id).specific
    if not page.permissions_for_user(request.user).can_publish():
        # Check before comparing so an unauthorized caller learns no revision id.
        raise PermissionDenied
    current_revision_id = page.latest_revision_id
    if current_revision_id != selected_revision_id:
        return Status(
            409,
            {
                "code": "revision_conflict",
                "current_revision_id": current_revision_id,
                "submitted_base_revision_id": selected_revision_id,
            },
        )

    revision = page.revisions.get(pk=selected_revision_id)
    action_class = action_registry.get_action_class(Page, "publish")
    action_class(revision, user=request.user).execute()

    published = Page.objects.get(pk=page.pk)
    return {
        "id": published.pk,
        "meta": {"type": page._meta.label},
        "revision_id": revision.pk,
        "live": published.live,
        "live_revision_id": published.live_revision_id,
    }


@router.get(
    "/{page_id}/preview/",
    response={200: None},
    url_name="cast_draft_preview",
    summary="Rendered Cast draft preview experiment",
)
@require_any_permission(Page, ("change",))
def draft_preview(request: HttpRequest, page_id: int):
    page = get_object_or_404(Page, pk=page_id).specific
    # Match the editor API: previewing a draft requires edit permission.
    if not page.permissions_for_user(request.user).can_edit():
        raise PermissionDenied
    return page.get_latest_revision_as_object().make_preview_request(original_request=request)


@router.patch(
    "/{page_id}/body/",
    response={200: RevisionUpdateResult, 400: AdapterError, 409: RevisionConflict, 422: BodyValidationError},
    url_name="cast_body_update",
    summary="Cast author-block body update experiment",
)
@require_any_permission(Page, ("change",))
@transaction.atomic
def author_body_update(request: HttpRequest, page_id: int, data: AuthorBodyUpdate):
    base_revision_id = _base_revision_id(request)
    if base_revision_id is None:
        return Status(
            400,
            {
                "code": "invalid_base_revision",
                "detail": 'Supply the base revision as a quoted integer in the "If-Match" header.',
            },
        )
    sections = {name: blocks for name, blocks in data.dict().items() if blocks is not None}
    if not sections:
        return Status(400, {"code": "empty_body_update", "detail": "Supply overview, detail, or both."})

    page = get_object_or_404(Page.objects.select_for_update(), pk=page_id).specific
    if not page.permissions_for_user(request.user).can_edit():
        raise PermissionDenied
    if page.latest_revision_id != base_revision_id:
        return Status(
            409,
            {
                "code": "revision_conflict",
                "current_revision_id": page.latest_revision_id,
                "submitted_base_revision_id": base_revision_id,
            },
        )

    draft = page.get_latest_revision().as_object()
    replacements = {}
    try:
        for section, blocks in sections.items():
            ctx = ConversionContext(
                section=section,
                user=request.user,
                existing_section=section_value(draft.body.raw_data, section),
            )
            replacements[section] = author_blocks_to_section(blocks, ctx=ctx)
    except ContentValidationError as error:
        return Status(422, {"code": "validation_error", "errors": error.error_map})
    draft.body = body_sections_with_replacements(draft.body.raw_data, replacements)

    action_class = action_registry.get_action_class(type(draft), "edit")
    action = action_class(draft, user=request.user, publish=False)
    action.execute()
    return {
        "id": page.pk,
        "meta": {"type": page._meta.label},
        "base_revision_id": base_revision_id,
        "latest_revision_id": action.revision.pk,
    }
