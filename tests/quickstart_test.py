import ast
import os
import stat
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

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


@pytest.mark.parametrize(
    "helper,arguments",
    [
        (quickstart.run_migrations, ["migrate"]),
        (quickstart.collect_static_files, ["collectstatic", "--noinput"]),
    ],
)
@pytest.mark.parametrize("fails", [False, True])
def test_management_helpers_use_checked_current_interpreter(tmp_path, monkeypatch, helper, arguments, fails):
    project = tmp_path / "project with spaces"
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        if fails and kwargs.get("check"):
            raise subprocess.CalledProcessError(7, argv)
        return subprocess.CompletedProcess(argv, 7 if fails else 0)

    monkeypatch.setattr(quickstart.subprocess, "run", run)
    if fails:
        with pytest.raises(subprocess.CalledProcessError) as error:
            helper(project)
        assert error.value.returncode == 7
    else:
        helper(project)
    assert calls == [([sys.executable, str(project / "manage.py"), *arguments], {"check": True})]


@pytest.mark.parametrize("automatic", [False, True])
@pytest.mark.parametrize("fails", [False, True])
def test_superuser_modes_dispatch_and_propagate_failure(tmp_path, monkeypatch, capsys, automatic, fails):
    project = tmp_path / "project with spaces"
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        if fails and kwargs.get("check"):
            raise subprocess.CalledProcessError(9, argv)
        return subprocess.CompletedProcess(argv, 9 if fails else 0)

    monkeypatch.setattr(quickstart.subprocess, "run", run)
    if fails:
        with pytest.raises(subprocess.CalledProcessError) as error:
            quickstart.create_superuser(project, auto_create=automatic)
        assert error.value.returncode == 9
    else:
        quickstart.create_superuser(project, auto_create=automatic)
    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert kwargs == {"check": True}
    assert argv[:2] == [sys.executable, str(project / "manage.py")]
    guidance = capsys.readouterr().out
    if not automatic:
        assert argv[2:] == ["createsuperuser"]
        assert "access the Wagtail admin at /cms/" in guidance
        assert "Username: user" not in guidance
        return
    assert argv[2:4] == ["shell", "-c"]
    assert len(argv) == 5
    assert "Username: user" in guidance
    assert "Password: password" in guidance
    assert "Email: user@example.com" in guidance
    # Inspect the actual emitted snippet without executing it or creating users.
    tree = ast.parse(argv[4])
    guard = next(node for node in tree.body if isinstance(node, ast.If))
    assert isinstance(guard.test, ast.UnaryOp) and isinstance(guard.test.op, ast.Not)
    exists = guard.test.operand
    assert isinstance(exists, ast.Call) and exists.func.attr == "exists"
    lookup = exists.func.value
    assert lookup.func.attr == "filter"
    assert [(kw.arg, ast.literal_eval(kw.value)) for kw in lookup.keywords] == [("username", "user")]
    creations = [
        node
        for statement in guard.body
        for node in ast.walk(statement)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "create_superuser"
    ]
    assert len(creations) == 1
    assert [ast.literal_eval(argument) for argument in creations[0].args] == ["user", "user@example.com", "password"]
    assert not any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "create_superuser"
        for statement in guard.orelse
        for node in ast.walk(statement)
    )


@pytest.fixture
def quickstart_main_environment(tmp_path, monkeypatch):
    target = tmp_path / "parent with spaces"
    target.mkdir()
    monkeypatch.chdir(target)
    monkeypatch.setattr(sys, "argv", ["django-cast-quickstart", "synthetic_site"])
    events = []
    project = target / "synthetic_site"

    def migration(path):
        assert path == project
        assert (path / "manage.py").exists()
        assert (path / "synthetic_site" / "settings.py").exists()
        assert Path.cwd() == target
        events.append(("migrate", path))

    def collect(path):
        assert Path.cwd() == target
        events.append(("collect", path))

    def superuser(path, *, auto_create):
        events.append(("superuser", path, auto_create))

    def browser(url, *, delay):
        assert Path.cwd() == project
        events.append(("browser", url, delay))

    def server(argv):
        assert Path.cwd() == project
        events.append(("server", argv))
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(quickstart, "run_migrations", migration)
    monkeypatch.setattr(quickstart, "collect_static_files", collect)
    monkeypatch.setattr(quickstart, "create_superuser", superuser)
    monkeypatch.setattr(quickstart, "open_browser_delayed", browser)
    monkeypatch.setattr(quickstart.subprocess, "run", server)
    return target, project, events


@pytest.mark.parametrize(
    "option,automatic", [(None, True), ("--interactive-superuser", False), ("--no-superuser", None)]
)
def test_main_orders_setup_and_server(quickstart_main_environment, monkeypatch, option, automatic):
    target, project, events = quickstart_main_environment
    if option:
        monkeypatch.setattr(sys, "argv", ["django-cast-quickstart", "synthetic_site", option])
    quickstart.main()
    expected = [("migrate", project), ("collect", project)]
    if automatic is not None:
        expected.append(("superuser", project, automatic))
    expected += [
        ("browser", "http://localhost:8000/cms/", 5.0),
        ("server", [sys.executable, str(project / "manage.py"), "runserver"]),
    ]
    assert events == expected
    assert Path.cwd() == project
    assert (project / "synthetic_site" / "urls.py").is_file()
    assert project.parent == target


@pytest.mark.parametrize("failure", ["run_migrations", "collect_static_files", "create_superuser"])
def test_main_cleans_only_owned_project_on_setup_failure(quickstart_main_environment, monkeypatch, failure):
    target, project, events = quickstart_main_environment
    sentinel = target / "keep.txt"
    sentinel.write_text("synthetic sentinel")

    def fail(*args, **kwargs):
        events.append(("failed", failure))
        raise subprocess.CalledProcessError(7, ["synthetic-setup"])

    monkeypatch.setattr(quickstart, failure, fail)
    with pytest.raises(SystemExit) as error:
        quickstart.main()
    assert error.value.code == 1
    expected = [("migrate", project), ("collect", project)][
        : ["run_migrations", "collect_static_files", "create_superuser"].index(failure)
    ]
    assert events == [*expected, ("failed", failure)]
    assert not project.exists()
    assert sentinel.read_text() == "synthetic sentinel"
    assert Path.cwd() == target


@pytest.mark.parametrize("refusal", ["exists", "conflicting-options", "invalid-name"])
def test_main_refuses_before_setup(quickstart_main_environment, monkeypatch, refusal):
    target, project, events = quickstart_main_environment
    if refusal == "exists":
        project.mkdir()
        (project / "keep.txt").write_text("synthetic sentinel")
    elif refusal == "conflicting-options":
        monkeypatch.setattr(
            sys, "argv", ["django-cast-quickstart", "synthetic_site", "--interactive-superuser", "--no-superuser"]
        )
    else:
        monkeypatch.setattr(sys, "argv", ["django-cast-quickstart", "invalid-name"])
    with pytest.raises(SystemExit) as error:
        quickstart.main()
    assert error.value.code == (2 if refusal == "conflicting-options" else 1)
    assert events == []
    assert Path.cwd() == target
    if refusal == "exists":
        assert (project / "keep.txt").read_text() == "synthetic sentinel"
    else:
        assert list(target.iterdir()) == []
