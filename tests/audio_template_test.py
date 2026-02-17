import pytest
from django.template.loader import render_to_string


TEMPLATE_NAME = "cast/audio/audio.html"


@pytest.mark.django_db
def test_facade_mode_renders_facade_html(post_with_audio, audio):
    """Facade mode renders data-load-mode="facade" and facade HTML structure."""
    post = post_with_audio
    html = render_to_string(
        TEMPLATE_NAME,
        {
            "page": post,
            "value": audio,
            "podlove_load_mode": "facade",
            "render_for_feed": False,
        },
    )
    assert 'data-load-mode="facade"' in html
    assert "podlove-player-container" in html
    assert "podlove-facade" in html
    assert "podlove-facade-inner" in html
    assert "podlove-facade-title" in html
    assert audio.name in html
    assert "podlove-facade-play" in html


@pytest.mark.django_db
def test_facade_mode_contextual_aria_label(post_with_audio, audio):
    """Facade play button includes episode title in aria-label."""
    post = post_with_audio
    html = render_to_string(
        TEMPLATE_NAME,
        {
            "page": post,
            "value": audio,
            "podlove_load_mode": "facade",
            "render_for_feed": False,
        },
    )
    assert f'aria-label="Play {audio.name}"' in html


@pytest.mark.django_db
def test_facade_mode_renders_duration(post_with_audio, audio):
    """Facade mode renders the duration string in the time display."""
    post = post_with_audio
    html = render_to_string(
        TEMPLATE_NAME,
        {
            "page": post,
            "value": audio,
            "podlove_load_mode": "facade",
            "render_for_feed": False,
        },
    )
    assert "podlove-facade-time" in html
    assert audio.duration_str in html


@pytest.mark.django_db
def test_facade_mode_hides_duration_when_none(post_with_audio, audio):
    """Facade mode suppresses the duration in time display when audio.duration is NULL."""
    post = post_with_audio
    audio.duration = None
    audio.save(duration=False)
    html = render_to_string(
        TEMPLATE_NAME,
        {
            "page": post,
            "value": audio,
            "podlove_load_mode": "facade",
            "render_for_feed": False,
        },
    )
    # Time display still exists but the second span (duration) must be empty
    assert "podlove-facade-time" in html
    import re

    time_match = re.search(r'class="podlove-facade-time">\s*<span>00:00</span>\s*<span>(.*?)</span>', html, re.DOTALL)
    assert time_match is not None
    assert time_match.group(1).strip() == ""


@pytest.mark.django_db
def test_facade_mode_with_cover_image(post_with_audio, audio, image):
    """Facade mode renders cover image via Wagtail image tag when FK is available."""
    post = post_with_audio
    post.cover_image = image
    post.save()
    html = render_to_string(
        TEMPLATE_NAME,
        {
            "page": post,
            "value": audio,
            "podlove_load_mode": "facade",
            "render_for_feed": False,
        },
    )
    assert "podlove-facade-cover" in html
    assert "<img" in html
    # Stacked mobile layout modifier and retina-ready rendition
    assert "podlove-facade-has-cover" in html
    assert "fill-400x400" in html


@pytest.mark.django_db
def test_facade_mode_with_blog_cover_fallback(post_with_audio, blog, audio, image):
    """Facade mode falls back to blog cover image when post has no cover image."""
    post = post_with_audio
    assert post.cover_image is None
    blog.cover_image = image
    blog.save()
    html = render_to_string(
        TEMPLATE_NAME,
        {
            "page": post,
            "value": audio,
            "blog": blog,
            "podlove_load_mode": "facade",
            "render_for_feed": False,
        },
    )
    assert "podlove-facade-cover" in html
    assert "podlove-facade-has-cover" in html
    assert "fill-400x400" in html


@pytest.mark.django_db
def test_facade_mode_with_cover_image_url_fallback(post_with_audio, audio):
    """Facade mode falls back to cover_image_url when FK is not available (cached path)."""
    post = post_with_audio
    assert post.cover_image is None
    # Simulate the cached repository path where only cover_image_url is set
    post.cover_image_url = "/media/images/cover.jpg"
    post.cover_alt_text_display = "Episode artwork"
    html = render_to_string(
        TEMPLATE_NAME,
        {
            "page": post,
            "value": audio,
            "podlove_load_mode": "facade",
            "render_for_feed": False,
        },
    )
    assert "podlove-facade-cover" in html
    assert "/media/images/cover.jpg" in html
    assert 'alt="Episode artwork"' in html
    assert 'loading="lazy"' in html
    # No stacked mobile layout without a Wagtail cover image
    assert "podlove-facade-has-cover" not in html


@pytest.mark.django_db
def test_facade_mode_without_cover_image(post_with_audio, audio):
    """Facade mode renders SVG waveform placeholder when page has no cover image."""
    post = post_with_audio
    assert post.cover_image is None
    html = render_to_string(
        TEMPLATE_NAME,
        {
            "page": post,
            "value": audio,
            "podlove_load_mode": "facade",
            "render_for_feed": False,
        },
    )
    assert "podlove-facade-waveform" in html
    assert "<img" not in html  # no <img> tag, only SVG placeholder
    assert "podlove-facade-title" in html
    assert "podlove-facade-play" in html
    # No stacked mobile layout without a cover image
    assert "podlove-facade-has-cover" not in html


@pytest.mark.django_db
def test_click_mode_renders_click_attribute(post_with_audio, audio):
    """Click mode renders data-load-mode="click" and no facade HTML."""
    post = post_with_audio
    html = render_to_string(
        TEMPLATE_NAME,
        {
            "page": post,
            "value": audio,
            "podlove_load_mode": "click",
            "render_for_feed": False,
        },
    )
    assert 'data-load-mode="click"' in html
    assert "podlove-facade" not in html
    assert "podlove-facade-inner" not in html


@pytest.mark.django_db
def test_default_mode_no_load_mode_attribute(post_with_audio, audio):
    """Default mode (no podlove_load_mode) renders no data-load-mode attribute."""
    post = post_with_audio
    html = render_to_string(
        TEMPLATE_NAME,
        {
            "page": post,
            "value": audio,
            "render_for_feed": False,
        },
    )
    assert "data-load-mode" not in html
    assert "podlove-facade" not in html
