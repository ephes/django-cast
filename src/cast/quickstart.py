#!/usr/bin/env python
"""
Django-Cast quickstart command.

Creates a new Django project with django-cast pre-configured.
"""

import argparse
import importlib.util
import keyword
import os
import secrets
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from importlib.resources import files
from pathlib import Path
from string import Template
from textwrap import dedent
from unicodedata import normalize

QUICKSTART_TEMPLATE_PACKAGE = "cast"
QUICKSTART_TEMPLATE_DIR = "quickstart_templates"
# Imported by the generated settings/URLs or by Django itself.
RESERVED_PROJECT_NAMES = {"django", "cast", "wagtail", "rest_framework"}


def render_quickstart_template(template_name: str, **context: str) -> str:
    """Render one packaged quickstart template."""
    template_path = files(QUICKSTART_TEMPLATE_PACKAGE).joinpath(QUICKSTART_TEMPLATE_DIR).joinpath(template_name)
    template = Template(template_path.read_text(encoding="utf-8"))
    return template.substitute(context).strip()


def create_project_structure(project_name: str, target_dir: Path) -> None:
    """Populate the project root already reserved by the caller."""
    # Create main directories
    project_dir = target_dir / project_name

    # Create app directory
    app_dir = project_dir / project_name
    app_dir.mkdir(exist_ok=True)

    # Create empty __init__.py
    (app_dir / "__init__.py").touch()

    # Create templates directory
    templates_dir = app_dir / "templates"
    templates_dir.mkdir(exist_ok=True)

    # Create static files directory
    static_dir = project_dir / "static"
    static_dir.mkdir(exist_ok=True)

    # Create media directory
    media_dir = project_dir / "media"
    media_dir.mkdir(exist_ok=True)


def create_settings_file(project_name: str, target_dir: Path) -> None:
    """Create settings.py with django-cast configuration."""
    settings_file = target_dir / project_name / project_name / "settings.py"
    settings_content = render_quickstart_template(
        "settings.py.template",
        project_name=project_name,
        secret_key=secrets.token_urlsafe(50),
    )
    settings_file.write_text(settings_content, encoding="utf-8")


def create_urls_file(project_name: str, target_dir: Path) -> None:
    """Create urls.py with django-cast URL configuration."""
    urls_file = target_dir / project_name / project_name / "urls.py"
    urls_content = render_quickstart_template("urls.py.template", project_name=project_name)
    urls_file.write_text(urls_content, encoding="utf-8")


def create_wsgi_file(project_name: str, target_dir: Path) -> None:
    """Create wsgi.py file."""
    wsgi_file = target_dir / project_name / project_name / "wsgi.py"
    wsgi_content = render_quickstart_template("wsgi.py.template", project_name=project_name)
    wsgi_file.write_text(wsgi_content, encoding="utf-8")


def create_manage_py(project_name: str, target_dir: Path) -> None:
    """Create manage.py file."""
    manage_file = target_dir / project_name / "manage.py"
    manage_content = render_quickstart_template("manage.py.template", project_name=project_name)
    manage_file.write_text(manage_content, encoding="utf-8")
    # Make it executable
    manage_file.chmod(0o755)


def create_base_template(project_name: str, target_dir: Path) -> None:
    """Create a basic base.html template."""
    template_file = target_dir / project_name / project_name / "templates" / "base.html"
    template_content = render_quickstart_template("base.html.template")
    template_file.write_text(template_content, encoding="utf-8")


def run_migrations(project_dir: Path) -> None:
    """Run Django migrations."""
    print("\nRunning migrations...")
    manage_py = project_dir / "manage.py"

    # Run makemigrations for sites app first (if needed)
    subprocess.run([sys.executable, str(manage_py), "migrate"], check=True)


def collect_static_files(project_dir: Path) -> None:
    """Run Django collectstatic command."""
    print("\nCollecting static files...")
    manage_py = project_dir / "manage.py"

    # Run collectstatic with --noinput to avoid prompts
    subprocess.run([sys.executable, str(manage_py), "collectstatic", "--noinput"], check=True)


def open_browser_delayed(url: str, delay: float = 5.0) -> None:
    """Open browser after a delay to allow server to start."""

    def _open() -> None:
        time.sleep(delay)
        print(f"\nOpening browser to {url}")
        print("Login with username: user, password: password")
        webbrowser.open(url)

    thread = threading.Thread(target=_open)
    thread.daemon = True
    thread.start()


def create_superuser(project_dir: Path, auto_create: bool = False) -> None:
    """Create superuser either automatically or interactively."""
    manage_py = project_dir / "manage.py"

    if auto_create:
        print("\nCreating superuser with default credentials...")
        print("Username: user")
        print("Password: password")
        print("Email: user@example.com")

        # Create superuser using shell command
        create_user_cmd = """
from django.contrib.auth import get_user_model
User = get_user_model()
if not User.objects.filter(username='user').exists():
    User.objects.create_superuser('user', 'user@example.com', 'password')
    print('Superuser created successfully!')
else:
    print('Superuser already exists.')
"""
        subprocess.run([sys.executable, str(manage_py), "shell", "-c", create_user_cmd], check=True)
    else:
        print("\nCreating superuser account...")
        print("You'll need this to access the Wagtail admin at /cms/")
        subprocess.run([sys.executable, str(manage_py), "createsuperuser"], check=True)


def main() -> None:
    """Main entry point for the quickstart command."""
    parser = argparse.ArgumentParser(
        description="Create a new Django project with django-cast pre-configured.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=dedent("""
        Examples:
          django-cast-quickstart mysite                    # Creates project with default superuser (user/password)
          django-cast-quickstart mysite --interactive-superuser  # Prompts for custom credentials
          django-cast-quickstart mysite --no-superuser     # Skip superuser creation
        """),
    )

    parser.add_argument("project_name", help="Name of the Django project to create")

    parser.add_argument(
        "--interactive-superuser",
        action="store_true",
        help="Prompt for superuser credentials instead of using defaults (user/password)",
    )

    parser.add_argument("--no-superuser", action="store_true", help="Skip superuser creation entirely")

    args = parser.parse_args()

    if args.interactive_superuser and args.no_superuser:
        parser.error("Cannot use --interactive-superuser and --no-superuser together")

    project_name = args.project_name

    # Validate project name
    if (
        not project_name.isidentifier()
        or normalize("NFKC", project_name) != project_name
        or keyword.iskeyword(project_name)
        or project_name in RESERVED_PROJECT_NAMES
    ):
        print(f"Error: '{project_name}' is not an available Python project name.")
        print(
            "Use an NFKC-normalized Python identifier that is neither a keyword nor a reserved framework/package name."
        )
        sys.exit(1)

    # Get target directory
    target_dir = Path.cwd()
    project_path = target_dir / project_name

    # The generated project root comes first on sys.path for manage.py, so a
    # name that shadows a stdlib or installed module breaks Django at import.
    if not project_path.exists() and (
        project_name in sys.modules or importlib.util.find_spec(project_name) is not None
    ):
        print(f"Error: '{project_name}' conflicts with the name of an existing Python module.")
        print("Choose a different project name.")
        sys.exit(1)

    try:
        project_path.mkdir()
    except FileExistsError:
        print(f"Error: Directory '{project_name}' already exists.")
        sys.exit(1)

    owned_root = project_path.stat(follow_symlinks=False)

    print(f"Creating Django-Cast project '{project_name}'...")

    try:
        # Create project structure
        create_project_structure(project_name, target_dir)

        # Create configuration files
        create_settings_file(project_name, target_dir)
        create_urls_file(project_name, target_dir)
        create_wsgi_file(project_name, target_dir)
        create_manage_py(project_name, target_dir)
        create_base_template(project_name, target_dir)

        # Run migrations
        run_migrations(project_path)

        # Collect static files
        collect_static_files(project_path)

        # Create superuser based on arguments
        if not args.no_superuser:
            # Default is auto-create, use interactive only if explicitly requested
            auto_create = not args.interactive_superuser
            create_superuser(project_path, auto_create=auto_create)
        else:
            print("\nSkipping superuser creation.")

    except Exception as e:
        print(f"\nError: {e}")
        # A competing creator/replacement never belongs to this invocation.
        if (
            project_path.exists()
            and (current_root := project_path.stat(follow_symlinks=False)).st_dev == owned_root.st_dev
            and current_root.st_ino == owned_root.st_ino
        ):
            shutil.rmtree(project_path)
        sys.exit(1)

    print(f"\nSuccess! Created Django-Cast project at {project_path}")
    if not args.no_superuser and not args.interactive_superuser:
        print("\nDefault superuser credentials:\n  Username: user\n  Password: password")
        print("\n⚠️  WARNING: Change these default credentials in production!")

    # Initialization is complete. Launch failures must preserve the project/database.
    try:
        os.chdir(project_path)
        print(f"\nChanged to project directory: {project_path}")
        print("\nStarting development server...\nPress Ctrl+C to stop the server")
        print("\nThe browser will open automatically in a few seconds...")
        open_browser_delayed("http://localhost:8000/cms/", delay=5.0)
        subprocess.run([sys.executable, str(project_path / "manage.py"), "runserver"], check=True)
    except KeyboardInterrupt:
        print("\nDevelopment server stopped.")
    except Exception as e:
        print(f"\nLaunch failed: {e}\nRetry: cd {project_path} && {sys.executable} manage.py runserver")
        sys.exit(1)
    finally:
        os.chdir(target_dir)


if __name__ == "__main__":
    main()
