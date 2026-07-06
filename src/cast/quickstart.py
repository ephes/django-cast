#!/usr/bin/env python
"""
Django-Cast quickstart command.

Creates a new Django project with django-cast pre-configured.
"""

import argparse
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


QUICKSTART_TEMPLATE_PACKAGE = "cast"
QUICKSTART_TEMPLATE_DIR = "quickstart_templates"


def render_quickstart_template(template_name: str, **context: str) -> str:
    """Render one packaged quickstart template."""
    template_path = files(QUICKSTART_TEMPLATE_PACKAGE).joinpath(QUICKSTART_TEMPLATE_DIR).joinpath(template_name)
    template = Template(template_path.read_text())
    return template.substitute(context).strip()


def create_project_structure(project_name: str, target_dir: Path) -> None:
    """Create the basic project directory structure."""
    # Create main directories
    project_dir = target_dir / project_name
    project_dir.mkdir(parents=True, exist_ok=True)

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
    settings_file.write_text(settings_content)


def create_urls_file(project_name: str, target_dir: Path) -> None:
    """Create urls.py with django-cast URL configuration."""
    urls_file = target_dir / project_name / project_name / "urls.py"
    urls_content = render_quickstart_template("urls.py.template", project_name=project_name)
    urls_file.write_text(urls_content)


def create_wsgi_file(project_name: str, target_dir: Path) -> None:
    """Create wsgi.py file."""
    wsgi_file = target_dir / project_name / project_name / "wsgi.py"
    wsgi_content = render_quickstart_template("wsgi.py.template", project_name=project_name)
    wsgi_file.write_text(wsgi_content)


def create_manage_py(project_name: str, target_dir: Path) -> None:
    """Create manage.py file."""
    manage_file = target_dir / project_name / "manage.py"
    manage_content = render_quickstart_template("manage.py.template", project_name=project_name)
    manage_file.write_text(manage_content)
    # Make it executable
    manage_file.chmod(0o755)


def create_base_template(project_name: str, target_dir: Path) -> None:
    """Create a basic base.html template."""
    template_file = target_dir / project_name / project_name / "templates" / "base.html"
    template_content = render_quickstart_template("base.html.template")
    template_file.write_text(template_content)


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

    def _open():
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


def main():
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
    if not project_name.isidentifier():
        print(f"Error: '{project_name}' is not a valid Python identifier.")
        print("Project name must start with a letter and contain only letters, numbers, and underscores.")
        sys.exit(1)

    # Get target directory
    target_dir = Path.cwd()
    project_path = target_dir / project_name

    if project_path.exists():
        print(f"Error: Directory '{project_name}' already exists.")
        sys.exit(1)

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

        print(f"\nSuccess! Created Django-Cast project at {project_path}")

        # Show login credentials if auto-created
        if not args.no_superuser and not args.interactive_superuser:
            print("\nDefault superuser credentials:")
            print("  Username: user")
            print("  Password: password")
            print("\n⚠️  WARNING: Change these default credentials in production!")

        # Change to project directory
        os.chdir(project_path)
        print(f"\nChanged to project directory: {project_path}")

        # Start the development server
        print("\nStarting development server...")
        print("Press Ctrl+C to stop the server")

        # Open browser to Wagtail admin after delay
        admin_url = "http://localhost:8000/cms/"
        print("\nThe browser will open automatically in a few seconds...")
        open_browser_delayed(admin_url, delay=5.0)

        # Run the development server
        manage_py = project_path / "manage.py"
        subprocess.run([sys.executable, str(manage_py), "runserver"])

    except Exception as e:
        print(f"\nError: {e}")
        # Clean up on error
        if project_path.exists():
            shutil.rmtree(project_path)
        sys.exit(1)


if __name__ == "__main__":
    main()
