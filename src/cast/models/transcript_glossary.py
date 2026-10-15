"""Show-wide transcript glossary terms (see ``cast.transcripts.glossary`` for matching)."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _
from model_utils.models import TimeStampedModel

from ..transcripts.glossary import is_common_word, normalize_phrase, parse_term_variants
from .voxhelm_settings import VoxhelmSettings

if TYPE_CHECKING:
    from .index_pages import Podcast


def get_podcast_transcript_language(podcast: Podcast) -> str:
    """Language of the podcast's transcripts, used to pick the common-word list.

    The Voxhelm language hint wins, resolved like ``CAST_VOXHELM_LANGUAGE`` for
    Voxhelm jobs (site setting, then Django setting, then environment), because
    it is the language transcripts are requested in. Without a hint (or with
    "auto") the language of the podcast page's locale is used, which Wagtail
    derives from ``LANGUAGE_CODE``. The Voxhelm settings resolution is repeated
    here because model modules must not import ``cast.voxhelm``.
    """
    site = podcast.get_site()
    candidates = (
        VoxhelmSettings.for_site(site).language if site is not None else "",
        getattr(settings, "CAST_VOXHELM_LANGUAGE", None) or "",
        os.getenv("CAST_VOXHELM_LANGUAGE", ""),
    )
    for candidate in candidates:
        value = str(candidate).strip()
        if value:
            if value.casefold() != "auto":
                return value
            break
    return podcast.locale.language_code


class TranscriptGlossaryTerm(TimeStampedModel):
    """A canonical spelling for transcripts of one podcast, with optional misheard variants.

    A term without variants is a target for proposals an editor approves; each
    variant is replaced by the term automatically in the podcast's transcripts.
    """

    podcast = models.ForeignKey(
        "cast.Podcast",
        on_delete=models.CASCADE,
        related_name="transcript_glossary_terms",
        help_text=_("Podcast whose transcripts use this term."),
    )
    term = models.CharField(
        max_length=255,
        help_text=_('The correct spelling, for example "Gunicorn". Unique per podcast, ignoring case.'),
    )
    variants = models.TextField(
        blank=True,
        help_text=_(
            'Misspellings speech recognition produces for this term, one per line, for example "Gunacorn". '
            "Each variant is replaced by the term automatically in this podcast's transcripts, so list only "
            "phrases that are always wrong. Common words of the transcript language are refused."
        ),
    )
    notes = models.TextField(blank=True, help_text=_("Internal notes, never shown publicly."))

    class Meta:
        ordering = ["podcast_id", "term"]
        verbose_name = _("Transcript glossary term")
        verbose_name_plural = _("Transcript glossary terms")
        constraints = [
            models.UniqueConstraint(
                "podcast",
                Lower("term"),
                name="unique_podcast_transcript_glossary_term",
                violation_error_message=_("This podcast already has this term."),
            ),
        ]

    def __str__(self) -> str:
        return self.term

    @property
    def variant_list(self) -> list[str]:
        return parse_term_variants(self.variants)

    def variant_count(self) -> int:
        return len(self.variant_list)

    variant_count.short_description = _("Variants")  # type: ignore[attr-defined]

    def clean(self) -> None:
        super().clean()
        self.term = " ".join(self.term.split())
        if not self.term or self.podcast_id is None:
            return
        term_key = normalize_phrase(self.term)
        others = TranscriptGlossaryTerm.objects.filter(podcast_id=self.podcast_id).exclude(pk=self.pk)
        other_terms: dict[str, str] = {}
        other_variants: dict[str, str] = {}
        for other in others.only("term", "variants"):
            other_terms[normalize_phrase(other.term)] = other.term
            for variant in other.variant_list:
                other_variants[normalize_phrase(variant)] = other.term

        errors: dict[str, list[str]] = {}
        if term_key in other_terms:
            errors.setdefault("term", []).append(str(_("This podcast already has this term.")))
        elif term_key in other_variants:
            errors.setdefault("term", []).append(
                str(_('"%(term)s" is a variant of the term "%(other)s".'))
                % {"term": self.term, "other": other_variants[term_key]}
            )

        language = get_podcast_transcript_language(self.podcast)
        for variant in self.variant_list:
            key = normalize_phrase(variant)
            if key == term_key:
                message = str(_('"%(variant)s" is the term itself.')) % {"variant": variant}
            elif key in other_terms:
                message = str(_('"%(variant)s" is the term "%(other)s".')) % {
                    "variant": variant,
                    "other": other_terms[key],
                }
            elif key in other_variants:
                message = str(_('"%(variant)s" is already a variant of "%(other)s".')) % {
                    "variant": variant,
                    "other": other_variants[key],
                }
            elif is_common_word(variant, language):
                message = str(
                    _(
                        '"%(variant)s" is a common word in this podcast\'s transcript language (%(language)s) '
                        "and would be replaced everywhere. Leave it to the transcript review."
                    )
                ) % {"variant": variant, "language": language}
            else:
                continue
            errors.setdefault("variants", []).append(message)
        if errors:
            raise ValidationError(errors)
