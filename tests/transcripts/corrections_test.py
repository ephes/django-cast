"""Applying the transcript glossary to stored transcripts (synthetic data only)."""

import json
import logging

import pytest
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import reverse
from wagtail import blocks
from wagtail.blocks import StreamValue
from wagtail.rich_text import RichText

from cast.models import (
    Contributor,
    EpisodeContributor,
    Transcript,
    TranscriptGlossaryTerm,
    TranscriptSpeakerMapping,
)
from cast.models.contributors import get_voice_reference_storage
from cast.transcripts import corrections, dote, podlove, webvtt
from cast.transcripts.corrections import (
    STATE_APPROVED,
    STATE_AUTO,
    STATE_OPEN,
    STATE_REJECTED,
    STATUS_APPLIED,
    STATUS_NEEDS_EPISODE,
    STATUS_NO_SEGMENTS,
    add_original_to_glossary,
    apply_transcript_corrections,
    decide_correction_group,
    decide_correction_occurrence,
    episodes_using_audio,
    refresh_transcript_corrections,
    reject_automatic_replacement,
    set_corrections_episode,
)
from cast.transcripts.glossary import episode_terms, phrase_spans
from cast.voxhelm import VoxhelmTranscriptService
from tests.factories import EpisodeFactory

TEXTS = [
    (10000, "John said Gunacorn is fast."),
    (12500, "We use Button Down for mail."),
    (15000, "Nothing to fix here."),
    (17500, "John's talk & more."),
]


def podlove_data(texts=TEXTS, speaker=""):
    return {
        "version": 1,
        "transcripts": [
            {"start_ms": start_ms, "speaker": speaker, "voice": speaker, "text": text} for start_ms, text in texts
        ],
    }


def dote_data(texts=TEXTS):
    def stamp(ms):
        return f"00:00:{ms // 1000:02},{ms % 1000:03}"

    return {
        "lines": [
            {"startTime": stamp(ms), "endTime": stamp(ms + 1000), "speakerDesignation": "", "text": text}
            for ms, text in texts
        ]
    }


def vtt_content(texts=TEXTS):
    cues = []
    for ms, text in texts:
        escaped = webvtt.escape_cue_text(text)
        cues.append(f"00:00:{ms // 1000:02}.{ms % 1000:03} --> 00:00:{ms // 1000 + 1:02}.{ms % 1000:03}\n{escaped}\n")
    return "WEBVTT\n\n" + "\n".join(cues)


def make_transcript(audio, *, texts=TEXTS, vtt=None, speakers=None, speaker=""):
    transcript = Transcript.objects.create(audio=audio)
    podlove_content = json.dumps(podlove_data(texts, speaker)).encode()
    transcript.podlove.save("t.podlove.json", ContentFile(podlove_content), save=False)
    transcript.dote.save("t.dote.json", ContentFile(json.dumps(dote_data(texts)).encode()), save=False)
    transcript.vtt.save("t.vtt", ContentFile((vtt if vtt is not None else vtt_content(texts)).encode()), save=False)
    if speakers is not None:
        transcript.speakers.save("t.speakers.json", ContentFile(json.dumps(speakers).encode()), save=False)
    transcript.save()
    return transcript


def public_texts(transcript):
    transcript.refresh_from_db()
    podlove_texts = {segment["start_ms"]: segment["text"] for segment in transcript.podlove_data["transcripts"]}
    dote_texts = {dote.dote_timestamp_to_ms(line["startTime"]): line["text"] for line in transcript.dote_data["lines"]}
    return podlove_texts, dote_texts, transcript._load_text_file("vtt")


def file_bytes(transcript):
    transcript.refresh_from_db()
    return {name: transcript._read_file_bytes(name) for name in ("podlove", "dote", "vtt", "corrections")}


BODY = json.dumps(
    [
        {
            "type": "overview",
            "value": [
                {"type": "paragraph", "value": '<p>Newsletter: <a href="https://example.com">Buttondown</a></p>'},
            ],
        }
    ]
)


@pytest.fixture
def glossary_settings(settings):
    settings.CAST_VOXHELM_LANGUAGE = "en"


@pytest.fixture
def jon(db):
    return Contributor.objects.create(display_name="Jon Gould", slug="jon-gould", transcript_variants="John => Jon")


@pytest.fixture
def glossary_episode(glossary_settings, podcast, audio, jon):
    episode = EpisodeFactory(
        owner=podcast.owner, parent=podcast, title="Mail", slug="mail", podcast_audio=audio, body=BODY
    )
    EpisodeContributor.objects.create(episode=episode, contributor=jon, role=EpisodeContributor.ROLE_GUEST)
    TranscriptGlossaryTerm.objects.create(podcast=podcast, term="Gunicorn", variants="Gunacorn")
    return episode


@pytest.fixture
def transcript(glossary_episode, audio):
    return make_transcript(audio)


# --- format transforms -----------------------------------------------------------------------


def test_podlove_get_texts_skips_duplicate_starts_and_bad_segments():
    data = {
        "transcripts": [
            {"start_ms": 1, "text": "a"},
            {"start_ms": 2, "text": "b"},
            {"start_ms": 2, "text": "c"},
            {"start_ms": "3", "text": "d"},
            "junk",
        ]
    }
    assert podlove.get_texts(data) == [(1, "a")]
    assert podlove.get_texts({}) == []


def test_set_texts_ignore_missing_lists_and_bad_entries():
    assert podlove.set_texts({}, {1: "x"}) == 0
    assert dote.set_texts({}, {1: "x"}) == 0
    data = {"transcripts": ["junk", {"start_ms": "1", "text": "a"}, {"start_ms": 1, "text": "x"}]}
    assert podlove.set_texts(data, {1: "x"}) == 0
    lines = {"lines": ["junk", {"startTime": "bad", "text": "a"}, {"startTime": "00:00:00,001", "text": "a"}]}
    assert dote.set_texts(lines, {1: "b"}) == 1
    assert lines["lines"][2]["text"] == "b"


@pytest.mark.parametrize(
    ("lines", "expected"),
    [
        (["<v Jon>John said</v>\n"], ["<v Jon>Jon said</v>\n"]),
        (["<v Jon>John said\n"], ["<v Jon>Jon said\n"]),
        (["Speaker 1: John said\r\n"], ["Speaker 1: Jon said\r\n"]),
        (["John\n", "said\n"], ["Jon said\n"]),
        (["<v Jon>Jon said</v>\n"], ["<v Jon>Jon said</v>\n"]),
        (["<v A>John</v> <v B>said</v>\n"], None),
        (["<i>John said</i>\n"], None),
        ([], None),
    ],
)
def test_set_cue_text_keeps_voice_and_prefix(lines, expected):
    assert webvtt.set_cue_text(lines, "Jon said") == expected


def test_set_texts_in_content_matches_cues_by_start():
    content = "WEBVTT\n\nNOTE x\n\n00:00:01.000 --> 00:00:02.000\na &amp; b\n\nbad --> x\nc\n"
    rewritten, changed = webvtt.set_texts_in_content(content, {1000: "a < b"})
    assert changed == 1
    assert "a &lt; b\n" in rewritten
    assert rewritten.endswith("bad --> x\nc\n")
    assert webvtt.set_texts_in_content(rewritten, {1000: "a < b"}) == (rewritten, 0)


# --- applying --------------------------------------------------------------------------------


@pytest.mark.django_db
def test_refresh_corrects_all_formats_and_keeps_raw_text(transcript):
    fingerprint = transcript.source_fingerprint

    result = refresh_transcript_corrections(transcript)

    assert result.status == STATUS_APPLIED
    assert result.automatic == 3  # John, Gunacorn, John's
    assert result.changed == 2
    assert result.proposals >= 1
    podlove_texts, dote_texts, vtt = public_texts(transcript)
    assert podlove_texts[10000] == dote_texts[10000] == "Jon said Gunicorn is fast."
    assert podlove_texts[17500] == dote_texts[17500] == "Jon's talk & more."
    assert "Jon said Gunicorn is fast.\n" in vtt
    assert "Jon's talk &amp; more.\n" in vtt
    assert podlove_texts[12500] == "We use Button Down for mail."
    data = transcript.corrections_data
    assert data["version"] == 1
    assert data["episode_id"] == transcript.audio.episodes.get().pk
    assert data["source_fingerprint"] == fingerprint == transcript.source_fingerprint
    assert len(data["glossary_fingerprint"]) == 64
    assert [segment["raw_text"] for segment in data["segments"]] == [text for _ms, text in TEXTS]
    assert data["segments"][0]["replacements"][0] == {
        "start": 0,
        "end": 4,
        "from": "John",
        "to": "Jon",
        "source": "contributor",
        "state": STATE_AUTO,
    }
    proposal = next(item for item in data["proposals"] if item["to"] == "Buttondown")
    assert proposal["original"] == "Button Down"
    assert proposal["state"] == STATE_OPEN
    assert transcript.corrections.storage is get_voice_reference_storage()
    assert transcript.corrections.name.startswith("cast_transcript_corrections/")


@pytest.mark.django_db
def test_refresh_and_apply_are_idempotent(transcript):
    refresh_transcript_corrections(transcript)
    first = file_bytes(transcript)

    again = refresh_transcript_corrections(transcript)

    assert again.changed == 0
    assert file_bytes(transcript) == first
    assert apply_transcript_corrections(transcript) == 0
    assert file_bytes(transcript) == first


@pytest.mark.django_db
def test_apply_rewrites_public_files_from_the_sidecar(transcript):
    refresh_transcript_corrections(transcript)
    transcript.podlove.save("t.podlove.json", ContentFile(json.dumps(podlove_data()).encode()), save=False)
    transcript.save(preserve_source_fingerprint=True)

    assert apply_transcript_corrections(transcript) == 2
    assert public_texts(transcript)[0][10000] == "Jon said Gunicorn is fast."


@pytest.mark.django_db
def test_apply_without_current_sidecar_does_nothing(transcript):
    assert apply_transcript_corrections(transcript) == 0


@pytest.mark.django_db
def test_dry_run_writes_nothing(transcript):
    before = file_bytes(transcript)

    result = refresh_transcript_corrections(transcript, dry_run=True)

    assert result.changed == 2
    assert file_bytes(transcript) == before


@pytest.mark.django_db
def test_transcript_without_podlove_segments(audio):
    transcript = Transcript.objects.create(audio=audio)
    assert refresh_transcript_corrections(transcript).status == STATUS_NO_SEGMENTS
    assert decide_correction_group(transcript, "Jon", STATE_APPROVED).status == STATUS_NO_SEGMENTS


@pytest.mark.django_db
def test_row_without_source_fingerprint_records_it_first(transcript):
    Transcript.objects.filter(pk=transcript.pk).update(source_fingerprint="")
    transcript.refresh_from_db()

    refresh_transcript_corrections(transcript)
    transcript.refresh_from_db()

    assert transcript.source_fingerprint
    assert transcript.corrections_data["source_fingerprint"] == transcript.source_fingerprint
    assert refresh_transcript_corrections(transcript).changed == 0


@pytest.mark.django_db
def test_malformed_sidecar_is_replaced(transcript):
    transcript.corrections.save("x.corrections.json", ContentFile(b"[1]"), save=False)
    transcript.save(update_fields=["corrections"])
    assert transcript.corrections_data == {}

    assert refresh_transcript_corrections(transcript).status == STATUS_APPLIED
    assert transcript.corrections_data["version"] == 1


@pytest.mark.django_db
def test_corrections_data_handles_missing_file(transcript):
    transcript.corrections.name = "cast_transcript_corrections/missing.json"
    assert transcript.corrections_data == {}


# --- editor state ----------------------------------------------------------------------------


@pytest.mark.django_db
def test_rejected_replacement_stays_rejected_after_refresh(transcript, jon):
    refresh_transcript_corrections(transcript)

    reject_automatic_replacement(transcript, start_ms=10000, start=0, end=4, to="Jon")
    jon.transcript_variants = "John => Jon\nJohn Gould => Jon Gould"
    jon.save()
    refresh_transcript_corrections(transcript)

    assert public_texts(transcript)[0][10000] == "John said Gunicorn is fast."
    states = [item["state"] for item in transcript.corrections_data["segments"][0]["replacements"]]
    assert states == [STATE_REJECTED, STATE_AUTO]
    with pytest.raises(LookupError):
        reject_automatic_replacement(transcript, start_ms=15000, start=0, end=4, to="Jon")
    with pytest.raises(LookupError):
        reject_automatic_replacement(transcript, start_ms=10000, start=1, end=4, to="Jon")


@pytest.mark.django_db
def test_approved_group_applies_to_every_occurrence(audio, glossary_episode):
    texts = [(1000, "Ask Button Down."), (2000, "button down again.")]
    transcript = make_transcript(audio, texts=texts)
    refresh_transcript_corrections(transcript)

    result = decide_correction_group(transcript, "Buttondown", STATE_APPROVED)

    assert result.approved == 2
    podlove_texts, dote_texts, vtt = public_texts(transcript)
    assert podlove_texts == {1000: "Ask Buttondown.", 2000: "Buttondown again."}
    assert dote_texts == podlove_texts
    assert "Buttondown again." in vtt
    assert transcript.corrections_data["decisions"] == [
        {"original": "Button Down", "to": "Buttondown", "state": STATE_APPROVED}
    ]
    # Decisions persist across a refresh with a changed glossary.
    TranscriptGlossaryTerm.objects.create(podcast=glossary_episode.get_parent().specific, term="Mail")
    assert refresh_transcript_corrections(transcript).approved == 2


@pytest.mark.django_db
def test_approved_original_also_replaces_unproposed_occurrences(audio, glossary_episode):
    transcript = make_transcript(audio, texts=[(1000, "The newsletter tool."), (2000, "Another tool.")])

    result = decide_correction_group(transcript, "Buttondown", STATE_APPROVED, originals=["tool", "Tool"])

    assert result.approved == 2
    assert public_texts(transcript)[0] == {1000: "The newsletter Buttondown.", 2000: "Another Buttondown."}
    decisions = transcript.corrections_data["decisions"]
    assert decisions == [{"original": "tool", "to": "Buttondown", "state": STATE_APPROVED}]


@pytest.mark.django_db
def test_rejected_group_suppresses_proposals(transcript):
    refresh_transcript_corrections(transcript)

    result = decide_correction_group(transcript, "Buttondown", STATE_REJECTED)
    refresh_transcript_corrections(transcript)

    assert result.status == STATUS_APPLIED
    states = [item["state"] for item in transcript.corrections_data["proposals"] if item["to"] == "Buttondown"]
    assert states == [STATE_REJECTED]  # listed as rejected, no longer open
    assert result.proposals == 0
    assert public_texts(transcript)[0][12500] == "We use Button Down for mail."
    with pytest.raises(ValueError):
        decide_correction_group(transcript, "Buttondown", "maybe")


@pytest.mark.django_db
def test_decide_one_occurrence(transcript):
    refresh_transcript_corrections(transcript)
    proposal = next(item for item in transcript.corrections_data["proposals"] if item["to"] == "Buttondown")
    position = {key: proposal[key] for key in ("start_ms", "start", "end", "to")}

    decide_correction_occurrence(transcript, **position, action=STATE_APPROVED)
    assert public_texts(transcript)[0][12500] == "We use Buttondown for mail."
    refresh_transcript_corrections(transcript)
    assert public_texts(transcript)[0][12500] == "We use Buttondown for mail."

    reject_automatic_replacement(
        transcript, start_ms=12500, start=proposal["start"], end=proposal["end"], to="Buttondown"
    )
    assert public_texts(transcript)[0][12500] == "We use Button Down for mail."
    proposal = next(item for item in transcript.corrections_data["proposals"] if item["to"] == "Buttondown")
    assert proposal["state"] == STATE_REJECTED

    with pytest.raises(LookupError):
        decide_correction_occurrence(transcript, start_ms=1, start=0, end=1, to="x", action=STATE_REJECTED)


@pytest.mark.django_db
def test_approved_occurrence_wins_over_another_target_of_the_span(transcript, podcast, jon):
    # "John" maps to Jon (contributor) and Johnny (show term): a conflict, so proposals for both.
    TranscriptGlossaryTerm.objects.create(podcast=podcast, term="Johnny", variants="John")
    refresh_transcript_corrections(transcript)
    targets = {
        item["to"]
        for item in transcript.corrections_data["proposals"]
        if (item["start_ms"], item["start"]) == (10000, 0)
    }
    assert targets == {"Jon", "Johnny"}

    decide_correction_occurrence(transcript, start_ms=10000, start=0, end=4, to="Johnny", action=STATE_APPROVED)

    assert public_texts(transcript)[0][10000] == "Johnny said Gunicorn is fast."
    remaining = [item["to"] for item in transcript.corrections_data["proposals"] if item["start_ms"] == 10000]
    assert remaining == ["Johnny"]


# --- glossary additions ----------------------------------------------------------------------


@pytest.mark.django_db
def test_add_original_to_existing_show_term(transcript, podcast):
    add_original_to_glossary(transcript, "Gunna Corn", "gunicorn")

    term = TranscriptGlossaryTerm.objects.get(podcast=podcast, term="Gunicorn")
    assert term.variant_list == ["Gunacorn", "Gunna Corn"]


@pytest.mark.django_db
def test_add_original_creates_show_term_and_applies_it(transcript, podcast):
    result = add_original_to_glossary(transcript, "Button Down", "Buttondown")

    term = TranscriptGlossaryTerm.objects.get(podcast=podcast, term="Buttondown")
    assert term.variants == "Button Down"
    # The approved decision takes the span; the new variant would replace it the same way.
    assert (result.automatic, result.approved) == (3, 1)
    assert public_texts(transcript)[0][12500] == "We use Buttondown for mail."


@pytest.mark.django_db
def test_add_original_to_contributor(transcript, jon):
    add_original_to_glossary(transcript, "John Goold", "Jon Gould")
    add_original_to_glossary(transcript, "Jonn", "Jon")

    jon.refresh_from_db()
    assert jon.transcript_variants == "John => Jon\nJohn Goold\nJonn => Jon"


@pytest.mark.django_db
def test_add_original_refuses_common_word(transcript, podcast):
    with pytest.raises(corrections.GlossaryAddError) as error:
        add_original_to_glossary(transcript, "rough", "Ruff")
    assert "variants" in error.value.message_dict
    assert not TranscriptGlossaryTerm.objects.filter(podcast=podcast, term="Ruff").exists()


@pytest.mark.django_db
def test_add_original_needs_an_episode(audio, glossary_settings):
    transcript = make_transcript(audio)
    with pytest.raises(corrections.GlossaryAddError):
        add_original_to_glossary(transcript, "Button Down", "Buttondown")


# --- episode context -------------------------------------------------------------------------


@pytest.mark.django_db
def test_ambiguous_episode_stores_raw_text_and_waits_for_a_choice(transcript, glossary_episode, podcast, audio):
    other = EpisodeFactory(owner=podcast.owner, parent=podcast, title="Other", slug="other", podcast_audio=audio)
    before = file_bytes(transcript)

    result = refresh_transcript_corrections(transcript)

    assert result.status == STATUS_NEEDS_EPISODE
    assert result.needs_episode
    data = transcript.corrections_data
    assert data["episode_id"] is None
    assert [segment["replacements"] for segment in data["segments"]] == [[]] * len(TEXTS)
    assert data["proposals"] == []
    after = file_bytes(transcript)
    assert {name: after[name] for name in ("podlove", "dote", "vtt")} == {
        name: before[name] for name in ("podlove", "dote", "vtt")
    }
    assert refresh_transcript_corrections(transcript).needs_episode
    assert decide_correction_group(transcript, "Jon", STATE_APPROVED).needs_episode
    assert [episode.pk for episode in episodes_using_audio(transcript)] == sorted([glossary_episode.pk, other.pk])

    no_audio = EpisodeFactory(owner=podcast.owner, parent=podcast, title="No audio", slug="no-audio", body=BODY)
    with pytest.raises(ValidationError):
        set_corrections_episode(transcript, no_audio)
    result = set_corrections_episode(transcript, glossary_episode)

    assert result.status == STATUS_APPLIED
    assert transcript.corrections_data["episode_id"] == glossary_episode.pk
    assert public_texts(transcript)[0][10000] == "Jon said Gunicorn is fast."


@pytest.mark.django_db
def test_explicit_episode_wins_at_first_run(transcript, glossary_episode, podcast, audio):
    EpisodeFactory(owner=podcast.owner, parent=podcast, title="Other", slug="other", podcast_audio=audio)

    result = refresh_transcript_corrections(transcript, episode=glossary_episode)

    assert result.status == STATUS_APPLIED


@pytest.mark.django_db
def test_set_episode_without_podlove_segments(glossary_episode, audio):
    transcript = Transcript.objects.create(audio=audio)
    assert set_corrections_episode(transcript, glossary_episode).status == STATUS_NO_SEGMENTS


@pytest.mark.django_db
def test_episode_no_longer_using_the_audio_stops_reapplication(transcript, glossary_episode):
    refresh_transcript_corrections(transcript)
    before = file_bytes(transcript)
    glossary_episode.podcast_audio = None
    glossary_episode.save()

    result = refresh_transcript_corrections(transcript)

    assert result.needs_episode
    assert file_bytes(transcript) == before


@pytest.mark.django_db
def test_new_source_starts_a_fresh_sidecar(transcript):
    refresh_transcript_corrections(transcript)
    decide_correction_group(transcript, "Buttondown", STATE_APPROVED)
    new_texts = [(20000, "John is back.")]
    transcript.podlove.save("new.podlove.json", ContentFile(json.dumps(podlove_data(new_texts)).encode()), save=False)
    transcript.save()
    assert transcript.source_fingerprint != transcript.corrections_data["source_fingerprint"]

    refresh_transcript_corrections(transcript)

    data = transcript.corrections_data
    assert data["source_fingerprint"] == transcript.source_fingerprint
    assert data["decisions"] == []
    assert [segment["raw_text"] for segment in data["segments"]] == ["John is back."]
    assert public_texts(transcript)[0] == {20000: "Jon is back."}


def test_show_note_sources_walks_nested_values():
    value = {"a": [RichText("<p>one</p>"), "plain"], "b": RichText("<p>two</p>")}
    assert list(corrections._show_note_sources(value)) == ["<p>one</p>", "<p>two</p>"]


class ExtraLinkBlock(blocks.StructBlock):
    title = blocks.CharBlock()
    url = blocks.URLBlock()


class LinkItemBlock(blocks.StructBlock):
    title = blocks.CharBlock()
    url = blocks.URLBlock()
    description = blocks.RichTextBlock(required=False)
    extra_links = blocks.ListBlock(ExtraLinkBlock(), required=False)


class SponsorBlock(blocks.StructBlock):
    heading = blocks.CharBlock()
    show_heading = blocks.BooleanBlock(required=False)
    sponsor_name = blocks.CharBlock()
    sponsor_url = blocks.URLBlock()


class UnlabelledLinkBlock(blocks.StructBlock):
    url = blocks.URLBlock()
    enabled = blocks.BooleanBlock(required=False)
    other_url = blocks.URLBlock(required=False)


SHOW_NOTES = blocks.StreamBlock(
    [
        ("links", blocks.ListBlock(LinkItemBlock())),
        ("sponsor", SponsorBlock()),
        ("unlabelled", UnlabelledLinkBlock()),
    ]
)


def test_show_note_sources_reads_links_kept_as_struct_block_fields():
    value = SHOW_NOTES.to_python(
        [
            {
                "type": "links",
                "value": [
                    {
                        "title": "getscaf",
                        "url": "https://github.com/getscaf",
                        "description": "<p>by Calvin</p>",
                        "extra_links": [
                            {"title": "copier & <b>co</b>", "url": "https://github.com/copier-org/copier"}
                        ],
                    },
                    {"title": "", "url": "https://example.com/untitled"},
                ],
            },
            {
                "type": "sponsor",
                "value": {"heading": "Sponsor", "sponsor_name": "Six Feet Up", "sponsor_url": "https://sixfeetup.com"},
            },
            {"type": "unlabelled", "value": {"url": "https://example.com/a", "other_url": "https://example.com/b"}},
        ]
    )

    sources = list(corrections._show_note_sources(value))

    assert sources == [
        '<p><a href="https://github.com/getscaf">getscaf</a></p>',
        "<p>by Calvin</p>",
        '<p><a href="https://github.com/copier-org/copier">copier &amp; &lt;b&gt;co&lt;/b&gt;</a></p>',
        '<p><a href="https://sixfeetup.com">Six Feet Up</a></p>',
    ]
    terms = episode_terms("\n".join(sources))
    assert {"getscaf", "scaf", "copier & <b>co</b>", "Six Feet Up", "Calvin"} <= set(terms)


def test_struct_block_links_keep_author_phrases_apart():
    items = [
        {"title": "A book by Daniel Green", "url": "https://example.com/book"},
        {"title": "Django", "url": "https://djangoproject.com"},
    ]
    value = SHOW_NOTES.to_python([{"type": "links", "value": items}])

    terms = episode_terms("\n".join(corrections._show_note_sources(value)))

    assert {"Daniel Green", "Green", "Django"} <= set(terms)
    assert "Daniel Green Django" not in terms


@pytest.mark.django_db
def test_contributor_with_two_roles_counts_once(glossary_episode, jon):
    EpisodeContributor.objects.create(episode=glossary_episode, contributor=jon, role=EpisodeContributor.ROLE_HOST)
    glossary, _fingerprint = corrections.effective_glossary(glossary_episode)
    assert [target.text for target in glossary.proposal_targets].count("Jon Gould") == 1


@pytest.mark.django_db
def test_transcript_without_webvtt(audio, glossary_episode):
    transcript = make_transcript(audio)
    transcript.vtt = None
    transcript.save()

    assert refresh_transcript_corrections(transcript).changed == 2
    assert not transcript.vtt


@pytest.mark.django_db
def test_episode_terms_come_from_the_body(glossary_episode):
    assert isinstance(glossary_episode.body, StreamValue)
    glossary, fingerprint = corrections.effective_glossary(glossary_episode)
    assert "Buttondown" in {target.text for target in glossary.proposal_targets}
    assert glossary.language == "en"


# --- speakers --------------------------------------------------------------------------------

SPEAKERS = {
    "summary": {"strategy": "pyannote_known_speaker"},
    "segments": [
        {"index": 0, "start": 10.0, "speaker": "Jon Gould", "speaker_uncertain": False},
        {"index": 1, "start": 12.5, "speaker": "Host", "speaker_uncertain": False},
    ],
}


@pytest.mark.django_db
@pytest.mark.parametrize("corrections_first", [True, False])
def test_speaker_application_and_corrections_keep_each_other(audio, glossary_episode, corrections_first):
    transcript = make_transcript(audio, speakers=SPEAKERS)
    if corrections_first:
        refresh_transcript_corrections(transcript)
        transcript.refresh_from_db()
        transcript.apply_known_speaker_suggestions(smooth=False)
    else:
        transcript.apply_known_speaker_suggestions(smooth=False)
        transcript.refresh_from_db()
        refresh_transcript_corrections(transcript)

    transcript.refresh_from_db()
    segment = transcript.podlove_data["transcripts"][0]
    assert (segment["speaker"], segment["text"]) == ("Jon Gould", "Jon said Gunicorn is fast.")
    line = transcript.dote_data["lines"][0]
    assert (line["speakerDesignation"], line["text"]) == ("Jon Gould", "Jon said Gunicorn is fast.")
    assert "<v Jon Gould>Jon said Gunicorn is fast.\n" in transcript._load_text_file("vtt")


@pytest.mark.django_db
def test_both_orders_give_the_same_files(audio, glossary_episode, podcast):
    results = []
    for corrections_first in (True, False):
        transcript = make_transcript(audio, speakers=SPEAKERS)
        steps = [
            lambda t: refresh_transcript_corrections(t),
            lambda t: t.apply_known_speaker_suggestions(smooth=False),
        ]
        for step in steps if corrections_first else reversed(steps):
            transcript.refresh_from_db()
            step(transcript)
        results.append({name: value for name, value in file_bytes(transcript).items() if name != "corrections"})
        transcript.delete()
    assert results[0] == results[1]


@pytest.mark.django_db
def test_approved_speaker_mappings_stay_current_after_corrections(audio, glossary_episode):
    transcript = make_transcript(audio, speaker="Speaker 1")
    TranscriptSpeakerMapping.objects.create(
        transcript=transcript,
        speaker_label="Speaker 1",
        display_name="Jon Gould",
        review_state=TranscriptSpeakerMapping.ReviewState.APPROVED,
        source_artifact_fingerprint=transcript.source_fingerprint,
    )

    refresh_transcript_corrections(transcript)
    transcript.refresh_from_db()
    transcript.sync_speaker_mappings()

    mapping = transcript.speaker_mappings.get()
    assert mapping.is_current_for_fingerprint(transcript.mapping_fingerprint())


# --- import hook -----------------------------------------------------------------------------


class StubClient:
    def download_artifact(self, path):
        return {
            "/podlove": json.dumps(podlove_data()).encode(),
            "/dote": json.dumps(dote_data()).encode(),
            "/vtt": vtt_content().encode(),
        }[path]


JOB = {
    "id": "job-1",
    "state": "succeeded",
    "result": {"artifacts": {"podlove": "/podlove", "dote": "/dote", "vtt": "/vtt"}},
}


@pytest.mark.django_db
def test_import_applies_the_glossary(audio, glossary_episode):
    result = VoxhelmTranscriptService(client=StubClient()).complete_audio_job(
        audio, job_id="job-1", source_url="https://example.com/a.m4a", initial_job_payload=JOB
    )

    data = result.transcript.corrections_data
    assert data["segments"][0]["raw_text"] == "John said Gunacorn is fast."
    assert public_texts(result.transcript)[0][10000] == "Jon said Gunicorn is fast."


@pytest.mark.django_db
def test_import_survives_a_failing_glossary_step(audio, glossary_episode, mocker, caplog):
    mocker.patch("cast.voxhelm.service.refresh_transcript_corrections", side_effect=RuntimeError("boom"))

    with caplog.at_level(logging.ERROR, logger="cast.voxhelm.service"):
        result = VoxhelmTranscriptService(client=StubClient()).complete_audio_job(
            audio, job_id="job-1", source_url="https://example.com/a.m4a", initial_job_payload=JOB
        )

    assert public_texts(result.transcript)[0][10000] == "John said Gunacorn is fast."
    assert "glossary corrections failed" in caplog.text


# --- command ---------------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    "arguments",
    [
        lambda transcript: ["--transcript", str(transcript.pk)],
        lambda transcript: ["--podcast", "test_podcast"],
        lambda transcript: ["--all"],
    ],
)
def test_command_reapplies(transcript, capsys, arguments):
    call_command("apply_transcript_glossary", *arguments(transcript))

    out = capsys.readouterr().out
    assert f"transcript {transcript.pk}: applied automatic=3" in out
    assert public_texts(transcript)[0][10000] == "Jon said Gunicorn is fast."


@pytest.mark.django_db
def test_command_dry_run(transcript, capsys):
    before = file_bytes(transcript)

    call_command("apply_transcript_glossary", "--all", "--dry-run")

    assert "changed=2" in capsys.readouterr().out
    assert file_bytes(transcript) == before


@pytest.mark.django_db
def test_command_reports_failures(transcript, mocker, capsys):
    mocker.patch(
        "cast.management.commands.apply_transcript_glossary.refresh_transcript_corrections",
        side_effect=RuntimeError("boom"),
    )
    with pytest.raises(CommandError):
        call_command("apply_transcript_glossary", "--all")
    assert "failed: boom" in capsys.readouterr().err


# --- privacy ---------------------------------------------------------------------------------


@pytest.mark.django_db
def test_sidecar_is_private_and_public_output_is_corrected(transcript, glossary_episode, api_client):
    refresh_transcript_corrections(transcript)
    assert "corrections" not in Transcript.admin_form_fields

    url = reverse("cast:api:audio_podlove_detail", kwargs={"pk": transcript.audio_id})
    response = api_client.get(url, format="json")

    content = response.content.decode()
    assert "Jon said Gunicorn is fast." in content
    assert "raw_text" not in content
    assert "Gunacorn" not in content


def test_edge_cases_of_pure_helpers():
    assert webvtt.set_texts_in_content("WEBVTT\n", {1: "x"}) == ("WEBVTT\n", 0)
    assert phrase_spans("a -- b", "--") == []
    assert phrase_spans("John's", "john") == [(0, 4)]


@pytest.mark.django_db
def test_failed_write_keeps_the_previous_files(transcript, mocker):
    before = file_bytes(transcript)
    mocker.patch.object(corrections.StagedFileReplacementGroup, "save_model", side_effect=RuntimeError("no db"))

    with pytest.raises(RuntimeError):
        refresh_transcript_corrections(transcript)

    assert file_bytes(transcript) == before


# --- review fixes: durable editor state, priority, queued episode, prefixes ------------------


@pytest.mark.django_db
def test_rejection_survives_a_variant_removed_and_restored(transcript, jon):
    refresh_transcript_corrections(transcript)
    reject_automatic_replacement(transcript, start_ms=10000, start=0, end=4, to="Jon")

    jon.transcript_variants = ""
    jon.save()
    refresh_transcript_corrections(transcript)
    jon.transcript_variants = "John => Jon"
    jon.save()
    refresh_transcript_corrections(transcript)

    assert public_texts(transcript)[0][10000] == "John said Gunicorn is fast."
    first = transcript.corrections_data["segments"][0]["replacements"][0]
    assert (first["from"], first["to"], first["state"]) == ("John", "Jon", STATE_REJECTED)


@pytest.mark.django_db
def test_approved_occurrence_survives_its_target_leaving_the_glossary(transcript, glossary_episode):
    refresh_transcript_corrections(transcript)
    proposal = next(item for item in transcript.corrections_data["proposals"] if item["to"] == "Buttondown")
    position = {key: proposal[key] for key in ("start_ms", "start", "end", "to")}
    decide_correction_occurrence(transcript, **position, action=STATE_APPROVED)

    glossary_episode.body = json.dumps([{"type": "overview", "value": []}])
    glossary_episode.save_revision()
    refresh_transcript_corrections(transcript)

    assert public_texts(transcript)[0][12500] == "We use Buttondown for mail."
    kept = [item for item in transcript.corrections_data["proposals"] if item["to"] == "Buttondown"]
    assert [item["state"] for item in kept] == [STATE_APPROVED]


@pytest.mark.django_db
def test_approved_decision_wins_over_a_later_automatic_variant(transcript, podcast):
    refresh_transcript_corrections(transcript)
    decide_correction_group(transcript, "Buttondown", STATE_APPROVED)

    TranscriptGlossaryTerm.objects.create(podcast=podcast, term="Button Downstream", variants="Button Down")
    refresh_transcript_corrections(transcript)

    assert public_texts(transcript)[0][12500] == "We use Buttondown for mail."
    replacements = transcript.corrections_data["segments"][1]["replacements"]
    assert [(item["to"], item["state"]) for item in replacements] == [("Buttondown", STATE_APPROVED)]


@pytest.mark.django_db
def test_rejecting_one_occurrence_of_an_approved_decision(audio, glossary_episode):
    transcript = make_transcript(audio, texts=[(1000, "Ask Button Down."), (2000, "Button Down again.")])
    decide_correction_group(transcript, "Buttondown", STATE_APPROVED, originals=["Button Down"])

    reject_automatic_replacement(transcript, start_ms=2000, start=0, end=11, to="Buttondown")
    refresh_transcript_corrections(transcript)

    assert public_texts(transcript)[0] == {1000: "Ask Buttondown.", 2000: "Button Down again."}


@pytest.mark.django_db
def test_queued_completion_uses_the_requested_episode(audio, glossary_episode, podcast, mocker):
    from cast.models import TranscriptGeneration
    from cast.voxhelm_tasks import complete_transcript_generation

    EpisodeFactory(owner=podcast.owner, parent=podcast, title="Other", slug="other", podcast_audio=audio)
    generation = TranscriptGeneration.objects.create(
        audio=audio, task_ref="t", voxhelm_job_id="job-1", source_url="https://example.com/a.m4a"
    )
    service = VoxhelmTranscriptService(client=StubClient())
    service.client.wait_for_job = lambda job_id: JOB
    mocker.patch("cast.voxhelm_tasks.VoxhelmTranscriptService", return_value=service)

    complete_transcript_generation.call(generation.pk, episode_id=glossary_episode.pk)

    transcript = Transcript.objects.get(audio=audio)
    assert transcript.corrections_data["episode_id"] == glossary_episode.pk
    assert public_texts(transcript)[0][10000] == "Jon said Gunicorn is fast."


@pytest.mark.django_db
def test_enqueue_passes_the_episode_to_the_completion_task(audio, glossary_episode, site, mocker):
    from types import SimpleNamespace

    from cast.voxhelm import TranscriptSubmission, enqueue_audio_transcript_generation

    service = mocker.Mock()
    service.submit_for_audio.return_value = TranscriptSubmission(
        job_id="job-1", source_url="https://example.com/a.m4a", task_ref="t", job_payload={}
    )
    mocker.patch("cast.voxhelm.service.VoxhelmTranscriptService", return_value=service)
    enqueue = mocker.Mock(return_value=SimpleNamespace(id="task-1"))
    mocker.patch("cast.voxhelm_tasks.complete_transcript_generation", new=SimpleNamespace(enqueue=enqueue))

    enqueue_audio_transcript_generation(audio=audio, request_or_site=site, episode=glossary_episode)

    enqueue.assert_called_once_with(mocker.ANY, episode_id=glossary_episode.pk)


def test_set_cue_text_keeps_a_speaker_prefix_inside_a_voice_tag():
    lines = ["<v Jon Gould>Speaker 1: John said.</v>\n"]
    assert webvtt.set_cue_text(lines, "Jon said.") == ["<v Jon Gould>Speaker 1: Jon said.</v>\n"]


@pytest.mark.django_db
def test_speaker_prefix_cues_give_the_same_files_in_both_orders(audio, glossary_episode):
    texts = [(10000, "John said."), (12500, "Hi.")]
    vtt = "WEBVTT\n\n00:00:10.000 --> 00:00:12.500\nSpeaker 1: John said.\n\n00:00:12.500 --> 00:00:13.500\nSpeaker 2: Hi.\n"
    results = []
    for corrections_first in (True, False):
        transcript = make_transcript(audio, texts=texts, vtt=vtt, speakers=SPEAKERS)
        steps = [refresh_transcript_corrections, lambda t: t.apply_known_speaker_suggestions(smooth=False)]
        for step in steps if corrections_first else reversed(steps):
            transcript.refresh_from_db()
            step(transcript)
        results.append(file_bytes(transcript)["vtt"])
        transcript.delete()
    assert results[0] == results[1]
    assert "<v Jon Gould>Speaker 1: Jon said.\n" in results[0].decode()


@pytest.mark.django_db
def test_rejected_occurrence_is_listed_once_after_refresh(transcript):
    refresh_transcript_corrections(transcript)
    proposal = next(item for item in transcript.corrections_data["proposals"] if item["to"] == "Buttondown")
    position = {key: proposal[key] for key in ("start_ms", "start", "end", "to")}
    decide_correction_occurrence(transcript, **position, action=STATE_REJECTED)

    refresh_transcript_corrections(transcript)

    kept = [item for item in transcript.corrections_data["proposals"] if item["to"] == "Buttondown"]
    assert [item["state"] for item in kept] == [STATE_REJECTED]


@pytest.mark.django_db
def test_approved_original_skips_text_that_already_spells_the_target(audio, glossary_episode):
    transcript = make_transcript(audio, texts=[(1000, "A tool and a Tool.")])

    result = decide_correction_group(transcript, "Tool", STATE_APPROVED, originals=["tool"])

    assert result.approved == 1
    assert public_texts(transcript)[0] == {1000: "A Tool and a Tool."}


@pytest.mark.django_db
def test_add_original_reports_invalid_contributor_variant(transcript, jon):
    with pytest.raises(corrections.GlossaryAddError) as error:
        add_original_to_glossary(transcript, "Jon", "Jon")
    assert "transcript_variants" in error.value.message_dict
    jon.refresh_from_db()
    assert jon.transcript_variants == "John => Jon"


@pytest.mark.django_db
def test_approving_a_group_keeps_occurrences_rejected_one_by_one(audio, glossary_episode):
    transcript = make_transcript(audio, texts=[(1000, "Ask Button Down."), (2000, "Button Down again.")])
    refresh_transcript_corrections(transcript)
    decide_correction_occurrence(transcript, start_ms=2000, start=0, end=11, to="Buttondown", action=STATE_REJECTED)

    decide_correction_group(transcript, "Buttondown", STATE_APPROVED)
    refresh_transcript_corrections(transcript)

    assert public_texts(transcript)[0] == {1000: "Ask Buttondown.", 2000: "Button Down again."}


@pytest.mark.django_db
def test_rejecting_a_group_keeps_occurrences_approved_one_by_one(audio, glossary_episode):
    transcript = make_transcript(audio, texts=[(1000, "Ask Button Down."), (2000, "Button Down again.")])
    refresh_transcript_corrections(transcript)
    decide_correction_occurrence(transcript, start_ms=2000, start=0, end=11, to="Buttondown", action=STATE_APPROVED)

    decide_correction_group(transcript, "Buttondown", STATE_REJECTED)
    refresh_transcript_corrections(transcript)

    assert public_texts(transcript)[0] == {1000: "Ask Button Down.", 2000: "Buttondown again."}
    open_proposals = [item for item in transcript.corrections_data["proposals"] if item["state"] == STATE_OPEN]
    assert not [item for item in open_proposals if item["to"] == "Buttondown"]


@pytest.mark.django_db
def test_corrections_are_current_and_episode_state(transcript, glossary_episode, podcast, audio):
    state = corrections.corrections_episode_state(transcript)
    assert (state.episode, state.needs_choice, state.stale) == (glossary_episode, False, False)
    assert not corrections.corrections_are_current(transcript)

    refresh_transcript_corrections(transcript)
    assert corrections.corrections_are_current(transcript)
    assert corrections.corrections_episode_state(transcript).episode == glossary_episode

    other = EpisodeFactory(owner=podcast.owner, parent=podcast, title="Other", slug="other", podcast_audio=audio)
    glossary_episode.podcast_audio = None
    glossary_episode.save()
    state = corrections.corrections_episode_state(transcript)
    assert (state.episode, state.choices, state.needs_choice, state.stale) == (None, [other], True, True)


@pytest.mark.django_db
def test_episode_state_for_shared_audio(transcript, glossary_episode, podcast, audio):
    EpisodeFactory(owner=podcast.owner, parent=podcast, title="Other", slug="other", podcast_audio=audio)
    assert corrections.corrections_episode_state(transcript).needs_choice

    refresh_transcript_corrections(transcript)

    state = corrections.corrections_episode_state(transcript)
    assert (state.episode, len(state.choices), state.needs_choice, state.stale) == (None, 2, True, False)


# --- review round 2: decisions are data, the latest action wins ------------------------------


def buttondown_position(transcript):
    proposal = next(item for item in transcript.corrections_data["proposals"] if item["to"] == "Buttondown")
    return {key: proposal[key] for key in ("start_ms", "start", "end", "to")}


@pytest.mark.django_db
def test_rejected_group_also_rejects_a_later_automatic_variant(transcript, podcast):
    refresh_transcript_corrections(transcript)
    decide_correction_group(transcript, "Buttondown", STATE_REJECTED)

    TranscriptGlossaryTerm.objects.create(podcast=podcast, term="Buttondown", variants="Button Down")
    result = refresh_transcript_corrections(transcript)

    assert public_texts(transcript)[0][12500] == "We use Button Down for mail."
    replacements = transcript.corrections_data["segments"][1]["replacements"]
    assert [(item["to"], item["state"]) for item in replacements] == [("Buttondown", STATE_REJECTED)]
    assert result.automatic == 3


@pytest.mark.django_db
def test_rejected_occurrence_also_rejects_a_later_automatic_variant(transcript, podcast):
    refresh_transcript_corrections(transcript)
    decide_correction_occurrence(transcript, **buttondown_position(transcript), action=STATE_REJECTED)

    TranscriptGlossaryTerm.objects.create(podcast=podcast, term="Buttondown", variants="Button Down")
    refresh_transcript_corrections(transcript)

    assert public_texts(transcript)[0][12500] == "We use Button Down for mail."


@pytest.mark.django_db
def test_latest_occurrence_action_wins(transcript):
    refresh_transcript_corrections(transcript)
    position = buttondown_position(transcript)

    decide_correction_occurrence(transcript, **position, action=STATE_APPROVED)
    reject_automatic_replacement(transcript, **position)
    assert public_texts(transcript)[0][12500] == "We use Button Down for mail."

    decide_correction_occurrence(transcript, **position, action=STATE_APPROVED)
    assert public_texts(transcript)[0][12500] == "We use Buttondown for mail."
    assert buttondown_position(transcript) == position

    reject_automatic_replacement(transcript, **position)
    refresh_transcript_corrections(transcript)
    assert public_texts(transcript)[0][12500] == "We use Button Down for mail."
    assert len(transcript.corrections_data["occurrence_decisions"]) == 1


@pytest.mark.django_db
def test_rejecting_a_new_target_of_a_rejected_span(transcript, jon):
    refresh_transcript_corrections(transcript)
    reject_automatic_replacement(transcript, start_ms=10000, start=0, end=4, to="Jon")
    jon.transcript_variants = "John => Jonathan"
    jon.save()
    refresh_transcript_corrections(transcript)
    assert public_texts(transcript)[0][10000] == "Jonathan said Gunicorn is fast."

    reject_automatic_replacement(transcript, start_ms=10000, start=0, end=4, to="Jonathan")

    assert public_texts(transcript)[0][10000] == "John said Gunicorn is fast."
    with pytest.raises(LookupError):
        reject_automatic_replacement(transcript, start_ms=10000, start=0, end=4, to="Jonathan")


@pytest.mark.django_db
def test_rejection_does_not_hide_proposals_for_other_targets(audio, glossary_episode, podcast):
    transcript = make_transcript(audio, texts=[(1000, "Gunacorn runs it.")])
    refresh_transcript_corrections(transcript)
    reject_automatic_replacement(transcript, start_ms=1000, start=0, end=8, to="Gunicorn")

    TranscriptGlossaryTerm.objects.filter(podcast=podcast, term="Gunicorn").update(term="Gunacorns", variants="")
    refresh_transcript_corrections(transcript)

    proposals = transcript.corrections_data["proposals"]
    assert [(item["start"], item["to"], item["state"]) for item in proposals] == [(0, "Gunacorns", STATE_OPEN)]


@pytest.mark.django_db
def test_rejected_occurrence_can_be_approved_again_after_it_became_automatic(transcript, podcast):
    refresh_transcript_corrections(transcript)
    position = buttondown_position(transcript)
    decide_correction_occurrence(transcript, **position, action=STATE_REJECTED)
    TranscriptGlossaryTerm.objects.create(podcast=podcast, term="Buttondown", variants="Button Down")
    refresh_transcript_corrections(transcript)
    replacements = transcript.corrections_data["segments"][1]["replacements"]
    assert [(item["to"], item["state"]) for item in replacements] == [("Buttondown", STATE_REJECTED)]

    # A group approval does not override the occurrence decision (by design) ...
    decide_correction_group(transcript, "Buttondown", STATE_APPROVED, originals=["Button Down"])
    assert public_texts(transcript)[0][12500] == "We use Button Down for mail."

    # ... but the occurrence itself can be decided again.
    decide_correction_occurrence(transcript, **position, action=STATE_APPROVED)

    assert public_texts(transcript)[0][12500] == "We use Buttondown for mail."
    replacements = transcript.corrections_data["segments"][1]["replacements"]
    assert [(item["to"], item["state"]) for item in replacements] == [("Buttondown", STATE_APPROVED)]
