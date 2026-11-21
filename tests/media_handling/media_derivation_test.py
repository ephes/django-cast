import warnings

import pytest
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from wagtail.models import Collection

from cast.api.serializers import AudioSerializer, VideoSerializer
from cast.media_derivation import (
    save_audio_with_derivations,
    save_transcript_with_derivations,
    save_video_with_derivations,
    should_sync_transcript_speaker_mappings,
)
from cast.models import Audio, Transcript


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
    mocker.patch("cast.media_derivation.DJANGO_VERSION", (5, 2))

    with pytest.warns(DeprecationWarning) as caught_warnings:
        save_audio_with_derivations(
            audio,
            False,
            False,
            "archive",
            None,
            generate_duration=False,
            cache_file_sizes=False,
        )
    assert caught_warnings[0].filename == __file__
    with pytest.warns(DeprecationWarning):
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


def test_derivation_services_accept_positional_save_arguments_before_django_51(audio, mocker):
    audio_save = mocker.patch.object(audio, "save")
    mocker.patch("cast.media_derivation.transaction.atomic")
    mocker.patch("cast.media_derivation.DJANGO_VERSION", (5, 0))

    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        save_audio_with_derivations(
            audio,
            False,
            False,
            "archive",
            None,
            generate_duration=False,
            cache_file_sizes=False,
        )

    audio_save.assert_called_once_with(
        duration=False,
        cache_file_sizes=False,
        force_insert=False,
        force_update=False,
        using="archive",
        update_fields=None,
    )


def test_derivation_services_preserve_default_keyword_duplicates_on_django_51_and_52(audio, mocker):
    audio_save = mocker.patch.object(audio, "save")
    mocker.patch("cast.media_derivation.transaction.atomic")
    mocker.patch("cast.media_derivation.DJANGO_VERSION", (5, 2))

    with pytest.warns(DeprecationWarning):
        save_audio_with_derivations(
            audio,
            True,
            True,
            "archive",
            ["duration"],
            force_insert=False,
            force_update=False,
            using=None,
            update_fields=None,
            generate_duration=False,
            cache_file_sizes=False,
        )

    audio_save.assert_called_once_with(
        duration=False,
        cache_file_sizes=False,
        force_insert=True,
        force_update=True,
        using="archive",
        update_fields=("duration",),
    )


def test_derivation_services_reject_non_default_keyword_duplicates_on_django_51_and_52(audio, mocker):
    mocker.patch("cast.media_derivation.DJANGO_VERSION", (5, 2))

    with pytest.warns(DeprecationWarning):
        with pytest.raises(TypeError, match="got multiple values for argument 'force_insert'"):
            save_audio_with_derivations(
                audio,
                False,
                force_insert=True,
                generate_duration=False,
                cache_file_sizes=False,
            )


@pytest.mark.parametrize(
    ("args", "kwargs", "message"),
    [
        ((False, False, "default", None, "extra"), {}, "takes from 1 to 5 positional arguments"),
        ((False,), {"force_insert": True}, "got multiple values for argument 'force_insert'"),
    ],
)
def test_derivation_services_reject_invalid_legacy_positional_save_arguments(
    audio,
    mocker,
    args,
    kwargs,
    message,
):
    mocker.patch("cast.media_derivation.DJANGO_VERSION", (5, 0))

    with pytest.raises(TypeError, match=message):
        save_audio_with_derivations(
            audio,
            *args,
            generate_duration=False,
            cache_file_sizes=False,
            **kwargs,
        )


def test_derivation_services_reject_positional_save_arguments_on_django_6(audio, mocker):
    mocker.patch("cast.media_derivation.DJANGO_VERSION", (6, 0))

    with pytest.raises(TypeError, match="takes 1 positional argument but 2 were given"):
        save_audio_with_derivations(
            audio,
            False,
            generate_duration=False,
            cache_file_sizes=False,
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

    save_with_derivations.assert_called_once_with(transcript, preserve_source_fingerprint=False)


@pytest.mark.django_db()
def test_transcript_derivation_service_skips_sync_for_unrelated_update(mocker):
    transcript = Transcript()
    save = mocker.patch.object(transcript, "save")
    sync_speaker_mappings = mocker.patch.object(transcript, "sync_speaker_mappings")

    save_transcript_with_derivations(transcript, update_fields=["speakers"])

    save.assert_called_once_with(
        update_fields=("speakers",),
        sync_speaker_mappings=False,
        preserve_source_fingerprint=False,
        using="default",
    )
    sync_speaker_mappings.assert_not_called()


@pytest.mark.django_db()
def test_transcript_derivation_service_normalizes_positional_update_fields(audio, mocker):
    transcript = Transcript(audio=audio)
    save = mocker.patch.object(transcript, "save")
    sync_speaker_mappings = mocker.patch.object(transcript, "sync_speaker_mappings")
    atomic = mocker.patch("cast.media_derivation.transaction.atomic")
    mocker.patch("cast.media_derivation.DJANGO_VERSION", (5, 2))

    with pytest.warns(DeprecationWarning):
        save_transcript_with_derivations(transcript, False, False, "archive", ["speakers"])

    atomic.assert_called_once_with(using="archive")
    save.assert_called_once_with(
        sync_speaker_mappings=False,
        preserve_source_fingerprint=False,
        force_insert=False,
        force_update=False,
        using="archive",
        update_fields=("speakers",),
    )
    sync_speaker_mappings.assert_not_called()


@pytest.mark.django_db()
def test_transcript_derivation_service_rolls_back_persistence_when_sync_fails(audio, mocker):
    transcript = Transcript(audio=audio)
    mocker.patch.object(transcript, "sync_speaker_mappings", side_effect=RuntimeError("mapping sync failed"))

    with pytest.raises(RuntimeError, match="mapping sync failed"):
        save_transcript_with_derivations(transcript)

    assert not Transcript.objects.filter(audio=audio).exists()


@pytest.mark.django_db(databases={"default", "migration_other"})
def test_transcript_derivation_uses_explicit_alias_for_mapping_reads_and_writes(settings):
    class DefaultRouter:
        def db_for_read(self, model, **hints):
            return "default"

        def db_for_write(self, model, **hints):
            return "default"

    alias = "migration_other"
    collection_ids = {}
    for database in ("default", alias):
        user = get_user_model().objects.using(database).create(username="synthetic-speaker-editor")
        collection, _ = Collection.objects.using(database).get_or_create(
            path="0001", defaults={"depth": 1, "numchild": 0, "name": "Synthetic"}
        )
        collection_ids[database] = collection.pk
        Audio.objects.using(database).create(
            pk=101, user_id=user.pk, collection_id=collection.pk, title="Synthetic audio"
        )
    Transcript.objects.using("default").create(pk=101, audio_id=101, collection_id=collection_ids["default"])
    transcript = Transcript(pk=101, audio_id=101, collection_id=collection_ids[alias])
    settings.DATABASE_ROUTERS = [DefaultRouter()]
    transcript.podlove.save(
        "synthetic-speakers.json",
        ContentFile(b'{"transcripts": [{"speaker": "Speaker 1"}]}'),
        save=False,
    )
    save_transcript_with_derivations(transcript, using=alias)

    mapping_model = transcript.speaker_mappings.model
    mapping = mapping_model.objects.using(alias).get(transcript_id=101, speaker_label="Speaker 1")
    assert mapping.active
    assert mapping.source_artifact_fingerprint == transcript.source_fingerprint
    assert not mapping_model.objects.using("default").exists()

    transcript.podlove.save(
        "synthetic-replacement.json",
        ContentFile(b'{"transcripts": [{"speaker": "Speaker 2"}]}'),
        save=False,
    )
    save_transcript_with_derivations(transcript, using=alias, update_fields=["podlove"])

    mapping.refresh_from_db(using=alias)
    assert not mapping.active
    assert mapping_model.objects.using(alias).get(transcript_id=101, speaker_label="Speaker 2").active
    assert not mapping_model.objects.using("default").exists()


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


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["audio", "video"])
@pytest.mark.parametrize("direct", [True, False])
@pytest.mark.parametrize("empty", [list, lambda: iter(())])
def test_empty_partial_media_save_is_complete_noop(audio, video, mocker, kind, direct, empty):
    obj = audio if kind == "audio" else video
    obj.title = "Must not persist"
    probes = [
        mocker.patch.object(obj, name)
        for name in (("create_duration", "size_to_metadata") if kind == "audio" else ("create_poster",))
    ]
    save = mocker.spy(obj, "save")
    validate = mocker.patch(f"cast.media_derivation.validate_{kind}_upload")
    if direct:
        helper = save_audio_with_derivations if kind == "audio" else save_video_with_derivations
        helper(obj, update_fields=empty())
        save.assert_not_called()
    else:
        options = {"duration": True, "cache_file_sizes": True} if kind == "audio" else {"poster": True}
        obj.save(update_fields=empty(), **options)
        assert save.call_count == 1
    for probe in probes:
        probe.assert_not_called()
    validate.assert_not_called()
    obj.refresh_from_db()
    assert obj.title != "Must not persist"


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["audio", "video"])
def test_title_only_save_excludes_unsaved_media_and_derivations(audio, video, mocker, kind):
    from django.core.files.uploadedfile import SimpleUploadedFile

    obj = audio if kind == "audio" else video
    source = "mp3" if kind == "audio" else "original"
    setattr(obj, source, f"persisted-source.{source}")
    obj.save()
    previous = getattr(obj, source).name
    setattr(obj, source, SimpleUploadedFile("excluded.bin", b"synthetic excluded upload"))
    obj.title = "Title only"
    validate = mocker.patch(f"cast.media_derivation.validate_{kind}_upload")
    if kind == "video":
        poster = obj.poster.name or ""

        def make_poster():
            obj.poster.name = "wrong-source-poster.jpg"

        derive = mocker.patch.object(obj, "create_poster", side_effect=make_poster)
        save_video_with_derivations(obj, update_fields=iter(["title"]))
    else:
        derive = mocker.patch.object(obj, "create_duration")
        sizes = mocker.patch.object(obj, "size_to_metadata")
        save_audio_with_derivations(obj, update_fields=iter(["title"]))
        sizes.assert_not_called()
    derive.assert_not_called()
    validate.assert_not_called()
    assert not getattr(obj, source)._committed
    obj.refresh_from_db()
    assert obj.title == "Title only"
    assert getattr(obj, source).name == previous
    if kind == "video":
        assert (obj.poster.name or "") == poster


@pytest.mark.django_db(databases={"default", "migration_other"})
@pytest.mark.parametrize("kind", ["audio", "video"])
@pytest.mark.parametrize("explicit", [False, True])
def test_derivations_follow_write_router_for_replica_instances(audio, video, settings, mocker, kind, explicit):
    from datetime import timedelta

    from django.contrib.auth import get_user_model
    from wagtail.models import Collection

    from cast.models import Audio, Video

    alias = "migration_other"
    original = audio if kind == "audio" else video
    model = Audio if kind == "audio" else Video
    get_user_model().objects.using(alias).create(pk=original.user_id, username="synthetic-replica")
    Collection.objects.using(alias).create(
        pk=original.collection_id, path="0001", depth=1, numchild=0, name="Synthetic"
    )
    model.objects.using(alias).create(
        pk=original.pk, user_id=original.user_id, collection_id=original.collection_id, title="Replica"
    )
    loaded = model.objects.using(alias).get(pk=original.pk)
    loaded.title = "Routed write"

    class WriteRouter:
        def db_for_write(self, model, **hints):
            return "default"

    settings.DATABASE_ROUTERS = [WriteRouter()]
    spy = mocker.spy(loaded, "save")
    if kind == "audio":
        mocker.patch.object(
            loaded, "create_duration", side_effect=lambda: setattr(loaded, "duration", timedelta(seconds=4))
        )
        mocker.patch.object(loaded, "size_to_metadata")
        save_audio_with_derivations(loaded, **({"using": alias} if explicit else {}))
    else:
        mocker.patch.object(loaded, "create_poster", side_effect=lambda: setattr(loaded.poster, "name", "derived.jpg"))
        save_video_with_derivations(loaded, **({"using": alias} if explicit else {}))
    destination = alias if explicit else "default"
    assert [call.kwargs["using"] for call in spy.call_args_list] == [destination, destination]
    assert model.objects.using(destination).get(pk=original.pk).title == "Routed write"
    other = "default" if explicit else alias
    assert model.objects.using(other).get(pk=original.pk).title != "Routed write"


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["audio", "video"])
def test_partial_save_with_all_sources_can_derive(audio, video, mocker, kind):
    from datetime import timedelta

    if kind == "audio":
        audio.duration = None
        duration = mocker.patch.object(
            audio, "create_duration", side_effect=lambda: setattr(audio, "duration", timedelta(seconds=7))
        )
        sizes = mocker.patch.object(
            audio, "size_to_metadata", side_effect=lambda: setattr(audio, "data", {"size": {}})
        )
        save_audio_with_derivations(audio, update_fields=iter([*audio.audio_formats, "title"]))
        duration.assert_called_once_with()
        sizes.assert_called_once_with()
        audio.refresh_from_db()
        assert audio.duration == timedelta(seconds=7)
        assert audio.data == {"size": {}}
    else:
        video.poster.name = ""
        derive = mocker.patch.object(
            video, "create_poster", side_effect=lambda: setattr(video.poster, "name", "derived.jpg")
        )
        save_video_with_derivations(video, update_fields=iter(["original"]))
        derive.assert_called_once_with()
        video.refresh_from_db()
        assert video.poster.name == "derived.jpg"
