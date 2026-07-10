from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Union

from django.conf import settings
from django.db.models.signals import post_delete
from wagtail.images import get_image_model
from wagtail.images.signal_handlers import post_delete_file_cleanup

_AUDIO_UPLOAD_MAX_BYTES = 512 * 1024 * 1024
_VIDEO_UPLOAD_MAX_BYTES = 2 * 1024 * 1024 * 1024
_EDITOR_MEDIA_PROBE_SECONDS = 10
_EDITOR_MEDIA_UPLOAD_LOCK_SECONDS = 7200


@dataclass(frozen=True)
class CastSetting:
    default: Any
    check_type: type | None = None


CAST_SETTING_REGISTRY: dict[str, CastSetting] = {
    "CAST_COMMENTS_ENABLED": CastSetting(False, bool),
    "CAST_COMMENTS_ALLOW_AUTHOR_EDITS": CastSetting(False, bool),
    "CAST_COMMENTS_FORM_CSS_CLASS": CastSetting("comments-form form-horizontal"),
    "CAST_COMMENTS_LABEL_CSS_CLASS": CastSetting("col-sm-2"),
    "CAST_COMMENTS_FIELD_CSS_CLASS": CastSetting("col-sm-10"),
    "CAST_COMMENTS_OWNED_IDS_CAP": CastSetting(200),
    "CAST_COMMENTS_AUTHOR_EDIT_WINDOW": CastSetting(0),
    "CAST_COMMENTS_EDIT_RATE_LIMIT": CastSetting(30),
    "CAST_COMMENTS_EDIT_RATE_WINDOW": CastSetting(60),
    "CAST_CUSTOM_THEMES": CastSetting([], list),
    "CAST_FOLLOW_LINKS": CastSetting({}, dict),
    "CHOOSER_PAGINATION": CastSetting(10),
    "MENU_ITEM_PAGINATION": CastSetting(20),
    "POST_LIST_PAGINATION": CastSetting(5),
    "DELETE_WAGTAIL_IMAGES": CastSetting(True),
    "CAST_FILTERSET_FACETS": CastSetting(
        ["search", "date", "date_facets", "category_facets", "tag_facets", "o"], list
    ),
    "CAST_IMAGE_FORMATS": CastSetting(["jpeg", "avif"], list),
    "CAST_REGULAR_IMAGE_SLOT_DIMENSIONS": CastSetting([(1110, 740)], list),
    "CAST_GALLERY_IMAGE_SLOT_DIMENSIONS": CastSetting([(1110, 740), (120, 80)], list),
    "CAST_GALLERY_THUMBNAIL_RENDITIONS_SRGB": CastSetting(True, bool),
    "CAST_REPOSITORY": CastSetting("default", str),
    "CAST_PODLOVE_PLAYER_THEMES": CastSetting({}, dict),
    "CAST_AUDIO_PLAYER": CastSetting("podlove", str),
    "CAST_EDITOR_SCOPES": CastSetting(
        {
            # django-cast deliberately has a single write bucket (create/update are not split),
            # so the standard IndieAuth post-write scopes ``create``/``update`` both satisfy it.
            # ``media`` (IndieAuth's upload-endpoint scope) and other aliases are intentionally
            # NOT bundled here: a site whose issuer uses them maps them in via this setting.
            "write": {"write", "create", "update"},
            "publish": {"publish"},
        }
    ),
    "CAST_PRIVATE_MEDIA_ROOT": CastSetting(""),
    "CAST_AUDIO_UPLOAD_MAX_BYTES": CastSetting(_AUDIO_UPLOAD_MAX_BYTES),
    "CAST_VIDEO_UPLOAD_MAX_BYTES": CastSetting(_VIDEO_UPLOAD_MAX_BYTES),
    "CAST_EDITOR_MEDIA_PROBE_SECONDS": CastSetting(_EDITOR_MEDIA_PROBE_SECONDS),
    "CAST_EDITOR_MEDIA_UPLOAD_LOCK_SECONDS": CastSetting(_EDITOR_MEDIA_UPLOAD_LOCK_SECONDS),
    "CAST_STYLEGUIDE_GALLERY_CHUNK_SIZE": CastSetting(6),
    "CAST_STYLEGUIDE_TRANSCRIPT_EXCERPT_SEGMENTS": CastSetting(2),
    "CAST_STYLEGUIDE_BODY_GALLERY_LIMIT": CastSetting(1),
    "CAST_STYLEGUIDE_REMOTE_MEDIA": CastSetting(False),
    "CAST_STYLEGUIDE_PODCAST_SOURCE_URL": CastSetting(None),
    "CAST_STYLEGUIDE_TRANSCRIPT_SOURCE_URL": CastSetting(None),
    "CAST_STYLEGUIDE_VIDEO_SOURCE_URL": CastSetting(None),
    "CAST_STYLEGUIDE_REMOTE_TIMEOUT": CastSetting(8),
    "CAST_STYLEGUIDE_IMAGE_LIMIT": CastSetting(6),
    "CAST_STYLEGUIDE_GENERATE_RENDITIONS": CastSetting(False),
    "CAST_STYLEGUIDE_TRANSCRIPT_MAX_SEGMENTS": CastSetting(12),
    "CAST_STYLEGUIDE_IMAGE_SOURCE_URLS": CastSetting(None),
    "CAST_POST_BODY_BLOCKS": CastSetting(None),
    # Defaults for settings whose accessor lives in comments/appsettings.py
    # (it layers legacy FLUENT_* fallbacks on top of these).
    "CAST_COMMENTS_EXCLUDE_FIELDS": CastSetting(()),
    "CAST_COMMENTS_DEFAULT_MODERATOR": CastSetting("cast.moderation.Moderator"),
}

_DYNAMIC_SETTING_DEFAULTS: dict[str, Any] = {
    setting_name: cast_setting.default for setting_name, cast_setting in CAST_SETTING_REGISTRY.items()
}


if TYPE_CHECKING:
    CAST_COMMENTS_ENABLED: bool
    CAST_COMMENTS_ALLOW_AUTHOR_EDITS: bool
    CAST_COMMENTS_FORM_CSS_CLASS: str
    CAST_COMMENTS_LABEL_CSS_CLASS: str
    CAST_COMMENTS_FIELD_CSS_CLASS: str
    CAST_COMMENTS_OWNED_IDS_CAP: int
    CAST_COMMENTS_AUTHOR_EDIT_WINDOW: int
    CAST_COMMENTS_EDIT_RATE_LIMIT: int
    CAST_COMMENTS_EDIT_RATE_WINDOW: int
    CAST_CUSTOM_THEMES: list[tuple[str, str]]
    CAST_FOLLOW_LINKS: dict[str, str]
    CHOOSER_PAGINATION: int
    MENU_ITEM_PAGINATION: int
    POST_LIST_PAGINATION: int
    DELETE_WAGTAIL_IMAGES: bool
    CAST_FILTERSET_FACETS: list[str]
    CAST_IMAGE_FORMATS: list[str]
    CAST_REGULAR_IMAGE_SLOT_DIMENSIONS: list[tuple[int, int]]
    CAST_GALLERY_IMAGE_SLOT_DIMENSIONS: list[tuple[int, int]]
    CAST_GALLERY_THUMBNAIL_RENDITIONS_SRGB: bool
    CAST_REPOSITORY: str
    CAST_PODLOVE_PLAYER_THEMES: dict[str, Any]
    CAST_AUDIO_PLAYER: str
    CAST_EDITOR_SCOPES: dict[str, set[str]]
    CAST_PRIVATE_MEDIA_ROOT: str
    CAST_AUDIO_UPLOAD_MAX_BYTES: int
    CAST_VIDEO_UPLOAD_MAX_BYTES: int
    CAST_EDITOR_MEDIA_PROBE_SECONDS: int
    CAST_EDITOR_MEDIA_UPLOAD_LOCK_SECONDS: int
    CAST_STYLEGUIDE_GALLERY_CHUNK_SIZE: int
    CAST_STYLEGUIDE_TRANSCRIPT_EXCERPT_SEGMENTS: int
    CAST_STYLEGUIDE_BODY_GALLERY_LIMIT: int
    CAST_STYLEGUIDE_REMOTE_MEDIA: bool
    CAST_STYLEGUIDE_PODCAST_SOURCE_URL: str | None
    CAST_STYLEGUIDE_TRANSCRIPT_SOURCE_URL: str | None
    CAST_STYLEGUIDE_VIDEO_SOURCE_URL: str | None
    CAST_STYLEGUIDE_REMOTE_TIMEOUT: int
    CAST_STYLEGUIDE_IMAGE_LIMIT: int
    CAST_STYLEGUIDE_GENERATE_RENDITIONS: bool
    CAST_STYLEGUIDE_TRANSCRIPT_MAX_SEGMENTS: int
    CAST_STYLEGUIDE_IMAGE_SOURCE_URLS: list[str] | str | None
    CAST_POST_BODY_BLOCKS: dict[str, list[str]] | None
    CAST_COMMENTS_EXCLUDE_FIELDS: tuple[str, ...]
    CAST_COMMENTS_DEFAULT_MODERATOR: str


def __getattr__(name: str) -> Any:
    if name in CAST_SETTING_REGISTRY:
        value = getattr(settings, name, CAST_SETTING_REGISTRY[name].default)
        if isinstance(value, list | dict):
            return value.copy()
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


SettingValue = Union[str, bool, int]


def set_default_if_not_set(setting_name: str, default_value: SettingValue) -> None:
    if getattr(settings, setting_name, None) is None:
        setattr(settings, setting_name, default_value)


DEFAULT_VALUES: list[tuple[str, SettingValue]] = [
    ("SITE_ID", 1),
    ("WAGTAIL_SITE_NAME", "Cast"),
    ("CRISPY_TEMPLATE_PACK", "bootstrap4"),
    ("CRISPY_ALLOWED_TEMPLATE_PACKS", "bootstrap4"),
]


def init_cast_settings() -> None:
    if not getattr(settings, "DELETE_WAGTAIL_IMAGES", CAST_SETTING_REGISTRY["DELETE_WAGTAIL_IMAGES"].default):
        # Have a way to deactivate wagtails post_delete_file_cleanup
        # which deletes the file physically when developing against S3
        # cast has to be after wagtail in INSTALLED_APPS for this to work
        post_delete.disconnect(post_delete_file_cleanup, sender=get_image_model())

    for setting_name, default_value in DEFAULT_VALUES:
        set_default_if_not_set(setting_name, default_value)
