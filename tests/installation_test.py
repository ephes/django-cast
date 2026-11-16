import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path


def test_manual_installation_settings_resolve_wagtail_image_models(tmp_path):
    """Execute the manual's settings, independently of tests.settings/quickstart."""
    repo_root = Path(__file__).resolve().parents[1]
    installation = (repo_root / "docs" / "installation.rst").read_text()
    documented_settings = []
    for heading in ("Settings\n--------", "Required Settings\n-----------------"):
        section = installation.split(f"\n{heading}\n", 1)[1]
        code = re.search(r"\.\. code-block:: python\n\n((?:[ \t]+[^\n]*\n|\n)+)", section)
        assert code is not None
        documented_settings.append(textwrap.dedent(code[1]))

    # Ordinary project boilerplate; Cast/Wagtail settings come from the manual.
    (tmp_path / "installation_settings.py").write_text(
        textwrap.dedent("""\
            from pathlib import Path
            BASE_DIR = Path(__file__).resolve().parent
            SECRET_KEY = "synthetic-installation-test"
            DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}
            ROOT_URLCONF = "installation_urls"
            STATIC_URL = "/static/"
            STATIC_ROOT = BASE_DIR / "static"
            DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
            TEMPLATES = [{
                "BACKEND": "django.template.backends.django.DjangoTemplates",
                "APP_DIRS": True,
                "OPTIONS": {"context_processors": [
                    "django.template.context_processors.request",
                    "django.contrib.auth.context_processors.auth",
                    "django.contrib.messages.context_processors.messages",
                ]},
            }]
            """)
        + "\n".join(documented_settings)
    )
    (tmp_path / "installation_urls.py").write_text(
        "from django.urls import include, path\n"
        "from cast import cast_and_wagtail_urls\n"
        'urlpatterns = [path("", include(cast_and_wagtail_urls))]\n'
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            textwrap.dedent("""\
                import django
                django.setup()
                from django.apps import apps
                from django.core.management import call_command
                from wagtail.images import get_image_model
                image = get_image_model()
                assert apps.get_model(image._meta.label) is image
                assert image._meta.label == "wagtailimages.Image"
                rendition = image.get_rendition_model()
                assert apps.get_model(rendition._meta.label) is rendition
                assert rendition._meta.get_field("image").remote_field.model is image
                call_command("check", databases=["default"])
                """),
        ],
        cwd=tmp_path,
        env={
            **os.environ,
            "DJANGO_SETTINGS_MODULE": "installation_settings",
            "PYTHONPATH": os.pathsep.join([str(tmp_path), str(repo_root / "src")]),
        },
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
