import subprocess
import sys

import pytest

from cast.media_probe import MediaProbeOutputTooLarge, media_probe_budget, run_media_probe
from cast.models import Audio, Video


@pytest.mark.parametrize("stream,limit", [("stdout", 1024 * 1024), ("stderr", 64 * 1024)])
@pytest.mark.parametrize("simultaneous", [False, True])
def test_media_probe_rejects_excess_output_and_reaps_child(mocker, stream, limit, simultaneous):
    popen = subprocess.Popen
    children = []

    def launch(*args, **kwargs):
        child = popen(*args, **kwargs)
        children.append(child)
        return child

    mocker.patch("cast.media_probe.subprocess.Popen", side_effect=launch)
    other_stream = "stderr" if stream == "stdout" else "stdout"
    script = "import sys, threading, time\n"
    if simultaneous:
        script += f"threading.Thread(target=sys.{other_stream}.buffer.write, args=(b'x' * 65536,)).start()\n"
    script += f"sys.{stream}.buffer.write(b'x' * {limit + 1})\nsys.{stream}.flush()\ntime.sleep(2)\n"
    with pytest.raises(MediaProbeOutputTooLarge, match=f"{stream} exceeded {limit} bytes"):
        run_media_probe([sys.executable, "-c", script])
    assert len(children) == 1
    assert children[0].returncode not in (None, 0)


def test_media_probe_accepts_full_envelopes_and_separates_streams():
    result = run_media_probe(
        [sys.executable, "-c", "import sys; sys.stderr.write('e' * 65536); sys.stdout.write('o' * 1048576)"],
    )
    assert result.stdout == b"o" * 1048576
    assert result.stderr == b"e" * 65536


@pytest.mark.django_db
def test_chapter_probe_parses_json_with_stderr(mocker):
    script = """import sys
print('diagnostic', file=sys.stderr)
print('{"chapters":[{"start_time":"0.125","tags":{"title":"Synthetic chapter"}}]}')
"""

    def fake_ffprobe(command, **kwargs):
        return run_media_probe([sys.executable, "-c", script], **kwargs)

    mocker.patch("cast.models.audio.run_media_probe", side_effect=fake_ffprobe)
    assert Audio(mp3="synthetic.mp3").get_chaptermark_data_from_file("mp3") == [
        {"start": "0.125", "title": "Synthetic chapter"}
    ]


def test_probe_output_collection_uses_cumulative_deadline():
    with media_probe_budget(0.1), pytest.raises(subprocess.TimeoutExpired):
        run_media_probe([sys.executable, "-c", "import time; time.sleep(5)"], timeout=10)


def test_video_probe_parses_json_with_stderr(mocker):
    script = """import sys
print('diagnostic', file=sys.stderr)
print('{"streams":[{"codec_type":"video","width":1920,"height":1080}]}')
"""
    mocker.patch(
        "cast.models.video.run_media_probe",
        side_effect=lambda command, **kwargs: run_media_probe([sys.executable, "-c", script], **kwargs),
    )
    assert Video._get_video_dimensions("synthetic.mp4") == (1920, 1080)
