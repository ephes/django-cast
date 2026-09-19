from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from wagtail.models import PageLogEntry

from tests.factories import EpisodeFactory, PostFactory, UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture(params=["post", "episode"])
def editable_page(request, blog, podcast, admin_user):
    factory, parent = (PostFactory, blog) if request.param == "post" else (EpisodeFactory, podcast)
    page = factory(parent=parent, title="Original", slug="original", live=False)
    page.save_revision(user=admin_user)
    url = reverse(f"cast:api:editor_{request.param}_detail", kwargs={"pk": page.pk})
    return page, url


@pytest.mark.parametrize("lock_kind", ["none", "owner", "other", "global", "scheduled"])
def test_patch_honors_locks_and_logs_edits(editable_page, admin_user, api_client, settings, lock_kind):
    page, url = editable_page
    settings.WAGTAILADMIN_GLOBAL_EDIT_LOCK = lock_kind == "global"
    if lock_kind in {"owner", "other", "global"}:
        page.locked = True
        page.locked_by = UserFactory() if lock_kind == "other" else admin_user
        page.save(update_fields=["locked", "locked_by"])
    elif lock_kind == "scheduled":
        revision = page.get_latest_revision()
        revision.approved_go_live_at = timezone.now() + timedelta(days=1)
        revision.save(update_fields=["approved_go_live_at"])
    original_revision = page.latest_revision_id
    revision_count = page.revisions.count()
    api_client.force_authenticate(user=admin_user)

    response = api_client.patch(
        url, {"base_revision_id": original_revision, "title": "Edited", "slug": "edited"}, format="json"
    )

    page.refresh_from_db()
    logs = PageLogEntry.objects.filter(page_id=page.pk, action="wagtail.edit")
    if lock_kind in {"other", "global", "scheduled"}:
        assert response.status_code == 409
        assert response.json() == {"code": "page_locked", "detail": "This page is locked for editing."}
        assert page.latest_revision_id == original_revision
        assert page.revisions.count() == revision_count
        assert page.slug == "original"
        assert page.get_latest_revision_as_object().title == "Original"
        assert not logs.exists()
    else:
        assert response.status_code == 200, response.content
        assert page.revisions.count() == revision_count + 1
        assert page.get_latest_revision_as_object().title == "Edited"
        log = logs.get()
        assert log.user_id == admin_user.pk
        assert log.revision_id == page.latest_revision_id == response.json()["latest_revision_id"]
        assert log.content_changed


@pytest.mark.parametrize("precondition", ["revision", "scheduled", "permission"])
def test_patch_checks_preconditions_before_lock(editable_page, admin_user, api_client, precondition):
    page, url = editable_page
    page.locked = True
    page.locked_by = UserFactory()
    page.save(update_fields=["locked", "locked_by"])
    revision = page.get_latest_revision()
    revision.approved_go_live_at = timezone.now() + timedelta(days=1)
    revision.save(update_fields=["approved_go_live_at"])
    actor = UserFactory() if precondition == "permission" else admin_user
    api_client.force_authenticate(user=actor)
    response = api_client.patch(
        url,
        {
            "base_revision_id": 0 if precondition == "revision" else revision.pk,
            "require_unpublished": precondition == "scheduled",
            "title": "Rejected",
        },
        format="json",
    )
    expected_status, expected_code = {
        "revision": (409, "revision_conflict"),
        "scheduled": (409, "scheduled_post"),
        "permission": (403, "permission_denied"),
    }[precondition]
    assert response.status_code == expected_status
    assert response.json()["code"] == expected_code
    page.refresh_from_db()
    assert page.latest_revision_id == revision.pk
    assert not PageLogEntry.objects.filter(page_id=page.pk, action="wagtail.edit").exists()


def test_edit_log_failure_rolls_back_revision_and_slug(editable_page, admin_user, api_client, mocker):
    page, url = editable_page
    revision_id = page.latest_revision_id
    revision_count = page.revisions.count()
    api_client.force_authenticate(user=admin_user)
    log = mocker.patch("wagtail.models.pages.log", side_effect=RuntimeError("log failed"))
    with pytest.raises(RuntimeError, match="log failed"):
        api_client.patch(url, {"base_revision_id": revision_id, "slug": "edited"}, format="json")
    log.assert_called_once()
    page.refresh_from_db()
    assert page.slug == "original"
    assert page.latest_revision_id == revision_id
    assert page.revisions.count() == revision_count
