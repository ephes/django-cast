from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeAlias

from django.utils.module_loading import import_string
from wagtail import blocks
from wagtail.embeds.blocks import EmbedBlock

from cast import appsettings
from cast.blocks import (
    AudioChooserBlock,
    CastImageChooserBlock,
    CodeBlock,
    GalleryBlockWithLayout,
    VideoChooserBlock,
)

POST_BODY_BLOCKS_SETTING = "CAST_POST_BODY_BLOCKS"
POST_BODY_SECTIONS = frozenset({"overview", "detail"})
DEFAULT_CONTENT_BLOCK_NAMES = (
    "paragraph",
    "code",
    "image",
    "gallery",
    "embed",
    "video",
    "audio",
)

ContentBlockDefinition: TypeAlias = tuple[str, blocks.Block]
PostBodyBlockFactory: TypeAlias = Callable[[], ContentBlockDefinition]


def default_content_blocks() -> list[ContentBlockDefinition]:
    """Return fresh instances of django-cast's built-in Post.body blocks."""
    return [
        ("paragraph", blocks.RichTextBlock()),
        ("code", CodeBlock(icon="code")),
        ("image", CastImageChooserBlock(template="cast/image/image.html")),
        ("gallery", GalleryBlockWithLayout()),
        ("embed", EmbedBlock()),
        ("video", VideoChooserBlock(template="cast/video/video.html", icon="media")),
        ("audio", AudioChooserBlock(template="cast/audio/audio.html", icon="media")),
    ]


def _setting_value() -> Any:
    return appsettings.CAST_POST_BODY_BLOCKS


def _setting_section_path(section: str, index: int | None = None) -> str:
    section_path = f"{POST_BODY_BLOCKS_SETTING}[{section!r}]"
    if index is None:
        return section_path
    return f"{section_path}[{index}]"


def _validate_setting_shape(value: Any) -> tuple[dict[str, Any], list[str]]:
    if value is None:
        return {}, []
    if not isinstance(value, dict):
        return (
            {},
            [f"{POST_BODY_BLOCKS_SETTING} must be a dict mapping 'overview' and 'detail' to lists of paths."],
        )

    errors = [
        f"{POST_BODY_BLOCKS_SETTING} contains unsupported section {section!r}; expected only 'overview' or 'detail'."
        for section in value
        if section not in POST_BODY_SECTIONS
    ]
    return value, errors


def _get_section_paths(setting: dict[str, Any], section: str) -> tuple[list[str], list[str]]:
    paths = setting.get(section, [])
    if not isinstance(paths, (list, tuple)):
        return [], [f"{_setting_section_path(section)} must be a list or tuple of dotted factory paths."]

    errors: list[str] = []
    dotted_paths: list[str] = []
    for index, path in enumerate(paths):
        if not isinstance(path, str) or not path:
            errors.append(f"{_setting_section_path(section, index)} must be a non-empty dotted factory path string.")
        else:
            dotted_paths.append(path)
    return dotted_paths, errors


def _load_factory(path: str, section: str, index: int) -> tuple[PostBodyBlockFactory | None, list[str]]:
    setting_path = _setting_section_path(section, index)
    try:
        factory = import_string(path)
    except Exception as exc:
        return None, [f"{setting_path} could not import {path!r}: {exc}"]
    if not callable(factory):
        return None, [f"{setting_path} must point to a callable factory, got {type(factory).__name__}."]
    return factory, []


def _call_factory(factory: PostBodyBlockFactory, path: str, section: str, index: int) -> tuple[Any, list[str]]:
    setting_path = _setting_section_path(section, index)
    try:
        return factory(), []
    except Exception as exc:
        return None, [f"{setting_path} factory {path!r} raised {type(exc).__name__}: {exc}"]


def _validate_factory_result(
    result: Any, path: str, section: str, index: int
) -> tuple[ContentBlockDefinition | None, str | None]:
    setting_path = _setting_section_path(section, index)
    if not isinstance(result, tuple) or len(result) != 2:
        return None, f"{setting_path} factory {path!r} must return a two-item tuple of (name, block)."

    name, block = result
    if not isinstance(name, str):
        return None, f"{setting_path} factory {path!r} returned a non-string block name."
    if not name.strip():
        return None, f"{setting_path} factory {path!r} returned an empty block name."
    if not isinstance(block, blocks.Block):
        return (
            None,
            f"{setting_path} factory {path!r} returned {name!r} with {type(block).__name__}; "
            "expected a wagtail.blocks.Block instance.",
        )
    if name in DEFAULT_CONTENT_BLOCK_NAMES:
        return None, f"{setting_path} custom block name {name!r} collides with a built-in Post.body block."
    return (name, block), None


def _load_section_blocks(section: str, setting: dict[str, Any]) -> tuple[list[ContentBlockDefinition], list[str]]:
    paths, errors = _get_section_paths(setting, section)
    if errors:
        return [], errors

    blocks_for_section: list[ContentBlockDefinition] = []
    seen_names: set[str] = set()
    for index, path in enumerate(paths):
        factory, factory_errors = _load_factory(path, section, index)
        if factory_errors:
            errors.extend(factory_errors)
            continue

        assert factory is not None
        result, call_errors = _call_factory(factory, path, section, index)
        if call_errors:
            errors.extend(call_errors)
            continue

        block_definition, result_error = _validate_factory_result(result, path, section, index)
        if result_error is not None:
            errors.append(result_error)
            continue

        assert block_definition is not None
        name, block = block_definition
        if name in seen_names:
            errors.append(f"{_setting_section_path(section, index)} custom block name {name!r} is duplicated.")
            continue

        seen_names.add(name)
        blocks_for_section.append((name, block))
    return blocks_for_section, errors


def configured_content_blocks(section: str) -> list[ContentBlockDefinition]:
    """Return configured custom blocks for one Post.body section.

    Invalid settings are reported by system checks. Runtime block construction
    falls back to the built-in blocks so Django can start and display those
    check errors instead of failing during model import.
    """
    setting, setting_errors = _validate_setting_shape(_setting_value())
    if section not in POST_BODY_SECTIONS or setting_errors:
        return []

    blocks_for_section, errors = _load_section_blocks(section, setting)
    if errors:
        return []
    return blocks_for_section


def validate_post_body_block_setting() -> list[str]:
    """Return validation errors for CAST_POST_BODY_BLOCKS."""
    setting, errors = _validate_setting_shape(_setting_value())
    if errors:
        return errors

    for section in ("overview", "detail"):
        _, section_errors = _load_section_blocks(section, setting)
        errors.extend(section_errors)
    return errors
