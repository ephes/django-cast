"""Glossary review on the transcript edit view (synthetic data only)."""

import pytest
from django.contrib.auth.models import Group, Permission
from django.urls import reverse
from wagtail.models import Collection, GroupCollectionPermission

from cast.models import Contributor, EpisodeContributor, TranscriptGlossaryTerm
from cast.transcripts.corrections import (
    STATE_REJECTED,
    refresh_transcript_corrections,
)
from cast.views.transcript_glossary import corrected_context, marked_context
from tests.factories import EpisodeFactory, UserFactory
from tests.transcripts.corrections_test import BODY, make_transcript, public_texts

TEXTS = [
    (10000, "John said Gunacorn is fast."),
    (12500, "We use Button Down for mail."),
    (15000, "Later button down again."),
]


@pytest.fixture
def jon(db):
    return Contributor.objects.create(display_name="Jon Gould", slug="jon-gould", transcript_variants="John => Jon")


@pytest.fixture
def episode(settings, podcast, audio, jon):
    settings.CAST_VOXHELM_LANGUAGE = "en"
    episode = EpisodeFactory(
        owner=podcast.owner, parent=podcast, title="Mail", slug="mail", podcast_audio=audio, body=BODY
    )
    EpisodeContributor.objects.create(episode=episode, contributor=jon, role=EpisodeContributor.ROLE_GUEST)
    TranscriptGlossaryTerm.objects.create(podcast=podcast, term="Gunicorn", variants="Gunacorn")
    return episode


@pytest.fixture
def transcript(episode, audio):
    return make_transcript(audio, texts=TEXTS)


@pytest.fixture
def applied(transcript):
    refresh_transcript_corrections(transcript)
    return transcript


def edit_url(transcript):
    return reverse("cast-transcript:edit", args=(transcript.id,))


def post(client, transcript, **data):
    return client.post(edit_url(transcript), data, follow=True)


def messages_of(response):
    return [str(message).strip() for message in response.context["messages"]]


def transcript_user(name, codenames):
    user = UserFactory(username=name, is_staff=True)
    user.set_password("password")
    user.save()
    group = Group.objects.create(name=f"{name} group")
    group.permissions.add(Permission.objects.get(codename="access_admin", content_type__app_label="wagtailadmin"))
    collection = Collection.get_first_root_node()
    for codename in codenames:
        permission = Permission.objects.get(codename=codename, content_type__app_label="cast")
        GroupCollectionPermission.objects.create(group=group, collection=collection, permission=permission)
    group.user_set.add(user)
    return user


# --- rendering -------------------------------------------------------------------------------


def test_marked_context_clips_long_text_at_word_boundaries():
    text = "word " * 30 + "Gunacorn" + " tail" * 30
    start = text.index("Gunacorn")
    html = marked_context(text, start, start + len("Gunacorn"), chars=20)
    assert html.startswith("…")
    assert html.endswith("…")
    assert "<mark>Gunacorn</mark>" in html
    assert marked_context("x" * 30 + "ab" + "y" * 30, 30, 32, chars=5) == "…xxxxx<mark>ab</mark>yyyyy…"


def test_corrected_context_applies_the_other_replacements_that_are_not_rejected():
    raw = "Jon met John and Mathis at Gunacorn."

    def item(original, to, state="auto"):
        start = raw.index(original)
        return {
            "start": start,
            "end": start + len(original),
            "from": original,
            "to": to,
            "source": "x",
            "state": state,
        }

    segment = {
        "start_ms": 0,
        "raw_text": raw,
        "replacements": [
            item("John", "Jon"),
            item("Mathis", "Matthes", state="rejected"),
            item("Gunacorn", "Gunicorn"),
        ],
    }

    def context(original):
        start = raw.index(original)
        return corrected_context(segment, start, start + len(original))

    assert context("Mathis") == "Jon met Jon and <mark>Mathis</mark> at Gunicorn."
    # the marked replacement itself stays the original
    assert context("John") == "Jon met <mark>John</mark> and Mathis at Gunicorn."
    assert context("Gunacorn") == "Jon met Jon and Mathis at <mark>Gunacorn</mark>."


@pytest.mark.django_db
def test_edit_view_without_podlove_has_no_glossary_section(admin_client, audio):
    from cast.models import Transcript

    transcript = Transcript.objects.create(audio=audio)
    response = admin_client.get(edit_url(transcript))
    assert response.status_code == 200
    assert "Glossary corrections" not in response.content.decode()


@pytest.mark.django_db
def test_not_yet_applied_offers_reapply(admin_client, transcript):
    response = admin_client.get(edit_url(transcript))
    content = response.content.decode()
    assert "The glossary has not been applied to this transcript yet." in content
    assert 'value="glossary-refresh"' in content


@pytest.mark.django_db
def test_groups_and_replacements_render_with_context(admin_client, applied, episode):
    response = admin_client.get(edit_url(applied))
    content = response.content.decode()
    review = response.context["glossary_review"]

    assert review.automatic == 2
    assert review.approved == 0
    assert review.open_proposals == 2
    assert [group["to"] for group in review.groups] == ["Buttondown"]
    assert review.groups[0]["originals"] == [{"count": 2, "original": "Button Down"}]
    assert (
        "2 automatic replacements and 0 approved replacements; 1 open proposal group with 2 occurrences left to decide."
        in content
    )
    assert f"Glossary context: episode “{episode.title}”" in content
    assert "We use <mark>Button Down</mark> for mail." in content
    # each context shows the segment's other replacements applied
    assert "<mark>John</mark> said Gunicorn is fast." in content
    assert "Jon said <mark>Gunacorn</mark> is fast." in content
    assert 'value="glossary-add"' in content
    assert "data-cast-glossary-seek" in content
    assert 'data-cast-glossary-end="12.5"' in content  # bounded by the next segment


@pytest.mark.django_db
def test_rejected_replacement_is_listed_apart_and_can_be_approved_again(admin_client, applied):
    post(admin_client, applied, action="glossary-reject-replacement", start_ms=10000, start=0, end=4, to="Jon")
    response = admin_client.get(edit_url(applied))
    review = response.context["glossary_review"]
    assert [item["original"] for item in review.rejected] == ["John"]
    assert [item["original"] for item in review.replacements] == ["Gunacorn"]
    assert "1 occurrence was rejected." in response.content.decode()
    assert public_texts(applied)[0][10000] == "John said Gunicorn is fast."

    post(
        admin_client,
        applied,
        action="glossary-occurrence",
        start_ms=10000,
        start=0,
        end=4,
        to="Jon",
        decision="approved",
    )
    assert public_texts(applied)[0][10000] == "Jon said Gunicorn is fast."
    assert admin_client.get(edit_url(applied)).context["glossary_review"].rejected == []


@pytest.mark.django_db
def test_proposal_without_segment_is_skipped(admin_client, applied):
    data = applied.corrections_data
    data["proposals"][0]["start_ms"] = 99999
    applied._write_corrections_data(data)
    applied.save()
    review = admin_client.get(edit_url(applied)).context["glossary_review"]
    assert review.open_proposals == 1


@pytest.mark.django_db
def test_group_shows_the_first_occurrences_as_samples(admin_client, episode, audio):
    texts = [(1000 * index, f"Part {index}: Button Down.") for index in range(1, 6)]
    transcript = make_transcript(audio, texts=texts)
    refresh_transcript_corrections(transcript)

    response = admin_client.get(edit_url(transcript))

    group = response.context["glossary_review"].groups[0]
    assert len(group["occurrences"]) == 5
    assert [item["start_ms"] for item in group["samples"]] == [1000, 2000, 3000]
    assert "Decide one by one (5 occurrences)" in response.content.decode()


@pytest.mark.django_db
def test_transcript_text_is_escaped(admin_client, episode, audio):
    texts = [(1000, '<script>alert("x")</script> Button Down <b>bold</b>')]
    transcript = make_transcript(audio, texts=texts)
    refresh_transcript_corrections(transcript)

    content = admin_client.get(edit_url(transcript)).content.decode()

    assert "<script>alert" not in content
    assert "<b>bold</b>" not in content
    assert (
        "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt; <mark>Button Down</mark> &lt;b&gt;bold&lt;/b&gt;" in content
    )


# --- episode context -------------------------------------------------------------------------


@pytest.mark.django_db
def test_ambiguous_episode_asks_and_choice_applies(admin_client, transcript, episode, podcast, audio):
    other = EpisodeFactory(owner=podcast.owner, parent=podcast, title="Other", slug="other", podcast_audio=audio)
    content = admin_client.get(edit_url(transcript)).content.decode()
    assert "This audio is used by several episodes" in content
    assert 'value="glossary-episode"' in content
    assert 'value="glossary-refresh"' not in content

    response = post(admin_client, transcript, action="glossary-refresh")
    assert any("Choose the episode" in message for message in messages_of(response))
    assert "This audio is used by several episodes" in response.content.decode()

    response = post(admin_client, transcript, action="glossary-episode", episode=other.pk + 1000)
    assert any("glossary review action was invalid" in message for message in messages_of(response))

    response = post(admin_client, transcript, action="glossary-episode", episode=episode.pk)
    assert response.redirect_chain[-1][0] == edit_url(transcript)
    assert any("Glossary applied" in message for message in messages_of(response))
    assert public_texts(transcript)[0][10000] == "Jon said Gunicorn is fast."
    assert transcript.corrections_data["episode_id"] == episode.pk


@pytest.mark.django_db
def test_stale_episode_asks_again(admin_client, applied, episode, podcast, audio):
    other = EpisodeFactory(owner=podcast.owner, parent=podcast, title="Other", slug="other", podcast_audio=audio)
    episode.podcast_audio = None
    episode.save()

    review = admin_client.get(edit_url(applied)).context["glossary_review"]

    assert review.needs_episode
    assert review.stale_episode
    assert review.groups == []
    response = post(admin_client, applied, action="glossary-episode", episode=other.pk)
    applied.refresh_from_db()
    assert applied.corrections_data["episode_id"] == other.pk
    assert "The episode that supplied" not in response.content.decode()


@pytest.mark.django_db
def test_without_episodes_using_the_audio(admin_client, audio, settings):
    settings.CAST_VOXHELM_LANGUAGE = "en"
    transcript = make_transcript(audio, texts=TEXTS)
    content = admin_client.get(edit_url(transcript)).content.decode()
    assert "No episode uses this transcript" in content


@pytest.mark.django_db
def test_without_podlove_segments(admin_client, episode, audio):
    transcript = make_transcript(audio, texts=[])
    response = post(admin_client, transcript, action="glossary-refresh")
    assert "The transcript has no Podlove segments to correct." in messages_of(response)


# --- actions ---------------------------------------------------------------------------------


@pytest.mark.django_db
def test_reapply_applies_the_glossary(admin_client, transcript):
    response = post(admin_client, transcript, action="glossary-refresh")
    assert response.status_code == 200
    assert any("Glossary applied: 2 automatic" in message for message in messages_of(response))
    assert public_texts(transcript)[0][10000] == "Jon said Gunicorn is fast."


@pytest.mark.django_db
def test_approve_all(admin_client, applied):
    response = post(admin_client, applied, action="glossary-group", to="Buttondown", decision="approved")
    assert any("Glossary applied" in message for message in messages_of(response))
    podlove_texts, dote_texts, vtt = public_texts(applied)
    assert podlove_texts[12500] == "We use Buttondown for mail."
    assert podlove_texts[15000] == "Later Buttondown again."
    assert dote_texts[12500] == "We use Buttondown for mail."
    assert "Later Buttondown again." in vtt


@pytest.mark.django_db
def test_reject_all(admin_client, applied):
    post(admin_client, applied, action="glossary-group", to="Buttondown", decision="rejected")
    assert public_texts(applied)[0][12500] == "We use Button Down for mail."
    assert {item["state"] for item in applied.corrections_data["proposals"]} == {STATE_REJECTED}
    response = admin_client.get(edit_url(applied))
    review = response.context["glossary_review"]
    assert review.groups == []
    assert review.open_proposals == 0
    assert [item["start_ms"] for item in review.rejected] == [12500, 15000]
    assert "2 rejected occurrences" in response.content.decode()


@pytest.mark.django_db
@pytest.mark.parametrize(("decision", "expected"), [("approved", "Later Buttondown again."), ("rejected", None)])
def test_decide_one_occurrence(admin_client, applied, decision, expected):
    proposal = next(item for item in applied.corrections_data["proposals"] if item["start_ms"] == 15000)
    post(
        admin_client,
        applied,
        action="glossary-occurrence",
        start_ms=15000,
        start=proposal["start"],
        end=proposal["end"],
        to="Buttondown",
        decision=decision,
    )
    podlove_texts = public_texts(applied)[0]
    assert podlove_texts[15000] == (expected or "Later button down again.")
    assert podlove_texts[12500] == "We use Button Down for mail."
    review = admin_client.get(edit_url(applied)).context["glossary_review"]
    assert review.open_proposals == 1
    assert len(review.rejected) == (decision == "rejected")


@pytest.mark.django_db
def test_unknown_occurrence_is_an_error_message(admin_client, applied):
    before = public_texts(applied)
    response = post(
        admin_client,
        applied,
        action="glossary-occurrence",
        start_ms=15000,
        start=0,
        end=2,
        to="Buttondown",
        decision="approved",
    )
    assert response.status_code == 200
    assert any("no longer available" in message for message in messages_of(response))
    assert public_texts(applied) == before


@pytest.mark.django_db
def test_reject_automatic_replacement(admin_client, applied):
    response = post(
        admin_client, applied, action="glossary-reject-replacement", start_ms=10000, start=10, end=18, to="Gunicorn"
    )
    assert any("Glossary applied" in message for message in messages_of(response))
    assert public_texts(applied)[0][10000] == "Jon said Gunacorn is fast."
    states = [item["state"] for item in applied.corrections_data["segments"][0]["replacements"]]
    assert STATE_REJECTED in states


@pytest.mark.django_db
@pytest.mark.parametrize(
    "data",
    [
        {"action": "glossary-reject-replacement", "start_ms": "x", "start": 0, "end": 4, "to": "Jon"},
        {"action": "glossary-reject-replacement", "start_ms": -1, "start": 0, "end": 4, "to": "Jon"},
        {"action": "glossary-reject-replacement", "start_ms": 10000, "start": 0, "end": 4},
        {"action": "glossary-group", "to": "Buttondown", "decision": "maybe"},
        {"action": "glossary-group", "decision": "approved"},
        {"action": "glossary-add", "original": "", "to": "Buttondown"},
    ],
)
def test_invalid_input_is_an_error_message(admin_client, applied, data):
    before = public_texts(applied)
    response = post(admin_client, applied, **data)
    assert response.status_code == 200
    assert any("glossary review action was invalid" in message for message in messages_of(response))
    assert public_texts(applied) == before


@pytest.mark.django_db
def test_unexpected_value_error_is_an_error_message(admin_client, applied, mocker):
    mocker.patch(
        "cast.transcripts.corrections.decide_correction_group", side_effect=ValueError("action must be approved")
    )
    response = post(admin_client, applied, action="glossary-group", to="Buttondown", decision="approved")
    assert "action must be approved" in messages_of(response)


@pytest.mark.django_db
def test_add_to_glossary(admin_client, applied, podcast):
    response = post(admin_client, applied, action="glossary-add", original="Button Down", to="Buttondown")
    assert any("Glossary applied" in message for message in messages_of(response))
    assert TranscriptGlossaryTerm.objects.get(podcast=podcast, term="Buttondown").variants == "Button Down"
    assert public_texts(applied)[0][12500] == "We use Buttondown for mail."


@pytest.mark.django_db
def test_add_common_word_to_glossary_is_refused(admin_client, applied, podcast):
    before = public_texts(applied)
    response = post(admin_client, applied, action="glossary-add", original="rough", to="Ruff")
    assert response.status_code == 200
    assert any("common word" in message.lower() for message in messages_of(response)), messages_of(response)
    assert not TranscriptGlossaryTerm.objects.filter(podcast=podcast, term="Ruff").exists()
    assert public_texts(applied) == before


@pytest.mark.django_db
def test_add_to_glossary_without_episode_context(admin_client, transcript, podcast, audio):
    EpisodeFactory(owner=podcast.owner, parent=podcast, title="Other", slug="other", podcast_audio=audio)
    response = post(admin_client, transcript, action="glossary-add", original="Button Down", to="Buttondown")
    assert "Choose the episode for this transcript&#x27;s glossary first." in messages_of(response)


# --- permissions -----------------------------------------------------------------------------


@pytest.mark.django_db
def test_add_to_glossary_needs_snippet_permissions(client, applied, podcast):
    user = transcript_user("transcript-editor", ["change_transcript", "choose_transcript", "choose_audio"])
    client.force_login(user)

    content = client.get(edit_url(applied)).content.decode()
    assert 'value="glossary-group"' in content
    assert 'value="glossary-add"' not in content

    response = post(client, applied, action="glossary-add", original="Button Down", to="Buttondown")
    assert "You do not have permission to edit the glossary." in messages_of(response)
    assert not TranscriptGlossaryTerm.objects.filter(podcast=podcast, term="Buttondown").exists()

    post(client, applied, action="glossary-group", to="Buttondown", decision="approved")
    assert public_texts(applied)[0][12500] == "We use Buttondown for mail."


@pytest.mark.django_db
@pytest.mark.parametrize(
    "data",
    [
        {"action": "glossary-refresh"},
        {"action": "glossary-group", "to": "Buttondown", "decision": "approved"},
        {"action": "glossary-reject-replacement", "start_ms": 10000, "start": 0, "end": 4, "to": "Jon"},
    ],
)
def test_actions_need_transcript_change_permission(client, applied, data):
    user = transcript_user("transcript-viewer", ["choose_transcript", "choose_audio"])
    client.force_login(user)
    before = public_texts(applied)

    assert client.get(edit_url(applied)).status_code == 404
    assert client.post(edit_url(applied), data).status_code == 404
    assert public_texts(applied) == before
