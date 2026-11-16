from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.core.exceptions import ValidationError

from cast.models import Contributor
from cast.models.contributors import ContributorVoiceReference
from cast.voxhelm.service import build_known_speaker_reference_entry


@pytest.mark.django_db
@pytest.mark.parametrize("start,end", [("-1", "2"), ("0", "11"), ("NaN", "2"), ("0", "Infinity"), ("-Infinity", "2")])
def test_source_range_rejects_invalid_domain(audio, start, end):
    audio.duration = timedelta(seconds=10)
    contributor = Contributor.objects.create(display_name="Synthetic", slug="synthetic")
    reference = ContributorVoiceReference(
        contributor=contributor, source_audio=audio, start_seconds=Decimal(start), end_seconds=Decimal(end)
    )
    with pytest.raises(ValidationError):
        reference.clean()
    assert build_known_speaker_reference_entry(reference) is None


@pytest.mark.django_db
@pytest.mark.parametrize("duration", [None, timedelta(seconds=10)])
def test_source_range_accepts_exact_end(audio, duration, mocker):
    audio.duration = duration
    contributor = Contributor.objects.create(display_name="Synthetic", slug="synthetic")
    reference = ContributorVoiceReference(
        contributor=contributor, source_audio=audio, start_seconds=Decimal("0"), end_seconds=Decimal("10")
    )
    reference.full_clean()
    mocker.patch("cast.voxhelm.service.resolve_audio_source_url", return_value="https://example.com/audio")
    assert build_known_speaker_reference_entry(reference)["end"] == 10


def test_invalid_legacy_range_payload():
    for start, end in [("invalid", "2"), ("0", "1e999")]:
        reference = SimpleNamespace(
            is_source_range=True,
            source_audio_id=1,
            source_audio=SimpleNamespace(duration=None),
            start_seconds=start,
            end_seconds=end,
        )
        assert build_known_speaker_reference_entry(reference) is None


@pytest.mark.django_db
def test_invalid_legacy_range_is_omitted_from_episode_payload(audio):
    from cast.voxhelm.service import build_known_speaker_references

    contributor = Contributor.objects.create(display_name="Synthetic", slug="synthetic")
    reference = ContributorVoiceReference.objects.create(
        contributor=contributor,
        source_audio=audio,
        start_seconds=Decimal("0"),
        end_seconds=Decimal(".001"),
        status=ContributorVoiceReference.Status.APPROVED,
        consent_confirmed=True,
    )
    ContributorVoiceReference.objects.filter(pk=reference.pk).update(start_seconds=Decimal("-1"))
    episode = SimpleNamespace(
        contributor_assignments=[SimpleNamespace(contributor_id=contributor.pk, contributor=contributor)]
    )
    assert build_known_speaker_references(episode) == []
