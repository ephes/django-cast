import pytest
from django.utils.deprecation import RemovedInDjango60Warning

from cast.api.serializers import AudioSerializer, VideoSerializer
from cast.media_derivation import (
    save_audio_with_derivations,
    save_transcript_with_derivations,
    save_video_with_derivations,
    should_sync_transcript_speaker_mappings,
)
from cast.models import Transcript


@pytest.mark.django_db()
def test_plain_audio_save_skips_derivation(audio, mocker):
    create_duration = mocker.patch.object(audio, "create_duration")
    size_to_metadata = mocker.patch.object(audio, "size_to_metadata")

    audio.save()

    create_duration.assert_not_called()
    size_to_metadata.assert_not_called()


@pytest.mark.django_db()
def test_audio_save_compatibility_flags_are_explicit_opt_in(audio, mocker):
    save_with_derivations = mocker.patch("cast.media_derivation.save_audio_with_derivations")

    audio.save(duration=True, cache_file_sizes=True)

    save_with_derivations.assert_called_once_with(
        audio,
        generate_duration=True,
        cache_file_sizes=True,
    )


@pytest.mark.django_db()
@pytest.mark.parametrize(
    ("save_kwargs", "expected_duration", "expected_cache"),
    [
        ({"duration": False}, False, True),
        ({"cache_file_sizes": False}, True, False),
        ({"duration": None}, False, True),
        ({"cache_file_sizes": None}, True, False),
    ],
)
def test_audio_single_compatibility_flags_preserve_legacy_defaults(
    audio,
    mocker,
    save_kwargs,
    expected_duration,
    expected_cache,
):
    save_with_derivations = mocker.patch("cast.media_derivation.save_audio_with_derivations")

    audio.save(**save_kwargs)

    save_with_derivations.assert_called_once_with(
        audio,
        generate_duration=expected_duration,
        cache_file_sizes=expected_cache,
    )


@pytest.mark.django_db()
def test_audio_explicit_none_for_both_compatibility_flags_disables_derivation(audio, mocker):
    save_with_derivations = mocker.patch("cast.media_derivation.save_audio_with_derivations")

    audio.save(duration=None, cache_file_sizes=None)

    save_with_derivations.assert_not_called()


@pytest.mark.django_db()
def test_audio_derivation_service_can_persist_without_enrichment(audio, mocker):
    create_duration = mocker.patch.object(audio, "create_duration")
    size_to_metadata = mocker.patch.object(audio, "size_to_metadata")

    save_audio_with_derivations(audio, generate_duration=False, cache_file_sizes=False)

    create_duration.assert_not_called()
    size_to_metadata.assert_not_called()


@pytest.mark.django_db()
def test_plain_video_save_skips_derivation(video, mocker):
    create_poster = mocker.patch.object(video, "create_poster")

    video.save()

    create_poster.assert_not_called()


@pytest.mark.django_db()
def test_video_save_compatibility_flag_is_explicit_opt_in(video, mocker):
    save_with_derivations = mocker.patch("cast.media_derivation.save_video_with_derivations")

    video.save(poster=True)

    save_with_derivations.assert_called_once_with(video, generate_poster=True)


@pytest.mark.django_db()
def test_video_derivation_service_can_persist_without_poster(video, mocker):
    create_poster = mocker.patch.object(video, "create_poster")

    save_video_with_derivations(video, generate_poster=False)

    create_poster.assert_not_called()


@pytest.mark.django_db()
def test_video_derivation_service_skips_follow_up_save_without_new_poster(video, mocker):
    create_poster = mocker.patch.object(video, "create_poster")

    save_video_with_derivations(video)

    create_poster.assert_called_once_with()


@pytest.mark.django_db()
def test_derivation_services_normalize_positional_save_arguments(audio, video, mocker):
    audio_save = mocker.patch.object(audio, "save")
    video_save = mocker.patch.object(video, "save")
    atomic = mocker.patch("cast.media_derivation.transaction.atomic")

    with pytest.warns(RemovedInDjango60Warning):
        save_audio_with_derivations(
            audio,
            False,
            False,
            "archive",
            None,
            generate_duration=False,
            cache_file_sizes=False,
        )
    with pytest.warns(RemovedInDjango60Warning):
        save_video_with_derivations(video, False, False, "archive", None, generate_poster=False)

    assert atomic.call_args_list[0].kwargs == {"using": "archive"}
    assert atomic.call_args_list[1].kwargs == {"using": "archive"}
    audio_save.assert_called_once_with(
        duration=False,
        cache_file_sizes=False,
        force_insert=False,
        force_update=False,
        using="archive",
        update_fields=None,
    )
    video_save.assert_called_once_with(
        poster=False,
        force_insert=False,
        force_update=False,
        using="archive",
        update_fields=None,
    )


@pytest.mark.django_db()
def test_plain_transcript_save_skips_speaker_mapping_sync(audio, mocker):
    transcript = Transcript(audio=audio)
    sync_speaker_mappings = mocker.patch.object(transcript, "sync_speaker_mappings")

    transcript.save()

    sync_speaker_mappings.assert_not_called()


@pytest.mark.django_db()
def test_transcript_save_compatibility_flag_is_explicit_opt_in(audio, mocker):
    transcript = Transcript(audio=audio)
    save_with_derivations = mocker.patch("cast.media_derivation.save_transcript_with_derivations")

    transcript.save(sync_speaker_mappings=True)

    save_with_derivations.assert_called_once_with(transcript)


@pytest.mark.django_db()
def test_transcript_derivation_service_skips_sync_for_unrelated_update(mocker):
    transcript = Transcript()
    save = mocker.patch.object(transcript, "save")
    sync_speaker_mappings = mocker.patch.object(transcript, "sync_speaker_mappings")

    save_transcript_with_derivations(transcript, update_fields=["speakers"])

    save.assert_called_once_with(update_fields=["speakers"], sync_speaker_mappings=False, using="default")
    sync_speaker_mappings.assert_not_called()


@pytest.mark.django_db()
def test_transcript_derivation_service_normalizes_positional_update_fields(audio, mocker):
    transcript = Transcript(audio=audio)
    save = mocker.patch.object(transcript, "save")
    sync_speaker_mappings = mocker.patch.object(transcript, "sync_speaker_mappings")
    atomic = mocker.patch("cast.media_derivation.transaction.atomic")

    with pytest.warns(RemovedInDjango60Warning):
        save_transcript_with_derivations(transcript, False, False, "archive", ["speakers"])

    atomic.assert_called_once_with(using="archive")
    save.assert_called_once_with(
        sync_speaker_mappings=False,
        force_insert=False,
        force_update=False,
        using="archive",
        update_fields=["speakers"],
    )
    sync_speaker_mappings.assert_not_called()


@pytest.mark.django_db()
def test_transcript_derivation_service_rolls_back_persistence_when_sync_fails(audio, mocker):
    transcript = Transcript(audio=audio)
    mocker.patch.object(transcript, "sync_speaker_mappings", side_effect=RuntimeError("mapping sync failed"))

    with pytest.raises(RuntimeError, match="mapping sync failed"):
        save_transcript_with_derivations(transcript)

    assert not Transcript.objects.filter(audio=audio).exists()


@pytest.mark.parametrize(
    ("update_fields", "expected"),
    [
        (None, True),
        (["podlove"], True),
        (["audio"], True),
        (["speakers"], False),
        ([], False),
    ],
)
def test_should_sync_transcript_speaker_mappings(update_fields, expected):
    assert should_sync_transcript_speaker_mappings(update_fields) is expected
    assert Transcript._should_sync_speaker_mappings(update_fields) is expected


@pytest.mark.django_db()
def test_legacy_media_serializers_use_derivation_services(user, mocker):
    save_audio = mocker.patch("cast.api.serializers.save_audio_with_derivations")
    save_video = mocker.patch("cast.api.serializers.save_video_with_derivations")

    audio = AudioSerializer().create({"user": user, "mp3": "audio.mp3"})
    video = VideoSerializer().create({"user": user, "original": "video.mp4"})

    save_audio.assert_called_once_with(audio)
    save_video.assert_called_once_with(video)
