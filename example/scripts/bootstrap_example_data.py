from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bootstrap demo content for the example project.")
    parser.add_argument("--reset-db", action="store_true", help="Delete the example db.sqlite3 before bootstrapping.")
    parser.add_argument("--blog-posts", type=int, default=4, help="Number of blog posts to create.")
    parser.add_argument("--podcast-episodes", type=int, default=3, help="Number of podcast episodes to create.")
    return parser.parse_args()


def _reset_db(db_path: Path) -> None:
    if db_path.exists():
        db_path.unlink()


def _ensure_site():
    from wagtail.models import Site

    site = Site.objects.first()
    if site is None:
        from wagtail.models import Page

        root = Page.get_first_root_node()
        site = Site.objects.create(
            hostname="localhost",
            port=8000,
            root_page=root,
            is_default_site=True,
            site_name="Example",
        )
    return site


def _set_theme(site) -> str:
    from cast.models import TemplateBaseDirectory, get_template_base_dir_choices

    available = {name for name, _label in get_template_base_dir_choices()}
    template_base_dir = "bootstrap5" if "bootstrap5" in available else "bootstrap4"
    TemplateBaseDirectory.objects.update_or_create(site=site, defaults={"name": template_base_dir})
    return template_base_dir


def _publish_page(page) -> None:
    if not page.live:
        page.save_revision().publish()


def _bootstrap_content(*, blog_posts: int, podcast_episodes: int) -> tuple[object, object]:
    from cast.devdata import generate_blog_with_media

    blog = generate_blog_with_media(
        number_of_posts=blog_posts,
        media_numbers={
            "images": 2,
            "galleries": 1,
            "images_in_galleries": 4,
            "videos": 1,
            "audios": 1,
        },
        podcast=False,
    )
    podcast = generate_blog_with_media(
        number_of_posts=podcast_episodes,
        media_numbers={
            "images": 1,
            "galleries": 1,
            "images_in_galleries": 4,
            "videos": 0,
            "audios": 2,
        },
        podcast=True,
    )

    _publish_page(blog)
    _publish_page(podcast)
    for child in blog.get_children().specific():
        _publish_page(child)
    for child in podcast.get_children().specific():
        _publish_page(child)

    return blog, podcast


def _ensure_superuser() -> None:
    from django.contrib.auth import get_user_model

    user_model = get_user_model()
    if user_model.objects.filter(is_superuser=True).exists():
        return
    username = "admin"
    if user_model.objects.filter(username=username).exists():
        user = user_model.objects.get(username=username)
        user.is_staff = True
        user.is_superuser = True
        user.set_password("admin")
        user.save()
    else:
        user_model.objects.create_superuser(username, "admin@example.com", "admin")
    print("Created superuser: admin / admin")


def _maybe_collectstatic() -> None:
    from django.conf import settings
    from django.core.management import call_command

    django_vite = getattr(settings, "DJANGO_VITE", {})
    if not django_vite:
        return

    dev_modes = []
    for config in django_vite.values():
        if isinstance(config, dict):
            dev_modes.append(config.get("dev_mode", False))
        else:
            dev_modes.append(getattr(config, "dev_mode", False))

    if any(mode is False for mode in dev_modes):
        call_command("collectstatic", interactive=False, verbosity=0)
        print("Collected static assets because Vite dev mode is disabled.")


def main() -> int:
    args = _parse_args()
    example_root = Path(__file__).resolve().parents[1]
    db_path = example_root / "db.sqlite3"

    if args.reset_db:
        _reset_db(db_path)

    sys.path.insert(0, str(example_root))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "example_site.settings.dev")
    import django

    django.setup()

    if args.reset_db:
        from django.core.management import call_command

        call_command("migrate", interactive=False)

    from django.contrib.auth import get_user_model
    from wagtail.models import Page

    # Wagtail creates a root page and a default home page; more than two pages implies user content exists.
    if not args.reset_db and (get_user_model().objects.exists() or Page.objects.count() > 2):
        print("Existing data detected. Use --reset-db to rebuild the example database.", file=sys.stderr)
        return 1

    _ensure_superuser()
    _maybe_collectstatic()

    site = _ensure_site()
    theme = _set_theme(site)

    blog, podcast = _bootstrap_content(blog_posts=args.blog_posts, podcast_episodes=args.podcast_episodes)

    print(f"Theme: {theme}")
    print(f"Blog: {blog.url}")
    print(f"Podcast: {podcast.url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
