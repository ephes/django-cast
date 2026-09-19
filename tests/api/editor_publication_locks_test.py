import threading
import time
from datetime import timedelta

import pytest
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.db import close_old_connections, connection, transaction
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient
from wagtail.models import GroupApprovalTask, PageLogEntry, Revision, TaskState, Workflow, WorkflowPage, WorkflowTask

from cast.api.editor.views import PostEditorMixin
from cast.models import Gallery
from tests.api.editor_publish_preview_test import grant_wagtail_admin_access, page_permission_user
from tests.factories import EpisodeFactory, PostFactory, UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture(params=["post", "episode", "episode-via-post"])
def publication_page(request, blog, podcast, admin_user, audio):
    if request.param == "post":
        page = PostFactory(parent=blog, title="Publication draft", slug="publication-draft", live=False)
    else:
        page = EpisodeFactory(
            parent=podcast, title="Publication draft", slug="publication-draft", live=False, podcast_audio=audio
        )
    page.save_revision(user=admin_user)
    endpoint = "episode" if request.param == "episode" else "post"
    return page, reverse(f"cast:api:editor_{endpoint}_publish", kwargs={"pk": page.pk})


@pytest.fixture
def approval_workflow():
    group = Group.objects.create(name="Publication reviewers")
    task = GroupApprovalTask.objects.create(name="Approve publication")
    task.groups.add(group)
    workflow = Workflow.objects.create(name="Publication review")
    WorkflowTask.objects.create(workflow=workflow, task=task, sort_order=0)
    return workflow, group


def publication_state(page):
    """Snapshot persisted publication, workflow, audit and media state."""
    return {
        "page": type(page).objects.filter(pk=page.pk).values().get(),
        "revisions": list(page.revisions.order_by("pk").values()),
        "workflows": list(page.workflow_states.order_by("pk").values()),
        "tasks": list(TaskState.objects.filter(workflow_state__in=page.workflow_states.all()).order_by("pk").values()),
        "logs": list(PageLogEntry.objects.filter(page_id=page.pk).order_by("pk").values()),
        "media": {
            name: list(getattr(page, name).order_by("pk").values_list("pk", flat=True))
            for name in ("images", "audios", "videos", "galleries")
        },
        "galleries": list(Gallery.objects.order_by("pk").values()),
    }


@pytest.mark.parametrize("superuser", [False, True])
@pytest.mark.parametrize("lock_kind", ["none", "owner", "other", "ownerless", "global", "scheduled"])
def test_publish_honors_locks(publication_page, api_client, settings, superuser, lock_kind):
    page, url = publication_page
    actor = page_permission_user(codenames=("change_page", "publish_page"))
    grant_wagtail_admin_access(actor)
    actor.is_superuser = superuser
    actor.save()
    settings.WAGTAILADMIN_GLOBAL_EDIT_LOCK = lock_kind == "global"
    if lock_kind in {"owner", "other", "ownerless", "global"}:
        page.locked = True
        page.locked_by = {"ownerless": None, "other": UserFactory()}.get(lock_kind, actor)
        page.save(update_fields=["locked", "locked_by"])
    elif lock_kind == "scheduled":
        draft = page.get_latest_revision_as_object()
        draft.go_live_at = timezone.now() + timedelta(days=1)
        draft.save_revision().publish(user=actor)
        # Protect even an older approved revision when a newer draft exists.
        page.refresh_from_db()
        page.title = "New draft must not replace the schedule"
        page.save_revision()
    before = publication_state(page)
    api_client.force_authenticate(user=actor)

    response = api_client.post(url)

    if lock_kind in {"none", "owner"}:
        assert response.status_code == 200, response.content
        page.refresh_from_db()
        assert page.live
        assert page.live_revision_id == page.latest_revision_id
        assert page.locked == (lock_kind == "owner")
        assert page.locked_by_id == (actor.pk if lock_kind == "owner" else None)
    else:
        assert response.status_code == 409, response.content
        assert response.json() == {"code": "page_locked", "detail": "This page is locked for publication."}
        assert publication_state(page) == before


@pytest.mark.parametrize("actor_kind", ["publisher", "reviewer", "superuser"])
@pytest.mark.parametrize("needs_changes", [False, True])
@pytest.mark.parametrize("cancel_on_publish", [False, True])
def test_publish_does_not_bypass_workflow(
    publication_page, approval_workflow, api_client, admin_user, settings, actor_kind, needs_changes, cancel_on_publish
):
    page, url = publication_page
    workflow, reviewers = approval_workflow
    actor = page_permission_user(codenames=("change_page", "publish_page"))
    grant_wagtail_admin_access(actor)
    if actor_kind == "reviewer":
        actor.groups.add(reviewers)
    elif actor_kind == "superuser":
        actor.is_superuser = True
        actor.save()
    settings.WAGTAIL_WORKFLOW_CANCEL_ON_PUBLISH = cancel_on_publish
    state = workflow.start(page, admin_user)
    if needs_changes:
        state.current_task_state.reject(user=admin_user)
    page.refresh_from_db()
    state.refresh_from_db()
    assert state.status == ("needs_changes" if needs_changes else "in_progress")
    lock = page.get_lock()
    if needs_changes:
        assert lock is None
    else:
        assert lock.for_user(actor) == (actor_kind == "publisher")
    before = publication_state(page)
    api_client.force_authenticate(user=actor)

    response = api_client.post(url)

    assert response.status_code == 409, response.content
    assert response.json()["code"] == "workflow_active"
    assert publication_state(page) == before


@pytest.mark.parametrize("workflow_status", ["not-started", "cancelled", "approved"])
def test_inactive_workflow_does_not_block_publication(
    publication_page, approval_workflow, api_client, admin_user, workflow_status
):
    page, url = publication_page
    workflow, _ = approval_workflow
    WorkflowPage.objects.create(page=page, workflow=workflow)
    if workflow_status != "not-started":
        state = workflow.start(page, admin_user)
        if workflow_status == "cancelled":
            state.cancel(user=admin_user)
        else:
            state.current_task_state.approve(user=admin_user)
            page.refresh_from_db()
            assert page.live  # Workflow completion must still publish normally.
            page.title = "Next draft"
            page.save_revision()
    api_client.force_authenticate(user=admin_user)

    response = api_client.post(url)

    assert response.status_code == 200, response.content


@pytest.mark.parametrize("applies", [False, True])
def test_publish_honors_custom_lock(publication_page, api_client, admin_user, mocker, applies):
    page, url = publication_page
    lock = mocker.Mock()
    lock.for_user.return_value = applies
    mocker.patch.object(type(page), "get_lock", return_value=lock)
    api_client.force_authenticate(user=admin_user)
    before = publication_state(page)

    response = api_client.post(url)

    lock.for_user.assert_called_once_with(admin_user)
    assert response.status_code == (409 if applies else 200), response.content
    if applies:
        assert response.json()["code"] == "page_locked"
        assert publication_state(page) == before


@pytest.mark.parametrize("precondition", ["permission", "revision", "no-draft", "no-revision"])
def test_publish_preconditions_take_precedence(publication_page, api_client, admin_user, precondition):
    page, url = publication_page
    page.locked = True
    page.locked_by = UserFactory()
    page.save(update_fields=["locked", "locked_by"])
    actor = admin_user
    headers = {}
    if precondition == "permission":
        actor = page_permission_user(codenames=("change_page",))
        grant_wagtail_admin_access(actor)
    elif precondition == "revision":
        headers["HTTP_IF_MATCH"] = '"0"'
    elif precondition == "no-draft":
        type(page).objects.filter(pk=page.pk).update(live=True, has_unpublished_changes=False)
    else:
        type(page).objects.filter(pk=page.pk).update(latest_revision=None)
    before = publication_state(page)
    api_client.force_authenticate(user=actor)

    response = api_client.post(url, **headers)

    expected_status, expected_code = {
        "permission": (403, "permission_denied"),
        "revision": (409, "revision_conflict"),
        "no-draft": (409, "no_unpublished_draft"),
        "no-revision": (409, "no_revision"),
    }[precondition]
    assert response.status_code == expected_status
    assert response.json()["code"] == expected_code
    assert publication_state(page) == before


def test_scheduled_publication_is_not_blocked(publication_page, admin_user):
    page, _ = publication_page
    draft = page.get_latest_revision_as_object()
    draft.go_live_at = timezone.now() + timedelta(days=1)
    revision = draft.save_revision()
    revision.publish(user=admin_user)
    revision.refresh_from_db()
    revision.approved_go_live_at = timezone.now() - timedelta(seconds=1)
    revision.content["go_live_at"] = revision.approved_go_live_at.isoformat()
    revision.save()

    call_command("publish_scheduled")

    page.refresh_from_db()
    assert page.live
    assert page.live_revision_id == revision.pk


def test_global_mode_does_not_lock_unlocked_pages(publication_page, api_client, admin_user, settings):
    _, url = publication_page
    settings.WAGTAILADMIN_GLOBAL_EDIT_LOCK = True
    api_client.force_authenticate(user=admin_user)
    assert api_client.post(url).status_code == 200


def test_disabled_workflows_follow_wagtail_policy(
    publication_page, approval_workflow, api_client, admin_user, settings
):
    page, url = publication_page
    workflow, _ = approval_workflow
    state = workflow.start(page, admin_user)
    settings.WAGTAIL_WORKFLOW_ENABLED = False
    api_client.force_authenticate(user=admin_user)
    response = api_client.post(url)
    assert response.status_code == 200, response.content
    state.refresh_from_db()
    assert state.status == "in_progress"


@pytest.mark.parametrize("scheduled", [False, True])
def test_publication_lock_error_precedence(publication_page, approval_workflow, api_client, admin_user, scheduled):
    page, url = publication_page
    workflow, _ = approval_workflow
    workflow.start(page, admin_user)
    page.locked = True
    page.locked_by = UserFactory()
    page.save(update_fields=["locked", "locked_by"])
    if scheduled:
        page.revisions.update(approved_go_live_at=timezone.now() + timedelta(days=1))
    before = publication_state(page)
    api_client.force_authenticate(user=admin_user)
    response = api_client.post(url)
    assert response.status_code == 409
    assert response.json()["code"] == ("page_locked" if scheduled else "workflow_active")
    assert publication_state(page) == before


def test_rejected_publication_preserves_live_media_and_draft(publication_page, api_client, admin_user, image, audio):
    page, url = publication_page
    page.get_latest_revision().publish(user=admin_user)
    page.refresh_from_db()
    # Retained live associations must not be replaced by the new draft body.
    page.images.add(image)
    page.audios.add(audio)
    draft = page.get_latest_revision_as_object()
    draft.title = "Unpublished change"
    draft.body = []
    draft.save_revision(user=admin_user)
    page.refresh_from_db()
    page.locked = True
    page.locked_by = UserFactory()
    page.save(update_fields=["locked", "locked_by"])
    before = publication_state(page)
    api_client.force_authenticate(user=admin_user)
    response = api_client.post(url)
    assert response.status_code == 409
    assert publication_state(page) == before


@pytest.mark.parametrize("endpoint", ["post", "episode"])
@pytest.mark.parametrize("guard", ["lock", "workflow", "schedule"])
def test_publication_guards_precede_episode_audio_validation(
    podcast, api_client, admin_user, approval_workflow, endpoint, guard
):
    page = EpisodeFactory(parent=podcast, title="Missing audio", slug="missing-audio", live=False, podcast_audio=None)
    revision = page.save_revision(user=admin_user)
    if guard == "lock":
        page.locked = True
        page.locked_by = UserFactory()
        page.save(update_fields=["locked", "locked_by"])
    elif guard == "workflow":
        approval_workflow[0].start(page, admin_user)
    else:
        revision.approved_go_live_at = timezone.now() + timedelta(days=1)
        revision.save()
    before = publication_state(page)
    api_client.force_authenticate(user=admin_user)
    response = api_client.post(reverse(f"cast:api:editor_{endpoint}_publish", kwargs={"pk": page.pk}))
    assert response.status_code == 409
    assert response.json()["code"] == ("workflow_active" if guard == "workflow" else "page_locked")
    assert publication_state(page) == before


@pytest.mark.django_db(transaction=True)
@pytest.mark.skipif(connection.vendor != "postgresql", reason="PostgreSQL row-lock semantics")
@pytest.mark.parametrize("concurrent_action", ["schedule", "workflow", "lock"])
def test_postgres_publish_serializes_editorial_changes(
    pg_editor_actors, approval_workflow, monkeypatch, concurrent_action
):
    admin_user, blog = pg_editor_actors
    page = PostFactory(parent=blog, title="Concurrent publication", slug="concurrent-publication", live=False)
    revision = page.save_revision(user=admin_user)
    workflow, _ = approval_workflow
    url = reverse("cast:api:editor_post_publish", kwargs={"pk": page.pk})
    revisions_locked = threading.Event()
    release_publish = threading.Event()
    change_started = threading.Event()
    change_finished = threading.Event()
    errors = []
    responses = []
    writer_pids = []
    original_check = PostEditorMixin._has_approved_schedule

    def pause_after_locks(post, *, for_update=False):
        scheduled = original_check(post, for_update=for_update)
        if for_update:
            revisions_locked.set()
            assert release_publish.wait(timeout=10)
        return scheduled

    monkeypatch.setattr(PostEditorMixin, "_has_approved_schedule", staticmethod(pause_after_locks))

    def publish():
        close_old_connections()
        try:
            client = APIClient()
            client.force_authenticate(user=type(admin_user).objects.get(pk=admin_user.pk))
            responses.append(client.post(url))
        except Exception as exc:  # pragma: no cover - surfaced below
            errors.append(exc)
        finally:
            close_old_connections()

    def change_editorial_state():
        close_old_connections()
        try:
            with transaction.atomic():
                # Bound a failed serialization test instead of leaving a blocked worker.
                with connection.cursor() as cursor:
                    cursor.execute("SET LOCAL lock_timeout = '15s'")
                    cursor.execute("SELECT pg_backend_pid()")
                    writer_pids.append(cursor.fetchone()[0])
                change_started.set()
                if concurrent_action == "schedule":
                    Revision.objects.filter(pk=revision.pk).update(
                        approved_go_live_at=timezone.now() + timedelta(days=1)
                    )
                elif concurrent_action == "workflow":
                    workflow.start(type(page).objects.get(pk=page.pk), admin_user)
                else:
                    type(page).objects.filter(pk=page.pk).update(locked=True, locked_by=admin_user)
            change_finished.set()
        except Exception as exc:  # pragma: no cover - surfaced below
            errors.append(exc)
        finally:
            close_old_connections()

    publish_thread = threading.Thread(target=publish)
    change_thread = threading.Thread(target=change_editorial_state)
    publish_thread.start()
    try:
        assert revisions_locked.wait(timeout=10)
        change_thread.start()
        assert change_started.wait(timeout=10)
        deadline = time.monotonic() + 4
        with connection.cursor() as cursor:
            while time.monotonic() < deadline:
                cursor.execute("SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s", [writer_pids[0]])
                row = cursor.fetchone()
                if row and row[0] == "Lock":
                    break
                assert not change_finished.is_set(), "Competing writer committed before publication released its locks"
                time.sleep(0.02)
            else:
                pytest.fail("Competing writer never waited on a PostgreSQL lock")
        assert not change_finished.is_set()
    finally:
        release_publish.set()
        publish_thread.join(timeout=20)
        if change_thread.ident is not None:
            change_thread.join(timeout=20)
    assert not publish_thread.is_alive() and not change_thread.is_alive()
    assert errors == []
    assert responses[0].status_code == 200, responses[0].content
    assert change_finished.is_set()
    page.refresh_from_db()
    assert page.live
    if concurrent_action == "schedule":
        assert page.revisions.get(pk=revision.pk).approved_go_live_at is not None
    elif concurrent_action == "workflow":
        assert page.current_workflow_state.status == "in_progress"
        assert not PageLogEntry.objects.filter(page_id=page.pk, action="wagtail.workflow.cancel").exists()
    else:
        assert page.locked
