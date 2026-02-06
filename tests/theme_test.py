import shutil
from pathlib import Path
import pytest
from django.db.utils import OperationalError
from django.template import engines
from django.urls import reverse
from wagtail.models import Site

from cast.context_processors import DEFAULT_TEMPLATE_BASE_DIR, site_template_base_dir
from cast.models.theme import (
    _clear_template_base_dir_choices_cache,
    get_required_template_names,
    get_template_base_dir_candidates,
    get_template_base_dir,
    get_template_base_dir_choices,
    get_template_directories,
)


def create_new_theme(name, invalid=False):
    default_engine = list(engines.all())[0]
    first_template_dir = Path(list(list(default_engine.engine.template_loaders)[0].get_dirs())[0])

    new_base_dir = first_template_dir / "cast" / name
    new_base_dir.mkdir(parents=True, exist_ok=True)

    required_names = get_required_template_names()
    if invalid:
        required_names = required_names[:-2]  # remove a required name to make it invalid

    for template_name in required_names:
        path = new_base_dir / template_name
        path.touch()

    return new_base_dir


def test_get_template_base_dir_choices():
    def get_choice_values():
        _clear_template_base_dir_choices_cache()
        return {choice[0] for choice in get_template_base_dir_choices()}

    # make sure the theme we create is not already there
    choices = get_choice_values()
    theme_name = "foobar"
    assert theme_name not in choices

    # create an invalid theme
    invalid_name = "invalid"
    invalid_base_dir = create_new_theme(invalid_name, invalid=True)
    choices_with_invalid_theme = get_choice_values()
    assert invalid_name not in choices_with_invalid_theme
    shutil.rmtree(invalid_base_dir)  # cleanup

    # create a valid new theme
    created_base_dir = create_new_theme(theme_name)
    choices_with_new_theme = get_choice_values()
    assert theme_name in choices_with_new_theme

    shutil.rmtree(created_base_dir)  # cleanup
    assert not created_base_dir.exists()


def test_get_template_base_dir_candidates_empty_required_names():
    assert len(get_template_base_dir_candidates([], required_template_names=[])) == 0


def test_get_template_directories_no_compatible_loaders(mocker):
    class FakeLoader:
        pass

    class FakeEngine:
        template_loaders = [FakeLoader()]

    class FakeContainer:
        engine = FakeEngine()

    mocker.patch("cast.models.theme.engines.all", return_value=[FakeContainer()])
    assert get_template_directories() == []


def test_cast_custom_theme_settings_show_up(settings):
    theme_name, theme_display = "my_theme", "My Theme"

    # make sure the custom theme is added to the choices
    settings.CAST_CUSTOM_THEMES = [(theme_name, theme_display)]
    custom_choices = get_template_base_dir_choices()
    assert (theme_name, theme_display) in custom_choices

    # make sure you cannot add predefined themes twice
    _clear_template_base_dir_choices_cache()
    settings.CAST_CUSTOM_THEMES.append((theme_name, theme_display))
    assert len(get_template_base_dir_choices()) == len(custom_choices)


@pytest.mark.django_db
def test_context_processors_site_template_base_dir(rf):
    request = rf.get("/")
    context = site_template_base_dir(request)
    assert context["cast_site_template_base_dir"] == "bootstrap4"
    assert context["cast_base_template"] == "cast/bootstrap4/base.html"


@pytest.mark.django_db
def test_context_processors_get_site_template_base_dir_from_request(rf):
    request = rf.get("/")
    request.cast_site_template_base_dir = "plain"
    context = site_template_base_dir(request)
    assert context["cast_site_template_base_dir"] == "plain"
    assert context["cast_base_template"] == "cast/plain/base.html"


def test_get_template_base_dir_override(simple_request):
    simple_request.cast_template_base_dir = "plain"
    assert get_template_base_dir(simple_request, "bootstrap4") == "plain"


def test_get_template_base_dir_query_param_overrides_session(rf):
    request = rf.get("/?theme=plain")
    request.session = {"template_base_dir": "bootstrap4"}
    assert get_template_base_dir(request, "bootstrap4") == "plain"


def test_get_template_base_dir_template_param_overrides_session(rf):
    request = rf.get("/?template_base_dir=plain")
    request.session = {"template_base_dir": "bootstrap4"}
    assert get_template_base_dir(request, "bootstrap4") == "plain"


def test_get_template_base_dir_override_still_wins_over_query_param(simple_request):
    simple_request.cast_template_base_dir = "plain"
    simple_request.GET = {"theme": "bootstrap4"}
    assert get_template_base_dir(simple_request, "bootstrap4") == "plain"


def test_get_template_base_dir_ignores_invalid_query_param(rf):
    request = rf.get("/?template_base_dir=missing-theme")
    request.session = {"template_base_dir": "plain"}
    assert get_template_base_dir(request, "bootstrap4") == "plain"


@pytest.mark.django_db
def test_get_select_theme_view(client):
    url = reverse("cast:select-theme")
    response = client.get(url)
    assert response.status_code == 200
    select_template_name = response.templates[0].name
    assert select_template_name == "cast/select_theme_page.html"


@pytest.mark.django_db
def test_get_select_theme_view_htmx(client):
    url = reverse("cast:select-theme")
    response = client.get(url, HTTP_HX_REQUEST="true")
    assert response.status_code == 200
    select_template_name = response.templates[0].name
    assert select_template_name.endswith("/select_theme.html")


@pytest.mark.django_db
def test_post_select_theme_view_invalid(client):
    # Given an invalid theme and a next url
    url = reverse("cast:select-theme")
    theme, next_url = "invalid", "/next-url/"
    # When we post to the select theme view
    response = client.post(
        url,
        {
            "template_base_dir": theme,
            "next": next_url,
        },
    )
    # Then we are not redirected to the next url and the theme is not stored in the session
    # and the form was invalid and has an error for the invalid field
    assert response.status_code == 200
    assert "template_base_dir" not in client.session
    assert "template_base_dir" in response.context["theme_form"].errors


@pytest.mark.django_db
def test_post_select_theme_view_happy(client):
    # Given plain as theme and a next url
    url = reverse("cast:select-theme")
    theme, next_url = "plain", "/next-url/"
    # When we post to the select theme view
    response = client.post(
        url,
        {
            "template_base_dir": theme,
            "next": next_url,
        },
    )
    # Then we are redirected to the next url and the theme is stored in the session
    assert response.status_code == 302
    assert next_url == response.url
    assert client.session["template_base_dir"] == "plain"


@pytest.mark.django_db
def test_non_existent_theme_returns_default(rf):
    """
    Make sure that if there are no sites and the template base dir does not exist,
    the default is returned.
    """
    Site.objects.all().delete()  # make sure there are no sites
    request = rf.get("/")
    context = site_template_base_dir(request)
    assert context["cast_site_template_base_dir"] == DEFAULT_TEMPLATE_BASE_DIR


def test_get_template_base_dir_choices_cache(mocker):
    """Verify that get_template_base_dir_choices caches after the first call."""
    mock_get_dirs = mocker.patch("cast.models.theme.get_template_directories", return_value=[])
    first = get_template_base_dir_choices()
    second = get_template_base_dir_choices()
    assert first == second
    assert first is not second  # returns fresh list copy each time
    assert mock_get_dirs.call_count == 1


def test_clear_template_base_dir_choices_cache(mocker):
    """Verify that _clear_template_base_dir_choices_cache resets the cache."""
    mock_get_dirs = mocker.patch("cast.models.theme.get_template_directories", return_value=[])
    get_template_base_dir_choices()
    _clear_template_base_dir_choices_cache()
    get_template_base_dir_choices()
    assert mock_get_dirs.call_count == 2


@pytest.mark.django_db
def test_context_processor_provides_theme_keys(rf):
    """Context processor should provide all theme-switching keys."""
    request = rf.get("/some-page/")
    context = site_template_base_dir(request)
    assert "template_base_dir" in context
    assert "theme_form" in context
    assert "template_base_dir_choices" in context
    assert "next_url" in context
    assert "has_selectable_themes" in context
    assert context["next_url"] == "/some-page/"
    assert context["template_base_dir"] == "bootstrap4"
    assert isinstance(context["has_selectable_themes"], bool)


@pytest.mark.django_db
def test_context_processor_theme_keys_no_site(rf):
    """When no site exists, theme keys should still be present with defaults."""
    Site.objects.all().delete()
    request = rf.get("/")
    context = site_template_base_dir(request)
    assert context["template_base_dir"] == DEFAULT_TEMPLATE_BASE_DIR
    assert "theme_form" in context
    assert "template_base_dir_choices" in context
    assert "next_url" in context
    assert "has_selectable_themes" in context


@pytest.mark.django_db
def test_context_processor_respects_query_param(rf):
    """Query parameter ?theme= should override the site default."""
    request = rf.get("/?theme=plain")
    request.session = {}
    context = site_template_base_dir(request)
    assert context["template_base_dir"] == "plain"


@pytest.mark.django_db
def test_context_processor_respects_session(rf):
    """Session value should override the site default."""
    request = rf.get("/")
    request.session = {"template_base_dir": "plain"}
    context = site_template_base_dir(request)
    assert context["template_base_dir"] == "plain"


@pytest.mark.django_db
def test_context_processor_survives_db_error(rf, mocker):
    """Context processor must not 500 even when the DB raises OperationalError."""
    mocker.patch(
        "cast.context_processors.TemplateBaseDirectory.for_request",
        side_effect=OperationalError("connection refused"),
    )
    request = rf.get("/")
    context = site_template_base_dir(request)
    assert context["cast_site_template_base_dir"] == DEFAULT_TEMPLATE_BASE_DIR
    assert context["template_base_dir"] == DEFAULT_TEMPLATE_BASE_DIR


def test_choices_cache_is_stale_after_settings_change(settings, mocker):
    """Cache is process-lifetime: new themes added after first call are invisible until cleared."""
    mocker.patch("cast.models.theme.get_template_directories", return_value=[])
    first = get_template_base_dir_choices()
    settings.CAST_CUSTOM_THEMES = [("new_runtime_theme", "New Runtime Theme")]
    second = get_template_base_dir_choices()
    # second call returns the cached result — "new_runtime_theme" is NOT visible
    assert first == second
    assert ("new_runtime_theme", "New Runtime Theme") not in second
    # only after explicit cache clear does the new theme appear
    _clear_template_base_dir_choices_cache()
    third = get_template_base_dir_choices()
    assert ("new_runtime_theme", "New Runtime Theme") in third
