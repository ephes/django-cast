from types import SimpleNamespace

import pytest
from wagtail.workflows import publish_workflow_state

from cast.models import Episode, Post
from cast.publication import (
    EPISODE_AUDIO_REQUIRED,
    PublicationRejected,
    PublicationViolation,
    _publish_revision_and_object,
    _validate_publish_revision_api,
    check_publishable,
    episode_audio_violation,
    install_publication_policy,
    violations_for,
)
from tests.factories import EpisodeFactory, HomePageFactory, PostFactory


def test_episode_audio_rule_accepts_an_audio_id():
    assert episode_audio_violation(42) is None


def test_episode_audio_rule_returns_structured_violation():
    assert episode_audio_violation(None) == PublicationViolation(
        field="podcast_audio",
        code="required",
        message=str(EPISODE_AUDIO_REQUIRED),
    )


def test_publication_rejected_preserves_django_validation_contract():
    violation = PublicationViolation("podcast_audio", "required", "Audio is required.")

    error = PublicationRejected((violation,))

    assert error.violations == (violation,)
    assert error.message_dict == {"podcast_audio": ["Audio is required."]}
    assert error.messages == ["Audio is required."]
    assert error.error_dict["podcast_audio"][0].code == "required"


def test_publication_rejected_adapts_to_editor_errors():
    error = PublicationRejected(
        (
            PublicationViolation("podcast_audio", "required", "Audio is required."),
            PublicationViolation("podcast_audio", "invalid", "Audio is invalid."),
        )
    )

    assert error.as_error_map() == {
        "podcast_audio": [
            {"code": "required", "message": "Audio is required."},
            {"code": "invalid", "message": "Audio is invalid."},
        ]
    }


def test_publication_rejected_adapts_to_form_errors():
    error = PublicationRejected(
        (
            PublicationViolation("podcast_audio", "required", "Audio is required."),
            PublicationViolation("non_field_errors", "invalid", "Page is invalid."),
        )
    )

    assert error.as_form_error().message_dict == {
        "podcast_audio": ["Audio is required."],
        "non_field_errors": ["Page is invalid."],
    }


def test_plain_post_has_no_publication_violations():
    assert violations_for(Post()) == []


def test_episode_without_audio_is_not_publishable():
    episode = Episode(podcast_audio_id=None)

    with pytest.raises(PublicationRejected) as error:
        check_publishable(episode)

    assert error.value.violations == (episode_audio_violation(None),)


def test_episode_with_audio_is_publishable():
    check_publishable(Episode(podcast_audio_id=42))


def test_publish_revision_and_object_accepts_positional_and_keyword_arguments():
    positional_revision = object()
    positional_page = object()
    positional_previous_revision = object()
    keyword_revision = object()
    keyword_page = object()
    keyword_previous_revision = object()

    assert _publish_revision_and_object(
        (positional_revision, positional_page, None, True, True, positional_previous_revision),
        {},
    ) == (
        positional_revision,
        positional_page,
        positional_previous_revision,
    )
    assert _publish_revision_and_object((positional_revision, positional_page), {}) == (
        positional_revision,
        positional_page,
        None,
    )
    assert _publish_revision_and_object(
        (),
        {"revision": keyword_revision, "object": keyword_page, "previous_revision": keyword_previous_revision},
    ) == (
        keyword_revision,
        keyword_page,
        keyword_previous_revision,
    )


def test_validate_publish_revision_api_accepts_expected_signature():
    def publish_revision(self, revision, object, user, changed, log_action, previous_revision=None):
        pass

    _validate_publish_revision_api(publish_revision)


def test_validate_publish_revision_api_rejects_missing_api():
    with pytest.raises(RuntimeError, match="not available"):
        _validate_publish_revision_api(None)


def test_validate_publish_revision_api_rejects_unsupported_signature():
    def publish_revision(self, revision, object):
        pass

    with pytest.raises(RuntimeError, match="missing previous_revision"):
        _validate_publish_revision_api(publish_revision)


def test_validate_publish_revision_api_rejects_unsupported_positional_order():
    def publish_revision(self, object, revision, user, changed, log_action, previous_revision=None):
        pass

    with pytest.raises(RuntimeError, match="positional parameter order"):
        _validate_publish_revision_api(publish_revision)


@pytest.mark.django_db
def test_install_publication_policy_is_idempotent():
    install_publication_policy()

    from wagtail.actions.publish_revision import PublishRevisionAction

    wrapped = PublishRevisionAction._publish_revision
    install_publication_policy()

    assert PublishRevisionAction._publish_revision is wrapped


@pytest.mark.django_db
def test_install_publication_policy_logs_and_skips_unsupported_api(mocker, caplog):
    from wagtail.actions.publish_revision import PublishRevisionAction

    caplog.set_level("WARNING", logger="cast.publication")
    mocker.patch.object(PublishRevisionAction, "_publish_revision", None)

    install_publication_policy()

    assert "Publication policy publish hook was not installed" in caplog.text


@pytest.mark.django_db
def test_revision_publish_rejects_episode_without_audio(podcast, body):
    episode = EpisodeFactory(
        owner=podcast.owner,
        parent=podcast,
        title="Audio-less episode",
        slug="audio-less-episode",
        live=False,
        first_published_at=None,
        podcast_audio=None,
        body=body,
    )
    revision = episode.save_revision()

    with pytest.raises(PublicationRejected):
        revision.publish()

    episode.refresh_from_db()
    assert episode.live is False


@pytest.mark.django_db
def test_revision_publish_validates_revision_content_instead_of_live_row(podcast, audio, body):
    episode = EpisodeFactory(
        owner=podcast.owner,
        parent=podcast,
        title="Published episode",
        slug="published-episode",
        live=False,
        first_published_at=None,
        podcast_audio=audio,
        body=body,
    )
    episode.save_revision().publish()
    episode.refresh_from_db()
    live_revision_id = episode.live_revision_id
    episode.podcast_audio = None
    audio_less_revision = episode.save_revision()

    with pytest.raises(PublicationRejected):
        audio_less_revision.publish()

    episode.refresh_from_db()
    assert episode.live is True
    assert episode.podcast_audio_id == audio.id
    assert episode.live_revision_id == live_revision_id


@pytest.mark.django_db
def test_revision_rejection_happens_before_episode_numbering(podcast, body):
    podcast.automatic_episode_numbering_enabled = True
    podcast.next_episode_number = 7
    podcast.save(update_fields=["automatic_episode_numbering_enabled", "next_episode_number"])
    episode = EpisodeFactory(
        owner=podcast.owner,
        parent=podcast,
        title="Unnumbered episode",
        slug="unnumbered-episode",
        live=False,
        first_published_at=None,
        podcast_audio=None,
        episode_number=None,
        body=body,
    )
    revision = episode.save_revision()

    with pytest.raises(PublicationRejected):
        revision.publish()

    episode.refresh_from_db()
    podcast.refresh_from_db()
    revision.refresh_from_db()
    assert episode.episode_number is None
    assert podcast.next_episode_number == 7
    assert revision.content["episode_number"] is None


@pytest.mark.django_db
def test_workflow_publish_rejects_episode_without_audio(podcast, body):
    episode = EpisodeFactory(
        owner=podcast.owner,
        parent=podcast,
        title="Workflow episode",
        slug="workflow-episode",
        live=False,
        first_published_at=None,
        podcast_audio=None,
        body=body,
    )
    episode.save_revision()
    workflow_state = SimpleNamespace(content_object=episode)

    with pytest.raises(PublicationRejected):
        publish_workflow_state(workflow_state)

    episode.refresh_from_db()
    assert episode.live is False


@pytest.mark.django_db
def test_publish_hook_allows_post_without_consuming_episode_number(podcast, body):
    podcast.automatic_episode_numbering_enabled = True
    podcast.next_episode_number = 7
    podcast.save(update_fields=["automatic_episode_numbering_enabled", "next_episode_number"])
    post = PostFactory(
        owner=podcast.owner,
        parent=podcast,
        title="Draft post",
        slug="draft-post",
        live=False,
        body=body,
    )

    post.save_revision().publish()

    post.refresh_from_db()
    podcast.refresh_from_db()
    assert post.live is True
    assert podcast.next_episode_number == 7


@pytest.mark.django_db
def test_publish_hook_allows_non_cast_page(site):
    page = HomePageFactory(parent=site.root_page, title="Draft home", slug="draft-home", live=False)

    page.save_revision().publish()

    page.refresh_from_db()
    assert page.live is True
