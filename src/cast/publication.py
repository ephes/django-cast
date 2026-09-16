from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

if TYPE_CHECKING:
    from wagtail.models import Revision

    from cast.models.pages import Post


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
