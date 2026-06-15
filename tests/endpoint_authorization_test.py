"""Access-control tests for the public audio and transcript object endpoints.

These endpoints serve ``Audio`` / ``Transcript`` content addressed by raw object id.
Content may only be served when the object is reachable through a live, viewable
episode/post (the public path) or when the requester may edit a referencing page
(the editor/preview path). Bare or mismatched object ids must return 404.
"""

import pytest
from django.contrib.auth.models import AnonymousUser
from django.urls import reverse
from wagtail.models import PageViewRestriction

from cast.devdata import create_transcript

VTT_CONTENT = "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nhello\n"
DOTE_DATA = {
    "lines": [
        {
            "startTime": "00:00:00,000",
            "endTime": "00:00:01,000",
            "speakerDesignation": "",
            "text": "hello",
        }
    ]
}
PODLOVE_DATA = {"transcripts": [{"start_ms": 0, "end_ms": 1000, "text": "hello"}]}


def _anon_request(rf):
    request = rf.get("/")
    request.user = AnonymousUser()
    return request


@pytest.mark.django_db
class TestPageViewablePredicate:
    def test_live_unrestricted_page_is_publicly_viewable(self, rf, episode):
        from cast.audio_access import page_is_publicly_viewable

        assert page_is_publicly_viewable(episode, _anon_request(rf)) is True

    def test_non_live_page_is_not_publicly_viewable(self, rf, episode):
        from cast.audio_access import page_is_publicly_viewable

        episode.live = False
        assert page_is_publicly_viewable(episode, _anon_request(rf)) is False

    def test_none_page_is_not_publicly_viewable(self, rf):
        from cast.audio_access import page_is_publicly_viewable

        assert page_is_publicly_viewable(None, _anon_request(rf)) is False

    def test_login_restricted_page_blocks_anonymous(self, rf, episode):
        from cast.audio_access import page_is_publicly_viewable

        PageViewRestriction.objects.create(page=episode, restriction_type=PageViewRestriction.LOGIN)
        assert page_is_publicly_viewable(episode, _anon_request(rf)) is False

    def test_login_restricted_page_allows_authenticated(self, rf, episode, django_user_model):
        from cast.audio_access import page_is_publicly_viewable

        PageViewRestriction.objects.create(page=episode, restriction_type=PageViewRestriction.LOGIN)
        request = rf.get("/")
        request.user = django_user_model.objects.create_user("member", password="x")
        assert page_is_publicly_viewable(episode, request) is True


@pytest.mark.django_db
class TestUserCanEditPagePredicate:
    def test_anonymous_cannot_edit(self, episode):
        from cast.audio_access import user_can_edit_page

        assert user_can_edit_page(episode, AnonymousUser()) is False

    def test_superuser_can_edit(self, episode, admin_user):
        from cast.audio_access import user_can_edit_page

        assert user_can_edit_page(episode, admin_user) is True


@pytest.mark.django_db
class TestWebVTTEndpointAuthorization:
    def _url(self, transcript, *, episode_id=None):
        url = reverse("cast:webvtt-transcript", kwargs={"pk": transcript.pk})
        if episode_id is not None:
            url = f"{url}?episode_id={episode_id}"
        return url

    @pytest.fixture
    def transcript(self, audio):
        return create_transcript(audio=audio, vtt=VTT_CONTENT)

    def test_live_episode_anchor_serves(self, client, transcript, episode):
        response = client.get(self._url(transcript, episode_id=episode.pk))
        assert response.status_code == 200
        assert response["Content-Type"] == "text/vtt"

    def test_no_anchor_with_live_episode_serves(self, client, transcript, episode):
        # Bare url, but a live episode references the audio -> public path.
        response = client.get(self._url(transcript))
        assert response.status_code == 200

    def test_unattached_transcript_returns_404(self, client, transcript):
        # No episode references the audio at all.
        assert client.get(self._url(transcript)).status_code == 404

    def test_draft_episode_returns_404_for_anonymous(self, client, transcript, episode):
        episode.live = False
        episode.save()
        assert client.get(self._url(transcript, episode_id=episode.pk)).status_code == 404

    def test_draft_episode_served_for_editor(self, admin_client, transcript, episode):
        episode.live = False
        episode.save()
        assert admin_client.get(self._url(transcript, episode_id=episode.pk)).status_code == 200

    def test_mismatched_anchor_returns_404(self, client, transcript, episode, post):
        # `post` is live but does not reference this audio.
        assert client.get(self._url(transcript, episode_id=post.pk)).status_code == 404

    def test_nonexistent_anchor_returns_404(self, client, transcript, episode):
        # An anchor id that resolves to no page at all.
        assert client.get(self._url(transcript, episode_id=999999)).status_code == 404

    def test_login_restricted_episode_blocks_anonymous(self, client, transcript, episode):
        PageViewRestriction.objects.create(page=episode, restriction_type=PageViewRestriction.LOGIN)
        assert client.get(self._url(transcript, episode_id=episode.pk)).status_code == 404

    def test_login_restricted_episode_served_for_logged_in_user(
        self, client, transcript, episode, django_user_model
    ):
        PageViewRestriction.objects.create(page=episode, restriction_type=PageViewRestriction.LOGIN)
        django_user_model.objects.create_user("member", password="secret")
        client.login(username="member", password="secret")
        assert client.get(self._url(transcript, episode_id=episode.pk)).status_code == 200


@pytest.mark.django_db
class TestPodcastIndexEndpointAuthorization:
    def _url(self, transcript, *, episode_id=None):
        url = reverse("cast:podcastindex-transcript-json", kwargs={"pk": transcript.pk})
        if episode_id is not None:
            url = f"{url}?episode_id={episode_id}"
        return url

    @pytest.fixture
    def transcript(self, audio):
        return create_transcript(audio=audio, dote=DOTE_DATA)

    def test_live_episode_anchor_serves(self, client, transcript, episode):
        assert client.get(self._url(transcript, episode_id=episode.pk)).status_code == 200

    def test_unattached_transcript_returns_404(self, client, transcript):
        assert client.get(self._url(transcript)).status_code == 404

    def test_draft_episode_returns_404_for_anonymous(self, client, transcript, episode):
        episode.live = False
        episode.save()
        assert client.get(self._url(transcript, episode_id=episode.pk)).status_code == 404


@pytest.mark.django_db
class TestPodloveTranscriptJSONEndpointAuthorization:
    def _url(self, transcript, *, episode_id=None):
        url = reverse("cast:podlove-transcript-json", kwargs={"pk": transcript.pk})
        if episode_id is not None:
            url = f"{url}?episode_id={episode_id}"
        return url

    @pytest.fixture
    def transcript(self, audio):
        return create_transcript(audio=audio, podlove=PODLOVE_DATA)

    def test_live_episode_anchor_serves(self, client, transcript, episode):
        assert client.get(self._url(transcript, episode_id=episode.pk)).status_code == 200

    def test_unattached_transcript_returns_404(self, client, transcript):
        assert client.get(self._url(transcript)).status_code == 404

    def test_draft_episode_returns_404_for_anonymous(self, client, transcript, episode):
        episode.live = False
        episode.save()
        assert client.get(self._url(transcript, episode_id=episode.pk)).status_code == 404


@pytest.mark.django_db
class TestHTMLTranscriptEndpointAuthorization:
    @pytest.fixture
    def transcript(self, audio):
        return create_transcript(audio=audio, podlove=PODLOVE_DATA)

    def test_unattached_transcript_returns_404(self, client, transcript):
        url = reverse("cast:html-transcript-no-post", kwargs={"transcript_pk": transcript.pk})
        assert client.get(url).status_code == 404

    def test_live_episode_post_anchor_serves(self, client, transcript, episode):
        url = reverse(
            "cast:html-transcript",
            kwargs={"transcript_pk": transcript.pk, "post_pk": episode.pk},
        )
        # Episode owns this transcript's audio -> redirects to the canonical url.
        assert client.get(url).status_code in (200, 302)

    def test_draft_post_anchor_returns_404_for_anonymous(self, client, transcript, episode):
        episode.live = False
        episode.save()
        url = reverse(
            "cast:html-transcript",
            kwargs={"transcript_pk": transcript.pk, "post_pk": episode.pk},
        )
        assert client.get(url).status_code == 404


@pytest.mark.django_db
class TestPodloveAudioDetailEndpointAuthorization:
    def test_bare_audio_without_episode_returns_404(self, client, audio):
        url = reverse("cast:api:audio_podlove_detail", kwargs={"pk": audio.pk})
        assert client.get(url).status_code == 404

    def test_audio_with_live_episode_serves_bare(self, client, episode):
        audio = episode.podcast_audio
        url = reverse("cast:api:audio_podlove_detail", kwargs={"pk": audio.pk})
        assert client.get(url).status_code == 200

    def test_audio_with_post_anchor_serves(self, client, episode):
        audio = episode.podcast_audio
        url = reverse("cast:api:audio_podlove_detail", kwargs={"pk": audio.pk, "post_id": episode.pk})
        assert client.get(url).status_code == 200

    def test_draft_episode_returns_404_for_anonymous(self, client, episode):
        audio = episode.podcast_audio
        episode.live = False
        episode.save()
        url = reverse("cast:api:audio_podlove_detail", kwargs={"pk": audio.pk, "post_id": episode.pk})
        assert client.get(url).status_code == 404

    def test_draft_episode_served_for_editor(self, admin_client, episode):
        audio = episode.podcast_audio
        episode.live = False
        episode.save()
        url = reverse("cast:api:audio_podlove_detail", kwargs={"pk": audio.pk, "post_id": episode.pk})
        assert admin_client.get(url).status_code == 200


@pytest.mark.django_db
class TestCanonicalEpisodeTranscriptAuthorization:
    def _url(self, episode):
        return reverse(
            "cast:episode-transcript",
            kwargs={"blog_slug": episode.blog.slug, "episode_slug": episode.slug},
        )

    @pytest.fixture(autouse=True)
    def _transcript(self, episode):
        create_transcript(audio=episode.podcast_audio, podlove=PODLOVE_DATA)

    def test_live_unrestricted_episode_serves(self, client, episode):
        assert client.get(self._url(episode)).status_code == 200

    def test_login_restricted_episode_blocks_anonymous(self, client, episode):
        PageViewRestriction.objects.create(page=episode, restriction_type=PageViewRestriction.LOGIN)
        assert client.get(self._url(episode)).status_code == 404

    def test_login_restricted_episode_served_for_logged_in_user(self, client, episode, django_user_model):
        PageViewRestriction.objects.create(page=episode, restriction_type=PageViewRestriction.LOGIN)
        django_user_model.objects.create_user("member", password="secret")
        client.login(username="member", password="secret")
        assert client.get(self._url(episode)).status_code == 200


@pytest.mark.django_db
class TestRestrictedSiblingEpisodeLabelLeak:
    """A restricted live episode sharing audio with a public one must not leak its
    speaker labels into public output via the all-live-episodes aggregate fallback."""

    def _setup(self, podcast, audio, body):
        from cast.devdata import create_episode
        from cast.models import Contributor, EpisodeContributor

        public_ep = create_episode(blog=podcast, podcast_audio=audio, num=20, body=body)
        EpisodeContributor.objects.create(
            episode=public_ep,
            contributor=Contributor.objects.create(display_name="Public Host", slug="public-host-leak"),
            role=EpisodeContributor.ROLE_HOST,
            sort_order=0,
        )
        restricted_ep = create_episode(blog=podcast, podcast_audio=audio, num=21, body=body)
        EpisodeContributor.objects.create(
            episode=restricted_ep,
            contributor=Contributor.objects.create(display_name="Secret Guest", slug="secret-guest-leak"),
            role=EpisodeContributor.ROLE_GUEST,
            sort_order=0,
        )
        PageViewRestriction.objects.create(page=restricted_ep, restriction_type=PageViewRestriction.LOGIN)
        transcript = create_transcript(
            audio=audio,
            podlove={
                "transcripts": [
                    {"speaker": "Public Host", "voice": "Public Host", "text": "hi"},
                    {"speaker": "Secret Guest", "voice": "Secret Guest", "text": "secret"},
                ]
            },
        )
        return public_ep, transcript

    def test_no_anchor_transcript_excludes_restricted_sibling_labels(self, client, podcast, audio, body):
        _, transcript = self._setup(podcast, audio, body)
        url = reverse("cast:podlove-transcript-json", kwargs={"pk": transcript.pk})
        data = client.get(url).json()
        speakers = {segment.get("speaker") for segment in data["transcripts"]}
        assert "Public Host" in speakers
        assert "Secret Guest" not in speakers

    def test_podlove_detail_aggregate_excludes_restricted_sibling_labels(self, client, podcast, audio, body):
        public_ep, _ = self._setup(podcast, audio, body)
        url = reverse("cast:api:audio_podlove_detail", kwargs={"pk": audio.pk}) + f"?episode_id={public_ep.pk}"
        data = client.get(url).json()
        speakers = {segment.get("speaker") for segment in data["transcripts"]}
        assert "Public Host" in speakers
        assert "Secret Guest" not in speakers


@pytest.mark.django_db
class TestPlayerTranscriptEditorFallback:
    def _url(self, audio, *, post_id):
        return reverse("cast:api:audio_player_transcript", kwargs={"pk": audio.pk}) + f"?post_id={post_id}"

    def test_draft_episode_returns_404_for_anonymous(self, client, audio, episode):
        episode.live = False
        episode.save()
        create_transcript(audio=audio, podlove=PODLOVE_DATA)
        assert client.get(self._url(audio, post_id=episode.pk)).status_code == 404

    def test_draft_episode_served_for_editor(self, admin_client, audio, episode):
        episode.live = False
        episode.save()
        create_transcript(audio=audio, podlove=PODLOVE_DATA)
        assert admin_client.get(self._url(audio, post_id=episode.pk)).status_code == 200
