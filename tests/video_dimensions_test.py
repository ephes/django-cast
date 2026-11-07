"""Synthetic structured probe output, independent of codecs and capture devices."""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from cast.models import Video, get_video_dimensions


def dimensions(streams):
    return get_video_dimensions(json.dumps({"streams": streams}).splitlines())


@pytest.mark.parametrize("codec", ["h264", "hevc", "vp9", "av1"])
def test_dimensions_are_codec_independent(codec):
    assert dimensions([{"codec_type": "video", "codec_name": codec, "width": 1920, "height": 1080}]) == (1920, 1080)


@pytest.mark.parametrize(
    "rotation,expected",
    [
        (0, (1920, 1080)),
        (90, (1080, 1920)),
        (-90, (1080, 1920)),
        (180, (1920, 1080)),
        (-180, (1920, 1080)),
        (270, (1080, 1920)),
        (-270, (1080, 1920)),
    ],
)
def test_only_quarter_turns_swap_the_selected_stream(rotation, expected):
    assert (
        dimensions(
            [
                {"codec_type": "audio", "side_data_list": [{"rotation": 90}]},
                {"codec_type": "video", "width": 1920, "height": 1080, "side_data_list": [{"rotation": rotation}]},
                {"codec_type": "video", "width": 640, "height": 480, "side_data_list": [{"rotation": 90}]},
            ]
        )
        == expected
    )


def test_encoded_portrait_dimensions_are_not_rotated_by_aspect_ratio_metadata():
    assert dimensions(
        [
            {
                "codec_type": "video",
                "width": 1080,
                "height": 1920,
                "display_aspect_ratio": "9:16",
                "side_data_list": [{"rotation": 0}],
            }
        ]
    ) == (1080, 1920)


@pytest.mark.parametrize(
    "data",
    [
        None,
        [],
        {"streams": None},
        {"streams": []},
        {"streams": [42]},
        {"streams": [{"codec_type": "audio"}]},
        {"streams": [{"codec_type": "video"}]},
        {"streams": [{"codec_type": "video", "width": "1920", "height": 1080}]},
        {"streams": [{"codec_type": "video", "width": 1920, "height": False}]},
        {"streams": [{"codec_type": "video", "width": 0, "height": 1080}]},
        {"streams": [{"codec_type": "video", "width": 1920, "height": -1}]},
    ],
)
def test_malformed_or_missing_dimensions_are_unavailable(data):
    assert get_video_dimensions([json.dumps(data)]) == (None, None)


def test_invalid_json_is_unavailable():
    assert get_video_dimensions(["not json"]) == (None, None)


@pytest.mark.parametrize("rotation", [None, {}, "bad", 10**400, "Infinity", "NaN"])
def test_bad_rotation_metadata_keeps_encoded_dimensions(rotation):
    assert dimensions(
        [
            {
                "codec_type": "video",
                "width": 1920,
                "height": 1080,
                "tags": {"rotate": rotation},
                "side_data_list": [None, {}],
            }
        ]
    ) == (1920, 1080)


def test_legacy_rotation_tag_and_selected_side_data_precedence():
    stream = {"codec_type": "video", "width": 1920, "height": 1080, "tags": {"rotate": "90"}}
    assert dimensions([stream]) == (1080, 1920)
    stream["side_data_list"] = [{"rotation": 0}]
    assert dimensions([stream]) == (1920, 1080)


@pytest.mark.django_db
def test_poster_generation_uses_selected_structured_dimensions_and_cleans_tempfile(mocker):
    commands = []

    def probe(command, **kwargs):
        commands.append((command, kwargs))
        if command[0] == "ffprobe":
            return SimpleNamespace(
                stdout=json.dumps(
                    {"streams": [{"codec_type": "video", "codec_name": "av1", "width": 1920, "height": 1080}]}
                ).encode()
            )
        Image.new("RGB", (1, 1)).save(command[-1], "JPEG")
        return SimpleNamespace(stdout=b"")

    mocker.patch("cast.models.video.run_media_probe", side_effect=probe)
    video = Video(title="Synthetic")
    mocker.patch.object(video, "original", SimpleNamespace(url="https://media.example/synthetic.mp4"))
    video._create_poster()
    assert video.poster and video.poster.storage.exists(video.poster.name)
    assert commands[0][0][commands[0][0].index("-select_streams") + 1] == "V:0"
    assert commands[0][0][commands[0][0].index("-of") + 1] == "json"
    assert commands[0][1]["timeout"] == commands[1][1]["timeout"] == 30
    assert commands[1][0][commands[1][0].index("-s") + 1] == "1920x1080"
    assert not Path(commands[1][0][-1]).exists()


@pytest.mark.parametrize(
    "ratio,expected",
    [
        ("81:256", (608, 1080)),
        ("4:3", (2560, 1080)),
        ("1:1", (1920, 1080)),
        ("0:1", (1920, 1080)),
        ("-1:1", (1920, 1080)),
        ("1:0", (1920, 1080)),
        ("N/A", (1920, 1080)),
    ],
)
def test_sample_aspect_shapes_display_dimensions_separately_from_rotation(ratio, expected):
    stream = {"codec_type": "video", "width": 1920, "height": 1080, "sample_aspect_ratio": ratio}
    assert dimensions([stream]) == expected
    stream["side_data_list"] = [{"rotation": 90}]
    assert dimensions([stream]) == tuple(reversed(expected))


def test_probe_nonfatal_stderr_does_not_contaminate_json(mocker):
    diagnostic = b"synthetic nonfatal probe diagnostic\n"
    payload = json.dumps({"streams": [{"codec_type": "video", "width": 1920, "height": 1080}]}).encode()

    def probe(command, **kwargs):
        stdout = diagnostic + payload if kwargs["stderr"] == subprocess.STDOUT else payload
        return SimpleNamespace(stdout=stdout, stderr=diagnostic)

    mocked = mocker.patch("cast.models.video.run_media_probe", side_effect=probe)
    assert Video._get_video_dimensions("synthetic.mp4") == (1920, 1080)
    assert mocked.call_args.kwargs["stderr"] == subprocess.PIPE
