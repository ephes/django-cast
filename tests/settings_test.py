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


def installed_apps_for(engine):
    env = os.environ.copy()
    env.pop("CAST_TEST_DB_ENGINE", None)
    if engine:
        env["CAST_TEST_DB_ENGINE"] = engine
    result = subprocess.run(
        [sys.executable, "-c", "import json; from tests import settings; print(json.dumps(settings.INSTALLED_APPS))"],
        check=True,
        capture_output=True,
        env=env,
        text=True,
    )
    return json.loads(result.stdout)


def test_postgres_contrib_app_is_only_installed_for_postgresql():
    assert "django.contrib.postgres" not in installed_apps_for(None)
    assert "django.contrib.postgres" in installed_apps_for("django.db.backends.postgresql")
