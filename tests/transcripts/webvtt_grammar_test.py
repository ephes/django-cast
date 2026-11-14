"""Only actual cue payloads participate in transcript transforms."""

import pytest

from cast.transcripts import dote, webvtt


@pytest.mark.parametrize(
    "timestamp", ["00:60.000", "60:00.000", "00:99:99.000", "1" * 5000 + ":00:00.000", "٠٠:٠١.000"]
)
def test_invalid_timestamps_do_not_match_corrections(timestamp):
    assert webvtt.webvtt_timestamp_to_ms(timestamp) is None
    content = f"WEBVTT\n\n{timestamp} --> 02:00:00.000\nold\n"
    assert webvtt.set_texts_in_content(content, {6039000: "wrong"}) == (content, 0)


@pytest.mark.parametrize(
    "timestamp,expected", [("59:59.999", 3599999), ("123:59:59.05", 446399050), ("01:02:03.5", 3723500)]
)
def test_timestamp_boundaries_and_dote_equivalence(timestamp, expected):
    assert webvtt.webvtt_timestamp_to_ms(timestamp) == expected
    if timestamp.count(":") == 2:
        assert dote.dote_timestamp_to_ms(timestamp.replace(".", ",")) == expected


@pytest.mark.parametrize("ending", ["\n", "\r\n"])
@pytest.mark.parametrize(
    "block",
    [
        "NOTE arrow --> text",
        "NOTE",
        "NOTE\tcomment",
        "STYLE",
        "REGION",
        "not timing --> text",
        "00:01.000 --> garbage",
        "00:99.000 --> 01:40.000",
    ],
)
def test_non_cue_blocks_remain_identical_for_all_transforms(block, ending):
    prefix = (
        "WEBVTT\n\n" + block + "\n00:01.000 --> 00:02.000\n<v Hidden>comment</v>\nSpeaker 9: private\n\n"
    ).replace("\n", ending)
    cue = "identifier\n00:03.000 --> 00:04.000 align:start\n<v Real>spoken</v>\n".replace("\n", ending)
    content = prefix + cue
    assert webvtt.get_speaker_labels(content) == {"Real"}
    renamed, changed = webvtt.rewrite_speakers(content, {"Hidden": "Wrong", "Speaker 9": "Wrong", "Real": "New"})
    assert changed and renamed == prefix + cue.replace("Real", "New")
    assert webvtt.sanitize_webvtt_content(content, set()) == prefix + cue.replace("<v Real>", "").replace("</v>", "")
    applied, count, _ = webvtt.apply_suggestions_to_content(content, {1000: "Wrong", 3000: "New"})
    assert count == 1 and applied == prefix + cue.replace("Real", "New")
    cleared, count, _ = webvtt.clear_suggestions_from_content(content, {1000, 3000})
    assert count == 1 and cleared == prefix + cue.replace("<v Real>", "").replace("</v>", "")
    corrected, count = webvtt.set_texts_in_content(content, {1000: "Wrong", 3000: "new text"})
    assert count == 1 and corrected == prefix + cue.replace("spoken", "new text")
