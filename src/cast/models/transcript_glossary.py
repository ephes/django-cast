"""Show-wide transcript glossary terms (see ``cast.transcripts.glossary`` for matching)."""

from __future__ import annotations

import os
from collections.abc import Iterable
from typing import TYPE_CHECKING

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _
from model_utils.models import TimeStampedModel
from wagtail.models import Site

from ..transcripts.glossary import is_common_word, normalize_phrase, parse_term_variants
from .voxhelm_settings import VoxhelmSettings

if TYPE_CHECKING:
    from .index_pages import Podcast


class GlossaryValidationContext:
    """Normalized namespace held by a caller owning the podcast write lock.

    Validation only reads this index. Accept a row after its write succeeds;
    rejected candidates must never release the previous row's spellings.
    """

    def __init__(self, language: str, terms: Iterable[TranscriptGlossaryTerm]) -> None:
        self.language = language
        self.terms: dict[str, dict[int, str]] = {}
        self.variants: dict[str, dict[int, str]] = {}
        self.keys: dict[int, tuple[str, list[str]]] = {}
        for term in terms:
            self.accept(term)

    @classmethod
    def for_podcast(cls, podcast: Podcast, terms: Iterable[TranscriptGlossaryTerm]) -> GlossaryValidationContext:
        return cls(get_podcast_transcript_language(podcast), terms)

    def accept(self, term: TranscriptGlossaryTerm) -> None:
        pk = term.pk
        assert pk is not None
        previous = self.keys.pop(pk, None)
        if previous is not None:
            term_key, variants = previous
            for index, keys in ((self.terms, [term_key]), (self.variants, variants)):
                for key in keys:
                    del index[key][pk]
                    if not index[key]:
                        del index[key]
        key = normalize_phrase(term.term)
        variants = [normalize_phrase(variant) for variant in term.variant_list]
        self.terms.setdefault(key, {})[pk] = term.term
        for variant in variants:
            self.variants.setdefault(variant, {})[pk] = term.term
        self.keys[pk] = (key, variants)

    @staticmethod
    def other_owner(index: dict[str, dict[int, str]], key: str, pk: int | None) -> str | None:
        # At most two owners are visited: the current row and one other row.
        return next((label for owner, label in reversed(index.get(key, {}).items()) if owner != pk), None)


def get_podcast_transcript_language(podcast: Podcast) -> str:
    """Language of the podcast's transcripts, used to pick the common-word list.

    The Voxhelm language hint wins, resolved like ``CAST_VOXHELM_LANGUAGE`` for
    Voxhelm jobs (site setting, then Django setting, then environment), because
    it is the language transcripts are requested in. Without a hint (or with
    "auto") the language of the podcast page's locale is used, which Wagtail
    derives from ``LANGUAGE_CODE``. The Voxhelm settings resolution is repeated
    here because model modules must not import ``cast.voxhelm``.
    """
    # Resolve the enclosing site on the owning database without Wagtail's global URL cache.
    paths = [podcast.path[:end] for end in range(podcast.steplen, len(podcast.path) + 1, podcast.steplen)]
    site = (
        Site.objects.using(podcast._state.db)
        .filter(root_page__path__in=paths)
        .order_by("-root_page__depth", "-is_default_site", "pk")
        .first()
    )
    language = (
        VoxhelmSettings.objects.using(podcast._state.db).filter(site=site).values_list("language", flat=True).first()
    )
    candidates = (
        language or "",
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

    _validation_context: GlossaryValidationContext | None = None

    def full_clean(
        self,
        exclude: Iterable[str] | None = None,
        validate_unique: bool = True,
        validate_constraints: bool = True,
        *,
        validation_context: GlossaryValidationContext | None = None,
    ) -> None:
        previous = self._validation_context
        self._validation_context = validation_context
        try:
            super().full_clean(exclude, validate_unique, validate_constraints)
        finally:
            self._validation_context = previous

    def clean(self) -> None:
        super().clean()
        self.term = " ".join(self.term.split())
        if not self.term or self.podcast_id is None:
            return
        context = self._validation_context
        if context is None:
            context = GlossaryValidationContext.for_podcast(
                self.podcast,
                TranscriptGlossaryTerm.objects.using(self._state.db)
                .filter(podcast_id=self.podcast_id)
                .only("term", "variants"),
            )
        self.clean_with_context(context)

    def clean_with_context(self, context: GlossaryValidationContext) -> None:
        """Check spellings against normalized data without database reads or writes."""
        term_key = normalize_phrase(self.term)
        other_term = context.other_owner(context.terms, term_key, self.pk)
        other_variant = context.other_owner(context.variants, term_key, self.pk)
        errors: dict[str, list[str]] = {}
        if other_term is not None:
            errors.setdefault("term", []).append(str(_("This podcast already has this term.")))
        elif other_variant is not None:
            errors.setdefault("term", []).append(
                str(_('"%(term)s" is a variant of the term "%(other)s".'))
                % {"term": self.term, "other": other_variant}
            )

        language = context.language
        for variant in self.variant_list:
            key = normalize_phrase(variant)
            other_term = context.other_owner(context.terms, key, self.pk)
            other_variant = context.other_owner(context.variants, key, self.pk)
            if key == term_key:
                message = str(_('"%(variant)s" is the term itself.')) % {"variant": variant}
            elif other_term is not None:
                message = str(_('"%(variant)s" is the term "%(other)s".')) % {
                    "variant": variant,
                    "other": other_term,
                }
            elif other_variant is not None:
                message = str(_('"%(variant)s" is already a variant of "%(other)s".')) % {
                    "variant": variant,
                    "other": other_variant,
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
