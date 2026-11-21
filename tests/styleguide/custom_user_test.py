"""Exercise the styleguide with auth relationships bound to a custom user at startup."""

import os
import subprocess
import sys
from pathlib import Path


def test_styleguide_seeds_and_reuses_configured_user(tmp_path):
    # Swapping AUTH_USER_MODEL after Django setup leaves some relationships
    # bound to the original user. Boot a separate, disposable project instead.
    env = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": "tests.settings",
        "CAST_TEST_MEDIA_ROOT": str(tmp_path / "media"),
        "CAST_TEST_PRIVATE_MEDIA_ROOT": str(tmp_path / "private"),
    }
    result = subprocess.run(
        [sys.executable, "-m", "tests.styleguide.custom_user_test"],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def _exercise_styleguide():
    import django
    from django.conf import settings

    settings.INSTALLED_APPS = [*settings.INSTALLED_APPS, "tests.styleguide.custom_user_app"]
    settings.AUTH_USER_MODEL = "custom_user_app.SeedUser"
    settings.DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
    settings.CAST_ENABLE_DEV_TOOLS = True
    settings.CAST_COMMENTS_ENABLED = True
    django.setup()

    from django.contrib.auth import get_user_model
    from django.core.management import call_command
    from django.test import Client
    from django.urls import reverse

    from cast.models import Audio, Blog, Post, Video
    from cast.views.styleguide import STYLEGUIDE_BLOG_SLUG, STYLEGUIDE_POST_SLUG_PREFIX, STYLEGUIDE_USER_NAME

    call_command("migrate", run_syncdb=True, verbosity=0, interactive=False)
    users = get_user_model()._default_manager
    staff = users.create_user(handle="synthetic-staff", password="fixture-password", is_staff=True)
    client = Client()
    client.force_login(staff)
    url = reverse("cast:styleguide") + "?theme=plain"

    assert client.get(url).status_code == 200
    owner = users.get(handle=STYLEGUIDE_USER_NAME)
    blog = Blog.objects.get(slug=STYLEGUIDE_BLOG_SLUG)
    posts = Post.objects.filter(slug__startswith=STYLEGUIDE_POST_SLUG_PREFIX)
    post_ids = set(posts.values_list("pk", flat=True))
    assert post_ids
    assert blog.owner == owner
    assert Audio.objects.filter(user=owner).exists()
    assert Video.objects.filter(user=owner).exists()
    assert not owner.is_active and not owner.has_usable_password()

    assert client.get(url).status_code == 200
    assert users.get(handle=STYLEGUIDE_USER_NAME).pk == owner.pk
    assert set(posts.values_list("pk", flat=True)) == post_ids


if __name__ == "__main__":
    _exercise_styleguide()
