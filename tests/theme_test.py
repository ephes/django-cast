import shutil
from pathlib import Path

import pytest
from django.template import engines

from cast.context_processors import site_template_base_dir
from cast.models.theme import (
    get_required_template_names,
    get_template_base_dir_candidates,
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
    settings.CAST_CUSTOM_THEMES.append((theme_name, theme_display))
    assert len(get_template_base_dir_choices()) == len(custom_choices)


@pytest.mark.django_db
def test_context_processors_site_template_base_dir(request_factory):
    request = request_factory.get("/")
    context = site_template_base_dir(request)
    assert context["cast_site_template_base_dir"] == "bootstrap4"
    assert context["cast_base_template"] == "cast/bootstrap4/base.html"