"""Own django-cast's Wagtail publication boundary.

Publication rules run before Wagtail makes revision content live. Supported
post-publication effects remain on Wagtail's ``page_published`` signal so they
also cover live copies and alias updates that bypass the revision action.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext_lazy as _

if TYPE_CHECKING:
    from wagtail.models import Revision

    from cast.models.pages import Post


_PUBLISH_REVISION_PARAMETER_NAMES = ("revision", "object", "user", "changed", "log_action", "previous_revision")
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PublicationViolation:
    """One field-specific reason that a page cannot be published."""

    field: str
    code: str
    message: str


class PublicationRejected(ValidationError):
    """Structured validation failure shared by publication transports."""

    violations: tuple[PublicationViolation, ...]

    def __init__(self, violations: Iterable[PublicationViolation]) -> None:
        self.violations = tuple(violations)
        error_dict: dict[str, list[ValidationError]] = {}
        for violation in self.violations:
            error_dict.setdefault(violation.field, []).append(ValidationError(violation.message, code=violation.code))
        super().__init__(error_dict)

    def as_error_map(self) -> dict[str, list[dict[str, str]]]:
        """Return the editor API's field-error shape."""
        error_map: dict[str, list[dict[str, str]]] = {}
        for violation in self.violations:
            error_map.setdefault(violation.field, []).append({"code": violation.code, "message": violation.message})
        return error_map

    def as_form_error(self) -> ValidationError:
        """Return the field-error shape expected by Django forms."""
        error_map: dict[str, list[str]] = {}
        for violation in self.violations:
            error_map.setdefault(violation.field, []).append(violation.message)
        return ValidationError(error_map)


EPISODE_AUDIO_REQUIRED = _("An episode must have an audio file to be published.")


def episode_audio_violation(podcast_audio_id: int | None) -> PublicationViolation | None:
    """Return the episode audio rule violation, if any."""
    if podcast_audio_id is not None:
        return None
    return PublicationViolation(
        field="podcast_audio",
        code="required",
        message=str(EPISODE_AUDIO_REQUIRED),
    )


def violations_for(page: Post, *, revision: Revision | None = None) -> list[PublicationViolation]:
    """Return all publication-policy violations for the content going live."""
    from cast.models.pages import Episode

    del revision  # Reserved for rules that need revision metadata.
    violations = []
    if isinstance(page, Episode):
        violation = episode_audio_violation(page.podcast_audio_id)
        if violation is not None:
            violations.append(violation)
    return violations


def check_publishable(page: Post, *, revision: Revision | None = None) -> None:
    """Raise when the supplied page content violates publication policy."""
    violations = violations_for(page, revision=revision)
    if violations:
        raise PublicationRejected(violations)


def _validate_publish_revision_api(publish_revision: Any) -> None:
    if publish_revision is None:
        raise RuntimeError("Wagtail PublishRevisionAction._publish_revision is not available")
    parameters = inspect.signature(publish_revision).parameters
    missing_parameters = {"revision", "object", "previous_revision"} - set(parameters)
    if missing_parameters:
        missing = ", ".join(sorted(missing_parameters))
        raise RuntimeError(f"Unsupported Wagtail PublishRevisionAction._publish_revision API; missing {missing}")
    positional_parameters = tuple(name for name in parameters if name in _PUBLISH_REVISION_PARAMETER_NAMES)
    if positional_parameters != _PUBLISH_REVISION_PARAMETER_NAMES:
        raise RuntimeError("Unsupported Wagtail PublishRevisionAction._publish_revision positional parameter order")


def _publish_revision_and_object(
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> tuple[Revision, Any, Revision | None]:
    arguments = _publish_revision_arguments(args, kwargs)
    return arguments["revision"], arguments["object"], arguments.get("previous_revision")


def _publish_revision_arguments(args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    arguments = dict(zip(_PUBLISH_REVISION_PARAMETER_NAMES, args, strict=False))
    arguments.update(kwargs)
    return arguments


def _reject_scheduled_publication(revision: Revision, page: Post, rejection: PublicationRejected) -> None:
    from wagtail.log_actions import log

    revision.approved_go_live_at = None
    revision.save(update_fields=["approved_go_live_at"])
    log(instance=page, action="cast.publish.rejected", revision=revision)
    violation_codes = ", ".join(f"{violation.field}:{violation.code}" for violation in rejection.violations)
    logger.error(
        "Publication policy rejected scheduled publication for page %s revision %s: %s",
        page.pk,
        revision.pk,
        violation_codes,
    )


def publication_policy_installed() -> bool:
    """Return whether the guarded Wagtail publication wrapper is installed."""
    try:
        from wagtail.actions.publish_revision import PublishRevisionAction
    except ImportError:
        return False
    publish_revision = getattr(PublishRevisionAction, "_publish_revision", None)
    return bool(getattr(publish_revision, "_cast_publication_policy_hook", False))


def install_publication_policy() -> None:
    """Install the guarded Wagtail publication boundary."""
    from wagtail.signals import page_published

    from cast.post_media import prepare_published_post_media

    page_published.connect(prepare_published_post_media, dispatch_uid="cast.prepare_published_post_media")

    try:
        from wagtail.actions.publish_revision import PublishRevisionAction
    except ImportError as error:
        logger.warning("Publication policy publish hook was not installed: %s", error)
        return

    original = getattr(PublishRevisionAction, "_publish_revision", None)
    if getattr(original, "_cast_publication_policy_hook", False):
        return
    try:
        # Wagtail has no public pre-save publish hook that can update both the
        # revision content and live object, so this private hook is guarded.
        _validate_publish_revision_api(original)
    except RuntimeError as error:
        logger.warning("Publication policy publish hook was not installed: %s", error)
        return
    assert original is not None

    def publish_revision_with_policy(
        self: Any,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        from cast.models import Episode, Post
        from cast.podcast_numbering import assign_episode_number_for_publish

        arguments = _publish_revision_arguments(args, kwargs)
        revision = arguments["revision"]
        object_to_publish = arguments["object"]
        previous_revision = arguments.get("previous_revision")
        if isinstance(object_to_publish, Post):
            with transaction.atomic():
                try:
                    check_publishable(object_to_publish, revision=revision)
                except PublicationRejected as rejection:
                    if arguments.get("log_action") != "wagtail.publish.scheduled":
                        raise
                    _reject_scheduled_publication(revision, object_to_publish, rejection)
                    return None
                if isinstance(object_to_publish, Episode):
                    assign_episode_number_for_publish(
                        object_to_publish,
                        revision,
                        previous_revision=previous_revision,
                    )
                return original(self, *args, **kwargs)
        return original(self, *args, **kwargs)

    setattr(publish_revision_with_policy, "_cast_publication_policy_hook", True)
    setattr(publish_revision_with_policy, "_cast_publication_policy_original", original)
    PublishRevisionAction._publish_revision = publish_revision_with_policy  # type: ignore[method-assign]
