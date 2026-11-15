from decimal import Decimal

import pytest

from cast.transcripts import speaker_samples, voice_references


def segment(label, start, end, **extra):
    return {
        "speaker": label,
        "start_ms": start * 1000,
        "end_ms": end * 1000,
        "text": "Synthetic useful speaker example with enough words.",
        **extra,
    }


@pytest.mark.parametrize("reverse", [False, True])
def test_candidates_subtract_all_other_speakers(reverse):
    records = [segment("A", 0, 30), segment("B", 10, 20), segment("C", 12, 15), segment("D", 30, 40)]
    candidates = voice_references.get_candidates({"transcripts": records[::-1] if reverse else records})
    assert [(c.start_seconds, c.end_seconds) for c in candidates if c.speaker_label == "A"] == [
        (Decimal(0), Decimal(10)),
        (Decimal(20), Decimal(30)),
    ]
    for candidate in candidates:
        for record in records:
            if candidate.speaker_label != record["speaker"]:
                assert (
                    candidate.end_seconds <= record["start_ms"] / 1000
                    or candidate.start_seconds >= record["end_ms"] / 1000
                )


def test_candidates_exclude_speech_without_text_and_ambiguous_labels():
    records = [segment("A", 0, 30), segment("B", 8, 22, text=""), segment("A", 22, 30, voice="C")]
    candidates = voice_references.get_candidates({"transcripts": records})
    assert [(c.start_seconds, c.end_seconds) for c in candidates] == [(Decimal(0), Decimal(8))]


@pytest.mark.parametrize("count", [100, 1000])
def test_sample_grouping_visits_candidates_once(count):
    class CountedList(list):
        visits = 0

        def __iter__(self):
            for item in super().__iter__():
                self.visits += 1
                yield item

    candidates = CountedList(
        speaker_samples.get_podlove_candidates(
            {"transcripts": [segment(f"S{i}", i, i + 1) for i in range(count)]},
            max_chars=180,
            min_chars=35,
            min_words=4,
        )
    )
    result = speaker_samples.select_samples(podlove_candidates=candidates, dote_candidates=[], limit=3)
    assert len(result) == count
    assert candidates.visits <= count * 2
    assert result["S0"][0].text == candidates[0].text


def test_solo_windows_inside_a_run_gap_do_not_invent_source_segments():
    records = [
        segment("A", 0, 10),
        segment("A", 12, 20),
        segment("B", 10, 10.5),
        segment("A", 10.5, 11, text=""),
        segment("B", 11, 12),
    ]
    candidates = voice_references.get_candidates({"transcripts": records})
    assert [(c.start_seconds, c.end_seconds) for c in candidates if c.speaker_label == "A"] == [
        (Decimal(0), Decimal(10)),
        (Decimal(12), Decimal(20)),
    ]
