"""Tests for private contributor voice references (diarization known-speaker slice 1).

Voice references are private, admin-only editorial data. They must never appear
in public contributor APIs, feeds, theme context, or repository serialization.
"""

from pathlib import Path

import pytest
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage, InMemoryStorage, default_storage
from django.test import override_settings

from cast.devdata import create_transcript
from cast.models import Contributor
from cast.models.contributors import (
    ContributorVoiceReference,
    get_voice_reference_storage,
)


def make_clip(name: str = "voice.wav") -> ContentFile:
    clip = ContentFile(b"RIFF....WAVEfmt ", name=name)
    return clip


@pytest.mark.django_db
class TestVoiceReferenceValidation:
    def test_clip_reference_is_valid(self):
        contributor = Contributor.objects.create(display_name="Johannes", slug="johannes")
        reference = ContributorVoiceReference(contributor=contributor, clip=make_clip())
        reference.full_clean()  # should not raise

    def test_source_range_reference_is_valid(self, audio):
        contributor = Contributor.objects.create(display_name="Johannes", slug="johannes")
        reference = ContributorVoiceReference(
            contributor=contributor,
            source_audio=audio,
            start_seconds="2296.000",
            end_seconds="2312.000",
        )
        reference.full_clean()  # should not raise

    def test_clip_and_range_together_is_rejected(self, audio):
        contributor = Contributor.objects.create(display_name="Johannes", slug="johannes")
        reference = ContributorVoiceReference(
            contributor=contributor,
            clip=make_clip(),
            source_audio=audio,
            start_seconds="1.0",
            end_seconds="2.0",
        )
        with pytest.raises(ValidationError):
            reference.full_clean()

    def test_neither_clip_nor_range_is_rejected(self):
        contributor = Contributor.objects.create(display_name="Johannes", slug="johannes")
        reference = ContributorVoiceReference(contributor=contributor)
        with pytest.raises(ValidationError):
            reference.full_clean()

    def test_range_without_source_audio_is_rejected(self):
        contributor = Contributor.objects.create(display_name="Johannes", slug="johannes")
        reference = ContributorVoiceReference(
            contributor=contributor,
            start_seconds="1.0",
            end_seconds="2.0",
        )
        with pytest.raises(ValidationError):
            reference.full_clean()

    def test_range_missing_one_bound_is_rejected(self, audio):
        contributor = Contributor.objects.create(display_name="Johannes", slug="johannes")
        reference = ContributorVoiceReference(
            contributor=contributor,
            source_audio=audio,
            start_seconds="1.0",
        )
        with pytest.raises(ValidationError):
            reference.full_clean()

    def test_range_start_must_be_before_end(self, audio):
        contributor = Contributor.objects.create(display_name="Johannes", slug="johannes")
        reference = ContributorVoiceReference(
            contributor=contributor,
            source_audio=audio,
            start_seconds="5.0",
            end_seconds="5.0",
        )
        with pytest.raises(ValidationError):
            reference.full_clean()

    def test_approving_requires_confirmed_consent(self):
        contributor = Contributor.objects.create(display_name="Johannes", slug="johannes")
        reference = ContributorVoiceReference(
            contributor=contributor,
            clip=make_clip(),
            status=ContributorVoiceReference.Status.APPROVED,
            consent_confirmed=False,
        )
        with pytest.raises(ValidationError):
            reference.full_clean()

    def test_approved_with_consent_is_valid(self):
        contributor = Contributor.objects.create(display_name="Johannes", slug="johannes")
        reference = ContributorVoiceReference(
            contributor=contributor,
            clip=make_clip(),
            status=ContributorVoiceReference.Status.APPROVED,
            consent_confirmed=True,
        )
        reference.full_clean()  # should not raise


@pytest.mark.django_db
class TestVoiceReferenceBehavior:
    def test_default_status_is_pending_and_not_usable(self):
        contributor = Contributor.objects.create(display_name="Johannes", slug="johannes")
        reference = ContributorVoiceReference(contributor=contributor, clip=make_clip())
        assert reference.status == ContributorVoiceReference.Status.PENDING
        assert reference.is_usable_for_voxhelm is False

    def test_approved_reference_is_usable(self):
        contributor = Contributor.objects.create(display_name="Johannes", slug="johannes")
        reference = ContributorVoiceReference(
            contributor=contributor,
            clip=make_clip(),
            status=ContributorVoiceReference.Status.APPROVED,
            consent_confirmed=True,
        )
        assert reference.is_usable_for_voxhelm is True

    def test_is_source_range_reflects_bounds(self, audio):
        contributor = Contributor.objects.create(display_name="Johannes", slug="johannes")
        clip_ref = ContributorVoiceReference(contributor=contributor, clip=make_clip())
        range_ref = ContributorVoiceReference(
            contributor=contributor, source_audio=audio, start_seconds="1.0", end_seconds="2.0"
        )
        assert clip_ref.is_source_range is False
        assert range_ref.is_source_range is True

    def test_str_includes_contributor_and_status(self):
        contributor = Contributor.objects.create(display_name="Johannes", slug="johannes")
        reference = ContributorVoiceReference(contributor=contributor, clip=make_clip(), title="Solo intro")
        assert "Johannes" in str(reference)
        assert "Solo intro" in str(reference)

    def test_hiding_contributor_keeps_references(self):
        contributor = Contributor.objects.create(display_name="Johannes", slug="johannes")
        reference = ContributorVoiceReference.objects.create(contributor=contributor, clip=make_clip())
        contributor.visible = False
        contributor.save()
        assert ContributorVoiceReference.objects.filter(pk=reference.pk).exists()


@pytest.mark.django_db
class TestVoiceReferenceQuerySet:
    def _approved(self, contributor):
        return ContributorVoiceReference.objects.create(
            contributor=contributor,
            clip=make_clip(),
            status=ContributorVoiceReference.Status.APPROVED,
            consent_confirmed=True,
        )

    def test_approved_excludes_other_statuses(self):
        contributor = Contributor.objects.create(display_name="Johannes", slug="johannes")
        approved = self._approved(contributor)
        ContributorVoiceReference.objects.create(contributor=contributor, clip=make_clip())  # pending
        assert list(ContributorVoiceReference.objects.approved()) == [approved]

    def test_usable_known_speaker_excludes_hidden_contributor_by_default(self):
        hidden = Contributor.objects.create(display_name="Hidden", slug="hidden", visible=False)
        self._approved(hidden)
        assert list(ContributorVoiceReference.objects.usable_known_speaker()) == []

    def test_usable_known_speaker_includes_hidden_when_explicitly_allowed(self):
        hidden = Contributor.objects.create(display_name="Hidden", slug="hidden", visible=False)
        reference = ContributorVoiceReference.objects.create(
            contributor=hidden,
            clip=make_clip(),
            status=ContributorVoiceReference.Status.APPROVED,
            consent_confirmed=True,
            allow_for_hidden_contributor=True,
        )
        assert list(ContributorVoiceReference.objects.usable_known_speaker()) == [reference]

    def test_usable_known_speaker_includes_visible_contributor(self):
        visible = Contributor.objects.create(display_name="Johannes", slug="johannes")
        reference = self._approved(visible)
        assert list(ContributorVoiceReference.objects.usable_known_speaker()) == [reference]


@pytest.mark.django_db
class TestVoiceReferenceStorage:
    @override_settings(
        STORAGES={
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
        }
    )
    def test_falls_back_to_private_media_storage_when_unconfigured(self, settings, tmp_path):
        settings.CAST_PRIVATE_MEDIA_ROOT = str(tmp_path / "private")

        storage = get_voice_reference_storage()

        assert isinstance(storage, FileSystemStorage)
        assert storage is not default_storage
        assert storage.location == str(tmp_path / "private")
        with pytest.raises(ValueError, match="not accessible via a URL"):
            storage.url("cast_voice_references/voice.wav")

    @override_settings(
        STORAGES={
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
            "cast_voice_references": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
        }
    )
    def test_uses_configured_private_storage_alias(self):
        assert isinstance(get_voice_reference_storage(), InMemoryStorage)

    def test_voice_reference_clip_is_saved_to_private_storage(self, tmp_path, settings):
        settings.CAST_PRIVATE_MEDIA_ROOT = str(tmp_path / "private")
        contributor = Contributor.objects.create(display_name="Johannes", slug="johannes-storage")

        reference = ContributorVoiceReference.objects.create(contributor=contributor, clip=make_clip())

        private_root = Path(reference.clip.storage.location)
        assert Path(reference.clip.path).is_relative_to(private_root)
        assert not default_storage.exists(reference.clip.name)
        with pytest.raises(ValueError, match="not accessible via a URL"):
            reference.clip.url

    def test_transcript_speakers_sidecar_is_saved_to_private_storage(self, tmp_path, settings, audio):
        settings.CAST_PRIVATE_MEDIA_ROOT = str(tmp_path / "private")
        transcript = create_transcript(audio=audio)

        transcript.speakers.save("test.speakers.json", ContentFile(b'{"segments": []}'), save=True)

        private_root = Path(transcript.speakers.storage.location)
        assert Path(transcript.speakers.path).is_relative_to(private_root)
        assert not default_storage.exists(transcript.speakers.name)
        with pytest.raises(ValueError, match="not accessible via a URL"):
            transcript.speakers.url


@pytest.mark.django_db
class TestVoiceReferencePrivacy:
    """Voice references must never leak into public-facing serialized output."""

    def test_serialize_contributor_excludes_voice_references(self):
        from cast.models.repository.serialization import serialize_contributor

        contributor = Contributor.objects.create(display_name="Johannes", slug="johannes")
        ContributorVoiceReference.objects.create(contributor=contributor, clip=make_clip())
        data = serialize_contributor(contributor)
        serialized = repr(data).lower()
        assert "voice_reference" not in serialized
        assert "voice.wav" not in serialized
        assert "cast_voice_references" not in serialized

    def test_serialize_contributor_excludes_source_range_voice_references(self, audio):
        from cast.models.repository.serialization import serialize_contributor

        contributor = Contributor.objects.create(display_name="Johannes", slug="johannes-source")
        ContributorVoiceReference.objects.create(
            contributor=contributor,
            source_audio=audio,
            start_seconds="1.000",
            end_seconds="12.000",
        )

        serialized = repr(serialize_contributor(contributor)).lower()

        assert "voice_reference" not in serialized
        assert "source_audio" not in serialized
        assert "start_seconds" not in serialized
        assert "end_seconds" not in serialized


@pytest.mark.django_db
class TestVoiceReferenceAdmin:
    def test_contributor_edit_form_exposes_voice_reference_panel(self, admin_client):
        from django.urls import reverse

        contributor = Contributor.objects.create(display_name="Johannes", slug="johannes")
        url = reverse("wagtailsnippets_cast_contributor:edit", args=(contributor.pk,))
        response = admin_client.get(url)
        assert response.status_code == 200
        assert b"voice_references" in response.content

    def test_contributor_edit_form_renders_private_clip_without_storage_url(self, admin_client):
        from django.urls import reverse

        contributor = Contributor.objects.create(display_name="Private Clip", slug="private-clip")
        ContributorVoiceReference.objects.create(contributor=contributor, clip=make_clip())
        url = reverse("wagtailsnippets_cast_contributor:edit", args=(contributor.pk,))

        response = admin_client.get(url)

        assert response.status_code == 200
        assert b"cast_voice_references/voice" in response.content
