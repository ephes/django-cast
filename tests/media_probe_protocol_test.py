"""ffmpeg/ffprobe inputs are restricted to the protocols their source needs."""

import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from cast.media_probe import LOCAL_INPUT_PROTOCOLS, REMOTE_INPUT_PROTOCOLS, input_protocol_args
from cast.models import Audio, Video


def _whitelist(command: list[str], source: str) -> str:
    """Return the protocol allowlist and check it precedes the input."""
    assert command.count("-protocol_whitelist") == 1
    flag = command.index("-protocol_whitelist")
    assert flag < command.index(source)
    return command[flag + 1]


@pytest.mark.parametrize(
    "source,expected",
    [
        ("/srv/media/cast_audio/episode.m4a", "file"),
        (Path("/srv/media/cast_audio/episode.m4a"), "file"),
        ("relative/episode.mp3", "file"),
        ("https://media.example/cast_audio/episode.m4a", "http,https,tcp,tls,httpproxy"),
        ("HTTP://media.example/cast_audio/episode.m4a", "http,https,tcp,tls,httpproxy"),
    ],
)
def test_input_protocol_args_match_source_kind(source, expected):
    assert input_protocol_args(source) == ["-protocol_whitelist", expected]


def test_protocol_sets_do_not_mix_local_and_network_access():
    assert LOCAL_INPUT_PROTOCOLS == "file"
    assert "file" not in REMOTE_INPUT_PROTOCOLS.split(",")


@pytest.mark.parametrize(
    "source,expected",
    [("/srv/media/a.m4a", "file"), ("https://media.example/a.m4a", "http,https,tcp,tls,httpproxy")],
)
def test_audio_duration_probe_uses_protocol_allowlist(mocker, source, expected):
    run = mocker.patch("cast.models.audio.run_media_probe", return_value=SimpleNamespace(stdout=b"1.500000"))
    Audio._get_audio_duration(source)
    assert _whitelist(run.call_args.args[0], source) == expected


@pytest.mark.parametrize(
    "source,expected",
    [("/srv/media/a.mp3", "file"), ("https://media.example/a.mp3", "http,https,tcp,tls,httpproxy")],
)
def test_chaptermark_probe_uses_protocol_allowlist(mocker, audio, source, expected):
    field = SimpleNamespace(url=source, path=source)
    mocker.patch("cast.models.audio.getattr", return_value=field)
    run = mocker.patch("cast.models.audio.run_media_probe", return_value=SimpleNamespace(stdout=b"{}"))
    audio.get_chaptermark_data_from_file("mp3")
    assert _whitelist(run.call_args.args[0], source) == expected


@pytest.mark.parametrize(
    "source,expected",
    [("/srv/media/a.mp4", "file"), ("https://media.example/a.mp4", "http,https,tcp,tls,httpproxy")],
)
def test_video_dimension_probe_uses_protocol_allowlist(mocker, source, expected):
    run = mocker.patch("cast.models.video.run_media_probe", return_value=SimpleNamespace(stdout=b"{}"))
    Video._get_video_dimensions(source)
    assert _whitelist(run.call_args.args[0], source) == expected


@pytest.mark.django_db
@pytest.mark.parametrize(
    "url,path,expected",
    [
        ("/media/a.mp4", "/srv/media/a.mp4", "file"),
        ("https://media.example/a.mp4", "/unused", "http,https,tcp,tls,httpproxy"),
    ],
)
def test_poster_extraction_uses_protocol_allowlist(mocker, url, path, expected):
    commands = []

    def probe(command, **kwargs):
        commands.append(command)
        raise subprocess.CalledProcessError(returncode=1, cmd=command[0])

    mocker.patch("cast.models.video.Video._get_video_dimensions", return_value=(1, 1))
    mocker.patch("cast.models.video.run_media_probe", side_effect=probe)
    video = Video()
    mocker.patch.object(video, "original", SimpleNamespace(url=url, path=path))
    with pytest.raises(subprocess.CalledProcessError):
        video._create_poster()
    source = url if url.startswith("http") else path
    assert commands[0][0] == "ffmpeg"
    assert _whitelist(commands[0], source) == expected


class _CountingListener:
    """Local TCP listener that counts connection attempts."""

    def __init__(self) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.sock.settimeout(0.2)
        self.port = self.sock.getsockname()[1]
        self.connections = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self.sock.accept()
            except OSError:
                continue
            self.connections += 1
            conn.close()

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
        self.sock.close()


@pytest.fixture()
def listener():
    server = _CountingListener()
    try:
        yield server
    finally:
        server.close()


@pytest.fixture()
def local_playlist(tmp_path, listener):
    playlist = tmp_path / "episode.m3u8"
    playlist.write_text(
        "#EXTM3U\n#EXT-X-TARGETDURATION:10\n#EXTINF:10,\n"
        f"http://127.0.0.1:{listener.port}/segment.ts\n#EXT-X-ENDLIST\n"
    )
    return playlist


@pytest.mark.skipif(shutil.which("ffprobe") is None, reason="ffprobe is not installed")
def test_local_media_cannot_make_ffprobe_open_network_urls(local_playlist, listener):
    """A local file that references a URL must not make the probe connect anywhere.

    Current ffmpeg already refuses this through its own defaults; the explicit
    allowlist keeps it that way on older builds and documents the contract.
    """
    with pytest.raises((subprocess.CalledProcessError, ValueError)):
        Audio._get_audio_duration(str(local_playlist))
    with pytest.raises((subprocess.CalledProcessError, ValueError)):
        Video._get_video_dimensions(str(local_playlist))
    assert listener.connections == 0


@pytest.mark.skipif(shutil.which("ffprobe") is None, reason="ffprobe is not installed")
def test_local_media_still_probes_with_file_only_allowlist(audio):
    assert Audio._get_audio_duration(audio.m4a.path).total_seconds() > 0


@pytest.mark.skipif(shutil.which("ffprobe") is None, reason="ffprobe is not installed")
def test_remote_media_can_still_tunnel_https_through_http_proxy(monkeypatch, listener):
    """Storage behind an outbound proxy keeps working: ``httpproxy`` is allowed for URLs."""
    monkeypatch.setenv("http_proxy", f"http://127.0.0.1:{listener.port}")
    monkeypatch.delenv("no_proxy", raising=False)
    monkeypatch.delenv("NO_PROXY", raising=False)
    with pytest.raises((subprocess.CalledProcessError, ValueError)):
        Audio._get_audio_duration("https://media.invalid/episode.m4a")
    deadline = time.monotonic() + 2
    while listener.connections == 0 and time.monotonic() < deadline:
        time.sleep(0.05)
    assert listener.connections >= 1
