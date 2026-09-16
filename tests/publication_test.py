import pytest

from cast.models import Episode, Post
from cast.publication import (
    EPISODE_AUDIO_REQUIRED,
    PublicationRejected,
    PublicationViolation,
    check_publishable,
    episode_audio_violation,
    violations_for,
)


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
