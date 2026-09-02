import json
import os
import subprocess
import sys


def test_test_media_roots_honor_environment_overrides(tmp_path):
    media_root = tmp_path / "media"
    private_media_root = tmp_path / "private-media"
    env = os.environ.copy()
    env["CAST_TEST_MEDIA_ROOT"] = str(media_root)
    env["CAST_TEST_PRIVATE_MEDIA_ROOT"] = str(private_media_root)

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json; from tests import settings; "
                "print(json.dumps([settings.MEDIA_ROOT, settings.CAST_PRIVATE_MEDIA_ROOT]))"
            ),
        ],
        check=True,
        capture_output=True,
        env=env,
        text=True,
    )

    assert json.loads(result.stdout) == [str(media_root), str(private_media_root)]
