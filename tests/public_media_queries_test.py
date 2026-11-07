import pytest
from django.contrib.auth.models import AnonymousUser, Group
from django.http import Http404, HttpResponse
from wagtail.models import PageViewRestriction

from cast.audio_access import authorize_audio_access, prevent_private_media_caching
from cast.devdata import create_transcript
from cast.models import Audio, Contributor, EpisodeContributor
from cast.transcripts.visibility import public_speaker_labels_for_transcript, public_speaker_mapping_for_transcript
from tests.factories import EpisodeFactory, PodcastFactory


def episode_for(podcast, audio, number):
    return EpisodeFactory(
        parent=podcast,
        owner=podcast.owner,
        title=f"Episode {number}",
        slug=f"ep-{number}",
        body=[],
        podcast_audio=audio,
    )


def anonymous(rf):
    request = rf.get("/")
    request.user = AnonymousUser()
    request.session = {}
    return request


@pytest.mark.django_db
@pytest.mark.parametrize("count", [1, 20])
def test_public_speaker_aggregate_query_budget(podcast, rf, count, django_assert_num_queries):
    audio = Audio.objects.create(user=podcast.owner, title="Synthetic audio")
    transcript = create_transcript(audio=audio, podlove={"transcripts": [{"speaker": "Speaker 1", "text": "hi"}]})
    contributor = Contributor.objects.create(display_name="Public Person", slug="public-person")
    for index in range(count):
        episode = episode_for(podcast, audio, index)
        EpisodeContributor.objects.create(episode=episode, contributor=contributor)
    for index, kind in enumerate(
        (PageViewRestriction.LOGIN, PageViewRestriction.PASSWORD, PageViewRestriction.GROUPS)
    ):
        private = PodcastFactory(
            parent=podcast.get_parent(), owner=podcast.owner, title=f"Private {index}", slug=f"private-{index}"
        )
        PageViewRestriction.objects.create(page=private, restriction_type=kind)
        episode = episode_for(private, audio, f"private-{index}")
        private_contributor = Contributor.objects.create(display_name=f"Secret {index}", slug=f"secret-{index}")
        EpisodeContributor.objects.create(episode=episode, contributor=private_contributor)
    with django_assert_num_queries(13):
        assert public_speaker_labels_for_transcript(transcript) == {"Public Person"}
    with django_assert_num_queries(7):
        assert public_speaker_mapping_for_transcript(transcript) == {}


@pytest.mark.django_db
@pytest.mark.parametrize("count", [1, 20])
@pytest.mark.parametrize("allowed", [False, True])
@pytest.mark.parametrize("authenticated", [False, True])
def test_audio_anchor_queries_are_batched(podcast, rf, user, count, allowed, authenticated, django_assert_num_queries):
    audio = Audio.objects.create(user=podcast.owner, title="Synthetic audio")
    denied = []
    for index in range(count):
        episode = episode_for(podcast, audio, index)
        denied.append(episode.pk)
        PageViewRestriction.objects.create(page=episode, restriction_type=PageViewRestriction.GROUPS)
    public = episode_for(podcast, audio, "public") if allowed else None
    assert list(audio.episodes.values_list("pk", flat=True)) == denied + ([public.pk] if public else [])
    request = anonymous(rf)
    if authenticated:
        request.user = user
    with django_assert_num_queries(7 if authenticated else 4):
        if public:
            granting = authorize_audio_access(request, audio=audio)
            assert granting.pk == public.pk
            response = prevent_private_media_caching(HttpResponse(), granting_page=granting)
            assert "Cache-Control" not in response
        else:
            with pytest.raises(Http404):
                authorize_audio_access(request, audio=audio)


@pytest.mark.django_db
@pytest.mark.parametrize("kind", [PageViewRestriction.LOGIN, PageViewRestriction.PASSWORD, PageViewRestriction.GROUPS])
def test_batched_anchors_keep_authenticated_restrictions_private(podcast, rf, user, kind):
    audio = Audio.objects.create(user=podcast.owner, title="Synthetic audio")
    episode = episode_for(podcast, audio, 0)
    restriction = PageViewRestriction.objects.create(page=podcast, restriction_type=kind)
    request = rf.get("/")
    request.user = user
    request.session = {restriction.passed_view_restrictions_session_key: [restriction.pk]}
    if kind == PageViewRestriction.GROUPS:
        group = Group.objects.create(name="Synthetic members")
        user.groups.add(group)
        restriction.groups.add(group)
    granting = authorize_audio_access(request, audio=audio)
    assert granting.pk == episode.pk
    response = prevent_private_media_caching(HttpResponse(), granting_page=granting)
    assert response["Cache-Control"] == "private, no-store"
    assert "Cookie" in response["Vary"] and "Authorization" in response["Vary"]


@pytest.mark.django_db
@pytest.mark.parametrize("superuser", [False, True])
def test_batched_anchors_keep_draft_editor_access(podcast, rf, admin_user, superuser):
    audio = Audio.objects.create(user=podcast.owner, title="Synthetic audio")
    episode = episode_for(podcast, audio, 0)
    episode.live = False
    episode.save()
    request = anonymous(rf)
    admin_user.is_superuser = superuser
    request.user = admin_user
    granting = authorize_audio_access(request, audio=audio)
    assert granting.pk == episode.pk
    assert (
        prevent_private_media_caching(HttpResponse(), granting_page=granting)["Cache-Control"] == "private, no-store"
    )


@pytest.mark.django_db
def test_batched_anchors_resolve_alias_ancestor_restrictions(podcast, rf):
    audio = Audio.objects.create(user=podcast.owner, title="Synthetic audio")
    PageViewRestriction.objects.create(page=podcast, restriction_type=PageViewRestriction.LOGIN)
    alias = PodcastFactory(
        parent=podcast.get_parent(), owner=podcast.owner, title="Alias", slug="alias", alias_of=podcast
    )
    second_alias = PodcastFactory(
        parent=podcast.get_parent(), owner=podcast.owner, title="Alias 2", slug="alias-2", alias_of=alias
    )
    episode_for(second_alias, audio, 0)
    with pytest.raises(Http404):
        authorize_audio_access(anonymous(rf), audio=audio)


@pytest.mark.django_db
def test_legacy_public_visibility_predicate_remains_available(podcast, rf):
    from cast.transcript_sanitization import _episode_is_publicly_visible

    audio = Audio.objects.create(user=podcast.owner, title="Synthetic audio")
    episode = episode_for(podcast, audio, 0)
    assert _episode_is_publicly_visible(episode)
    PageViewRestriction.objects.create(page=podcast, restriction_type=PageViewRestriction.LOGIN)
    assert not _episode_is_publicly_visible(episode)


@pytest.mark.django_db
@pytest.mark.parametrize("alias_kind", ["episode", "ancestor"])
def test_aggregate_speakers_exclude_restricted_alias_sources(podcast, alias_kind):
    from cast.models import TranscriptSpeakerMapping

    audio = Audio.objects.create(user=podcast.owner, title="Synthetic audio")
    transcript = create_transcript(audio=audio, podlove={"transcripts": [{"speaker": "Speaker 1", "text": "hi"}]})
    public = episode_for(podcast, audio, "public")
    visible = Contributor.objects.create(display_name="Public Person", slug="public-person")
    EpisodeContributor.objects.create(episode=public, contributor=visible)
    if alias_kind == "episode":
        source = episode_for(podcast, audio, "source")
        PageViewRestriction.objects.create(page=source, restriction_type=PageViewRestriction.LOGIN)
        target = EpisodeFactory(
            parent=podcast,
            owner=podcast.owner,
            title="Alias",
            slug="alias",
            body=[],
            podcast_audio=audio,
            alias_of=source,
        )
    else:
        source = PodcastFactory(parent=podcast.get_parent(), owner=podcast.owner, title="Private", slug="private")
        PageViewRestriction.objects.create(page=source, restriction_type=PageViewRestriction.LOGIN)
        alias = PodcastFactory(
            parent=podcast.get_parent(), owner=podcast.owner, title="Alias", slug="alias", alias_of=source
        )
        target = episode_for(alias, audio, "private")
    hidden = Contributor.objects.create(display_name="Private Person", slug="private-person")
    EpisodeContributor.objects.create(episode=target, contributor=hidden)
    TranscriptSpeakerMapping.objects.update_or_create(
        transcript=transcript,
        speaker_label="Speaker 1",
        defaults={
            "contributor": hidden,
            "review_state": "approved",
            "source_artifact_fingerprint": transcript.mapping_fingerprint(),
        },
    )
    assert public_speaker_labels_for_transcript(transcript) == {"Public Person"}
    assert public_speaker_mapping_for_transcript(transcript) == {}


def test_visibility_helpers_tolerate_missing_optional_mapping_data():
    from types import SimpleNamespace

    from cast.transcripts.visibility import _current_mapping_rows, _current_raw_speaker_labels, _public_contributor_ids

    assert _current_mapping_rows(SimpleNamespace()) == []
    assert _current_raw_speaker_labels(SimpleNamespace()) == set()
    episode = SimpleNamespace(
        visible_contributor_assignments=[SimpleNamespace(contributor_id=None), SimpleNamespace(contributor_id=23)]
    )
    assert _public_contributor_ids([episode]) == {23}


@pytest.mark.django_db
def test_over_one_thousand_audio_anchors_preserve_authorization_and_speaker_privacy(podcast, rf, user):
    """Exercise real ORM queries beyond SQLite's expression-depth limit."""
    audio = Audio.objects.create(user=podcast.owner, title="Synthetic shared audio")
    transcript = create_transcript(audio=audio, podlove={"transcripts": [{"speaker": "Speaker 1", "text": "hi"}]})
    source = PodcastFactory(parent=podcast.get_parent(), owner=podcast.owner, title="Source", slug="source")
    restriction = PageViewRestriction.objects.create(page=source, restriction_type=PageViewRestriction.GROUPS)
    group = Group.objects.create(name="Synthetic listeners")
    restriction.groups.add(group)
    user.groups.add(group)
    alias = PodcastFactory(
        parent=podcast.get_parent(), owner=podcast.owner, title="Alias", slug="alias", alias_of=source
    )
    alias = PodcastFactory(
        parent=podcast.get_parent(), owner=podcast.owner, title="Alias chain", slug="alias-chain", alias_of=alias
    )
    episodes = [episode_for(alias, audio, number) for number in range(1100)]
    hidden = Contributor.objects.create(display_name="Private Person", slug="private-person")
    EpisodeContributor.objects.create(episode=episodes[0], contributor=hidden)
    public = episode_for(podcast, audio, "last-public")
    visible = Contributor.objects.create(display_name="Public Person", slug="public-person")
    EpisodeContributor.objects.create(episode=public, contributor=visible)

    request = anonymous(rf)
    assert not all(row.accept_request(request) for row in episodes[0].get_view_restrictions())
    assert authorize_audio_access(request, audio=audio).pk == public.pk
    assert public_speaker_labels_for_transcript(transcript) == {"Public Person"}

    public.live = False
    public.save()
    with pytest.raises(Http404):
        authorize_audio_access(request, audio=audio)
    assert public_speaker_labels_for_transcript(transcript) is None

    request.user = user
    assert all(row.accept_request(request) for row in episodes[0].get_view_restrictions())
    granting = authorize_audio_access(request, audio=audio)
    assert granting.pk == episodes[0].pk
    assert (
        prevent_private_media_caching(HttpResponse(), granting_page=granting)["Cache-Control"] == "private, no-store"
    )
