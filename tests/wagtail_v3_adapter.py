"""Test-only revision-aware adapter over Wagtail 8's v3 update helpers."""

from typing import Literal

import swapper
from django.db import transaction
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Router, Schema, Status
from wagtail.actions import action_registry
from wagtail.api.v3.auth import BearerTokenAuth
from wagtail.api.v3.form_data import build_page_update_form
from wagtail.api.v3.permissions import require_any_permission
from wagtail.api.v3.routers.pages import PageUpdateSchema
from wagtail.api.v3.schemas.pages import PageTypeInjectingBody

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
    code: Literal["invalid_base_revision", "publish_not_supported"]
    detail: str


class RevisionConflict(Schema):
    code: Literal["revision_conflict"]
    current_revision_id: int | None
    submitted_base_revision_id: int


def _base_revision_id(request: HttpRequest) -> int | None:
    """Parse the strong integer ETag used by this disposable experiment."""
    value = request.headers.get("If-Match", "").strip()
    if len(value) < 3 or value[0] != '"' or value[-1] != '"':
        return None
    revision_id = value[1:-1]
    return int(revision_id) if revision_id.isdecimal() else None


@router.patch(
    "/{page_id}/",
    response={200: RevisionUpdateResult, 400: AdapterError, 409: RevisionConflict},
    url_name="cast_revision_update",
    summary="Revision-aware Cast page update experiment",
)
@require_any_permission(Page, ("change",))
@transaction.atomic
def revision_aware_update(
    request: HttpRequest,
    page_id: int,
    data: PageUpdateSchema = PageTypeInjectingBody(...),
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
