"""Block converters shared by content transports."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from django.core.exceptions import ValidationError as DjangoValidationError
from wagtail.blocks import Block

from cast.post_body_blocks import configured_content_blocks, default_content_blocks

from .errors import ErrorCollector, flatten_django_validation_error
from .media_refs import get_choosable_audio, get_choosable_image, get_choosable_video
from .richtext import sanitize_block_value

_CUSTOM_BLOCK_CONVERSION_ERRORS = (TypeError, ValueError, KeyError, AttributeError)
_CUSTOM_BLOCK_READ_ERRORS = (DjangoValidationError, *_CUSTOM_BLOCK_CONVERSION_ERRORS)


@dataclass(frozen=True)
class ConversionContext:
    """State shared by one conversion.

    Writes require ``user`` only when resolving media references. On reads,
    ``user=None`` deliberately skips media visibility filtering.
    """

    section: str | None
    user: Any | None
    existing_section: list[dict] | None = None
    path_prefix: str | None = None


class Unsupported:
    """Sentinel type for stored values that cannot be represented to authors."""


UNSUPPORTED = Unsupported()


class BlockConverter(Protocol):
    """Convert one named block between author and StreamField representations.

    ``to_stream`` records only fatal errors. A conversion succeeds exactly
    when it adds no errors, so a successful prepared value may be ``None``.
    """

    @property
    def name(self) -> str: ...  # pragma: no cover

    @property
    def editable(self) -> bool: ...  # pragma: no cover

    def to_stream(
        self, value: Any, *, ctx: ConversionContext, path: str, errors: ErrorCollector
    ) -> Any | None: ...  # pragma: no cover

    def to_author(self, value: Any, *, ctx: ConversionContext) -> Any | Unsupported: ...  # pragma: no cover


def _unwrap_list_item_values(value: Any) -> Any:
    if isinstance(value, list):
        if all(isinstance(item, dict) and item.get("type") == "item" and "value" in item for item in value):
            return [_unwrap_list_item_values(item["value"]) for item in value]
        return [_unwrap_list_item_values(item) for item in value]
    if isinstance(value, dict):
        return {key: _unwrap_list_item_values(item) for key, item in value.items()}
    return value


def _custom_author_value(block: Block, value: Any) -> Any:
    python_value = block.to_python(value)
    cleaned = block.clean(python_value)
    if type(block).get_api_representation is not Block.get_api_representation:
        return block.get_api_representation(cleaned)
    return _unwrap_list_item_values(block.get_prep_value(cleaned))


@dataclass(frozen=True)
class GenericBlockConverter:
    """Adapt a configured Wagtail block to the content conversion contract."""

    name: str
    block: Block
    editable: bool = True

    def to_stream(self, value: Any, *, ctx: ConversionContext, path: str, errors: ErrorCollector) -> Any | None:
        try:
            python_value = self.block.to_python(value)
            before = len(errors)
            python_value = sanitize_block_value(self.block, python_value, path=path, errors=errors)
            if len(errors) > before:
                return None
            cleaned = self.block.clean(python_value)
            return self.block.get_prep_value(cleaned)
        except DjangoValidationError as exc:
            errors.extend(flatten_django_validation_error(exc, path))
        except _CUSTOM_BLOCK_CONVERSION_ERRORS as exc:
            errors.add(path, "invalid", str(exc) or "Invalid custom block value.")
        return None

    def to_author(self, value: Any, *, ctx: ConversionContext) -> Any | Unsupported:
        try:
            return _custom_author_value(self.block, value)
        except _CUSTOM_BLOCK_READ_ERRORS:
            return UNSUPPORTED


@dataclass(frozen=True)
class ParagraphConverter:
    name: str = "paragraph"
    editable: bool = True
    block: Block = field(default_factory=lambda: dict(default_content_blocks())["paragraph"])

    def to_stream(self, value: Any, *, ctx: ConversionContext, path: str, errors: ErrorCollector) -> Any | None:
        if not isinstance(value, str):
            errors.add(path, "invalid", "Expected a string value.")
            return None
        try:
            python_value = sanitize_block_value(self.block, self.block.to_python(value), path=path, errors=errors)
            if python_value is None:
                return None
            cleaned = self.block.clean(python_value)
        except DjangoValidationError as exc:
            message = "; ".join(exc.messages) or "Invalid rich text."
            errors.add(path, "invalid", message)
            return None
        return self.block.get_prep_value(cleaned)

    def to_author(self, value: Any, *, ctx: ConversionContext) -> Any:
        return value


@dataclass(frozen=True)
class EmbedConverter:
    name: str = "embed"
    editable: bool = False

    def to_stream(self, value: Any, *, ctx: ConversionContext, path: str, errors: ErrorCollector) -> None:
        errors.add(
            f"{path.rsplit('.', 1)[0]}.type",
            "unsupported_block_type",
            f"Block type {self.name!r} is not supported.",
        )

    def to_author(self, value: Any, *, ctx: ConversionContext) -> Unsupported:
        return UNSUPPORTED


@dataclass(frozen=True)
class CodeConverter:
    name: str = "code"
    editable: bool = True

    def to_stream(self, value: Any, *, ctx: ConversionContext, path: str, errors: ErrorCollector) -> Any | None:
        if not isinstance(value, dict):
            errors.add(path, "invalid", "Expected an object value.")
            return None
        invalid = False
        for key in ("language", "source"):
            if not isinstance(value.get(key), str) or not value.get(key):
                errors.add(f"{path}.{key}", "required", f"Code block '{key}' is required.")
                invalid = True
        if invalid:
            return None
        return {"language": value["language"], "source": value["source"]}

    def to_author(self, value: Any, *, ctx: ConversionContext) -> Any | Unsupported:
        if isinstance(value, dict) and isinstance(value.get("language"), str) and isinstance(value.get("source"), str):
            return {"language": value["language"], "source": value["source"]}
        return UNSUPPORTED


@dataclass(frozen=True)
class MediaRefConverter:
    """Convert one permission-filtered media chooser reference."""

    name: str
    resolver: Callable[[Any, Any], Any | None]
    not_found_message: Callable[[Any], str]
    editable: bool = True

    def to_stream(self, value: Any, *, ctx: ConversionContext, path: str, errors: ErrorCollector) -> Any | None:
        object_id = value.get("id") if isinstance(value, dict) else None
        if self.resolver(object_id, ctx.user) is None:
            errors.add(f"{path}.id", "not_found", self.not_found_message(object_id))
            return None
        return object_id

    def to_author(self, value: Any, *, ctx: ConversionContext) -> Any | Unsupported:
        if ctx.user is not None and self.resolver(value, ctx.user) is None:
            return UNSUPPORTED
        return {"id": value}


class ImageConverter(MediaRefConverter):
    def __init__(self) -> None:
        super().__init__(
            name="image",
            resolver=get_choosable_image,
            not_found_message=lambda object_id: f"Image {object_id} does not exist or is not accessible.",
        )


class AudioConverter(MediaRefConverter):
    def __init__(self) -> None:
        super().__init__(
            name="audio",
            resolver=get_choosable_audio,
            not_found_message=lambda object_id: "Referenced media is not available.",
        )


class VideoConverter(MediaRefConverter):
    def __init__(self) -> None:
        super().__init__(
            name="video",
            resolver=get_choosable_video,
            not_found_message=lambda object_id: "Referenced media is not available.",
        )


def content_converters(section: str | None) -> dict[str, BlockConverter]:
    """Return built-in and configured converters for ``section``."""
    converters: dict[str, BlockConverter] = {
        converter.name: converter
        for converter in (
            ParagraphConverter(),
            EmbedConverter(),
            CodeConverter(),
            ImageConverter(),
            AudioConverter(),
            VideoConverter(),
        )
    }
    if section is not None:
        for name, block in configured_content_blocks(section):
            if name not in converters:
                converters[name] = GenericBlockConverter(name=name, block=block)
    return converters
