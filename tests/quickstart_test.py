import os
import stat
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

from cast import quickstart


QUICKSTART_TEMPLATE_FILES = {
    "base.html.template",
    "manage.py.template",
    "settings.py.template",
    "urls.py.template",
    "wsgi.py.template",
}


def generate_quickstart_project(tmp_path: Path, project_name: str = "mysite") -> Path:
    quickstart.create_project_structure(project_name, tmp_path)
    quickstart.create_settings_file(project_name, tmp_path)
    quickstart.create_urls_file(project_name, tmp_path)
    quickstart.create_wsgi_file(project_name, tmp_path)
    quickstart.create_manage_py(project_name, tmp_path)
    quickstart.create_base_template(project_name, tmp_path)
    return tmp_path / project_name


def test_quickstart_templates_are_packaged():
    assert quickstart.render_quickstart_template(
        "settings.py.template", project_name="mysite", secret_key="known-secret"
    ).startswith('"""\nDjango settings for mysite project.')


def test_quickstart_templates_are_in_built_distributions(tmp_path):
    dist_dir = tmp_path / "dist"
    result = subprocess.run(
        ["uv", "build", "--sdist", "--wheel", "--out-dir", str(dist_dir)],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout

    wheel = next(dist_dir.glob("*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        wheel_templates = {
            Path(name).name
            for name in archive.namelist()
            if name.startswith("cast/quickstart_templates/") and Path(name).name in QUICKSTART_TEMPLATE_FILES
        }
    assert wheel_templates == QUICKSTART_TEMPLATE_FILES

    sdist = next(dist_dir.glob("*.tar.gz"))
    with tarfile.open(sdist) as archive:
        sdist_templates = {
            Path(name).name
            for name in archive.getnames()
            if "/src/cast/quickstart_templates/" in name and Path(name).name in QUICKSTART_TEMPLATE_FILES
        }
    assert sdist_templates == QUICKSTART_TEMPLATE_FILES


def test_quickstart_generates_project_files_from_packaged_templates(tmp_path, monkeypatch):
    monkeypatch.setattr(quickstart.secrets, "token_urlsafe", lambda length: f"secret-{length}")

    project_dir = generate_quickstart_project(tmp_path)

    settings_content = (project_dir / "mysite" / "settings.py").read_text()
    assert 'SECRET_KEY = "secret-50"' in settings_content
    assert 'ROOT_URLCONF = "mysite.urls"' in settings_content
    assert 'WSGI_APPLICATION = "mysite.wsgi.application"' in settings_content
    assert 'WAGTAIL_SITE_NAME = "mysite"' in settings_content
    assert "from cast import CAST_APPS, CAST_MIDDLEWARE" in settings_content

    urls_content = (project_dir / "mysite" / "urls.py").read_text()
    assert 'path("cast/", include("cast.urls", namespace="cast"))' in urls_content
    assert 'path("", include(wagtail_urls))' in urls_content

    wsgi_content = (project_dir / "mysite" / "wsgi.py").read_text()
    assert 'os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mysite.settings")' in wsgi_content

    manage_py = project_dir / "manage.py"
    manage_content = manage_py.read_text()
    assert manage_content.startswith("#!/usr/bin/env python")
    assert 'os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mysite.settings")' in manage_content
    assert manage_py.stat().st_mode & stat.S_IXUSR

    base_template = (project_dir / "mysite" / "templates" / "base.html").read_text()
    assert "{% block title %}{% endblock %}" in base_template
    assert "{{ settings.WAGTAIL_SITE_NAME }}" in base_template


def test_generated_quickstart_project_passes_django_check(tmp_path, monkeypatch):
    monkeypatch.setattr(quickstart.secrets, "token_urlsafe", lambda length: f"secret-{length}")
    project_dir = generate_quickstart_project(tmp_path)
    repo_src = Path(__file__).resolve().parents[1] / "src"
    existing_pythonpath = os.environ.get("PYTHONPATH")
    pythonpath_parts = [str(repo_src)]
    if existing_pythonpath:
        pythonpath_parts.append(existing_pythonpath)
    subprocess_env = {**os.environ, "PYTHONPATH": os.pathsep.join(pythonpath_parts)}
    subprocess_env.pop("DJANGO_SETTINGS_MODULE", None)

    result = subprocess.run(
        [sys.executable, "manage.py", "check"],
        cwd=project_dir,
        env=subprocess_env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stderr + result.stdout
