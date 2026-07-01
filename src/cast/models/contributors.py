from typing import Any

from django import forms
from django.core.exceptions import ValidationError
from django.db import models
from django.http import HttpRequest
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from modelcluster.fields import ParentalKey
from modelcluster.models import ClusterableModel
from wagtail.admin.panels import FieldPanel, InlinePanel, MultiFieldPanel
from wagtail.models import Orderable
from wagtail.snippets.models import register_snippet

from ..form_widgets import PrivateClearableFileInput

CONTRIBUTOR_ROLE_HOST = "host"
CONTRIBUTOR_ROLE_GUEST = "guest"
CONTRIBUTOR_ROLE_CHOICES = (
    (CONTRIBUTOR_ROLE_HOST, _("Host")),
    (CONTRIBUTOR_ROLE_GUEST, _("Guest")),
)


@register_snippet
class Contributor(ClusterableModel):
    """Public person snippet used for podcast episode credits."""

    AVATAR_RENDITION_FILTER = "fill-80x80|format-webp"

    display_name = models.CharField(max_length=128, help_text=_("The public contributor name."))
    slug = models.SlugField(unique=True, help_text=_("Stable identifier for this contributor."))
    visible = models.BooleanField(
        default=True,
        help_text=_("Globally hide this contributor from public episode pages and podcast feeds."),
    )
    default_role = models.CharField(
        max_length=32,
        choices=CONTRIBUTOR_ROLE_CHOICES,
        default=CONTRIBUTOR_ROLE_GUEST,
        help_text=_("Default role to use when this contributor is added to an episode."),
    )
    avatar = models.ForeignKey(
        "wagtailimages.Image",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text=_("Optional public contributor avatar."),
    )
    short_bio = models.TextField(blank=True, help_text=_("Optional short public biography."))

    panels = [
        FieldPanel("display_name"),
        FieldPanel("slug"),
        FieldPanel("visible"),
        FieldPanel("default_role"),
        FieldPanel("avatar"),
        FieldPanel("short_bio"),
        MultiFieldPanel(
            [InlinePanel("links", label=_("Link"))],
            heading=_("Links"),
        ),
        MultiFieldPanel(
            [InlinePanel("voice_references", label=_("Voice reference"))],
            heading=_("Voice references (private)"),
        ),
    ]

    class Meta:
        ordering = ["display_name"]

    def __str__(self) -> str:
        return self.display_name

    def get_avatar_url(self, request: HttpRequest | None = None) -> str:
        if self.avatar is None:
            return ""
        avatar_url = self.avatar.file.url
        if request is not None and hasattr(request, "build_absolute_uri"):
            return request.build_absolute_uri(avatar_url)
        return avatar_url

    def get_avatar_rendition_url(self, request: HttpRequest | None = None) -> str:
        cached = getattr(self, "_avatar_rendition_url", None)
        if cached is None:
            cached = self._compute_avatar_rendition_url()
            self._avatar_rendition_url = cached
        if cached and request is not None and hasattr(request, "build_absolute_uri"):
            return request.build_absolute_uri(cached)
        return cached

    def _compute_avatar_rendition_url(self) -> str:
        if self.avatar is None:
            return ""
        return self.avatar.get_rendition(self.AVATAR_RENDITION_FILTER).url


def get_voice_reference_storage():
    """Return the storage backend for private contributor voice-reference clips.

    Production deployments should configure a protected (non-public) storage
    backend under the ``"cast_voice_references"`` alias in ``STORAGES`` so that
    reference clips are not served from public media. When the alias is absent,
    django-cast falls back to the private media storage backend instead of
    default public media storage.
    """
    from django.core.files.storage import InvalidStorageError, storages

    from ..private_storage import get_private_media_storage

    try:
        return storages["cast_voice_references"]
    except InvalidStorageError:
        return get_private_media_storage()


class ContributorVoiceReferenceQuerySet(models.QuerySet):
    def approved(self) -> "ContributorVoiceReferenceQuerySet":
        return self.filter(status=ContributorVoiceReference.Status.APPROVED)

    def usable_known_speaker(self) -> "ContributorVoiceReferenceQuerySet":
        """Approved references whose contributor may drive public transcript names.

        Hidden contributors are excluded unless an editor explicitly opted the
        reference into known-speaker use through ``allow_for_hidden_contributor``.
        """
        return self.approved().filter(
            models.Q(contributor__visible=True) | models.Q(allow_for_hidden_contributor=True)
        )


class ContributorVoiceReference(Orderable):
    """Private, admin-only voice-reference material for a contributor.

    A reference is either an uploaded/managed clip or a source range into
    existing audio, never both. References are sensitive editorial data and must
    not be exposed through public contributor APIs, feeds, theme context,
    repository serialization, static exports, or public transcript output.
    """

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        APPROVED = "approved", _("Approved")
        DISABLED = "disabled", _("Disabled")
        REJECTED = "rejected", _("Rejected")

    contributor = ParentalKey(Contributor, related_name="voice_references", on_delete=models.CASCADE)
    title = models.CharField(max_length=128, blank=True, help_text=_("Optional internal label for this reference."))
    source_audio = models.ForeignKey(
        "cast.Audio",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text=_("Audio the source range points into. Required for source-range references."),
    )
    source_episode = models.ForeignKey(
        "cast.Episode",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text=_("Optional episode this reference was captured from, for editorial context."),
    )
    clip = models.FileField(
        upload_to="cast_voice_references/",
        storage=get_voice_reference_storage,
        null=True,
        blank=True,
        help_text=_("Uploaded clean solo clip. Use protected storage; do not expose publicly."),
    )
    start_seconds = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    end_seconds = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.PENDING,
        help_text=_("References start as pending and must be approved before Voxhelm use."),
    )
    consent_confirmed = models.BooleanField(
        default=False,
        help_text=_("Confirms the contributor consented to voice-reference use. Required to approve."),
    )
    allow_for_hidden_contributor = models.BooleanField(
        default=False,
        help_text=_("Allow known-speaker use for public transcripts even if the contributor is hidden."),
    )
    notes = models.TextField(blank=True, help_text=_("Optional reviewer notes."))

    objects = ContributorVoiceReferenceQuerySet.as_manager()

    panels = [
        FieldPanel("title"),
        FieldPanel("clip", widget=PrivateClearableFileInput),
        FieldPanel("source_audio"),
        FieldPanel("source_episode"),
        FieldPanel("start_seconds"),
        FieldPanel("end_seconds"),
        FieldPanel("status"),
        FieldPanel("consent_confirmed"),
        FieldPanel("allow_for_hidden_contributor"),
        FieldPanel("notes"),
    ]

    class Meta(Orderable.Meta):
        verbose_name = _("Contributor voice reference")
        verbose_name_plural = _("Contributor voice references")
        ordering = ["sort_order"]

    def __str__(self) -> str:
        label = self.title or (_("source range") if self.is_source_range else _("clip"))
        return f"{self.contributor.display_name}: {label} ({self.get_status_display()})"

    @property
    def is_source_range(self) -> bool:
        return self.start_seconds is not None and self.end_seconds is not None

    @property
    def is_usable_for_voxhelm(self) -> bool:
        return self.status == self.Status.APPROVED

    def clean(self) -> None:
        super().clean()
        has_clip = bool(self.clip)
        has_range_bounds = self.start_seconds is not None or self.end_seconds is not None
        if has_clip and has_range_bounds:
            raise ValidationError(_("Provide either an uploaded clip or a source range, not both."))
        if not has_clip and not has_range_bounds:
            raise ValidationError(_("Provide either an uploaded clip or a source range."))
        if has_range_bounds:
            if self.start_seconds is None or self.end_seconds is None:
                raise ValidationError(_("A source range needs both a start and an end time."))
            if self.source_audio_id is None:
                raise ValidationError(_("A source range needs source audio."))
            if self.start_seconds >= self.end_seconds:
                raise ValidationError(_("The source range start time must be before its end time."))
        if self.status == self.Status.APPROVED and not self.consent_confirmed:
            raise ValidationError(_("Approving a voice reference requires confirmed consent."))

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.clean()
        super().save(*args, **kwargs)


class ContributorLink(Orderable):
    """Ordered public link/profile for a contributor."""

    SERVICE_WEBSITE = "website"
    SERVICE_GITHUB = "github"
    SERVICE_MASTODON = "mastodon"
    SERVICE_TWITTER = "twitter"
    SERVICE_LINKEDIN = "linkedin"
    SERVICE_YOUTUBE = "youtube"
    SERVICE_CHOICES = (
        (SERVICE_WEBSITE, _("Website")),
        (SERVICE_GITHUB, _("GitHub")),
        (SERVICE_MASTODON, _("Mastodon")),
        (SERVICE_TWITTER, _("Twitter/X")),
        (SERVICE_LINKEDIN, _("LinkedIn")),
        (SERVICE_YOUTUBE, _("YouTube")),
    )

    contributor = ParentalKey(Contributor, related_name="links", on_delete=models.CASCADE)
    service = models.CharField(max_length=32, choices=SERVICE_CHOICES, default=SERVICE_WEBSITE)
    url = models.URLField(max_length=500)

    panels = [
        FieldPanel("service"),
        FieldPanel("url"),
    ]

    class Meta(Orderable.Meta):
        verbose_name = _("Contributor link")
        verbose_name_plural = _("Contributor links")
        ordering = ["sort_order"]

    def __str__(self) -> str:
        return f"{self.contributor.display_name}: {self.get_service_display()}"

    def clean(self) -> None:
        super().clean()
        self._validate_episode_assignments_match_contributor()

    def save(self, *args: Any, **kwargs: Any) -> None:
        self._validate_episode_assignments_match_contributor()
        super().save(*args, **kwargs)

    def _validate_episode_assignments_match_contributor(self) -> None:
        if self.pk is None or self.contributor_id is None:
            return
        mismatching_assignments = EpisodeContributor.objects.filter(link_id=self.pk).exclude(
            contributor_id=self.contributor_id
        )
        if mismatching_assignments.exists():
            raise ValidationError(
                {
                    "contributor": _(
                        "This link is used by episode assignments for another contributor. "
                        "Remove those assignments before reassigning it."
                    )
                }
            )


class ContributorLinkSelect(forms.Select):
    """Select widget that exposes contributor ownership to the episode admin JS."""

    def __init__(self, attrs: dict[str, Any] | None = None) -> None:
        default_attrs: dict[str, Any] = {
            "data-cast-contributor-link-select": "true",
            "data-cast-contributor-link-options-url": reverse_lazy("cast-contributors:links"),
        }
        default_attrs.update(attrs or {})
        super().__init__(attrs=default_attrs)

    def create_option(
        self,
        name: str,
        value: Any,
        label: int | str,
        selected: bool,
        index: int,
        subindex: int | None = None,
        attrs: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        option = super().create_option(name, value, label, selected, index, subindex=subindex, attrs=attrs)
        link = getattr(value, "instance", None)
        if link is not None:
            option["attrs"]["data-cast-contributor-id"] = str(link.contributor_id)
        return option

    class Media:
        js = ["cast/js/wagtail/contributor-link-select.js"]


class EpisodeContributor(Orderable):
    """Ordered contributor assignment for a podcast episode."""

    ROLE_HOST = CONTRIBUTOR_ROLE_HOST
    ROLE_GUEST = CONTRIBUTOR_ROLE_GUEST
    ROLE_CHOICES = CONTRIBUTOR_ROLE_CHOICES

    episode = ParentalKey("cast.Episode", related_name="contributor_assignments", on_delete=models.CASCADE)
    contributor = models.ForeignKey(Contributor, on_delete=models.PROTECT, related_name="episode_assignments")
    role = models.CharField(max_length=32, choices=ROLE_CHOICES, default=ROLE_GUEST)
    link = models.ForeignKey(
        ContributorLink,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
        help_text=_("Optional contributor link to use for this episode and feed item."),
    )

    panels = [
        FieldPanel("contributor"),
        FieldPanel("role"),
        FieldPanel("link", widget=ContributorLinkSelect),
    ]

    class Meta(Orderable.Meta):
        verbose_name = _("Episode contributor")
        verbose_name_plural = _("Episode contributors")
        ordering = ["sort_order"]
        constraints = [
            models.UniqueConstraint(fields=["episode", "contributor", "role"], name="unique_episode_contributor_role"),
        ]

    def __str__(self) -> str:
        return f"{self.contributor.display_name} ({self.get_role_display()})"

    def clean(self) -> None:
        super().clean()
        link = self.link
        if link is not None and self.contributor_id is not None and link.contributor_id != self.contributor_id:
            raise ValidationError({"link": _("The selected link must belong to the selected contributor.")})

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.clean()
        super().save(*args, **kwargs)

    @property
    def display_name(self) -> str:
        return self.contributor.display_name

    @property
    def href(self) -> str:
        if self.link is None:
            return ""
        return self.link.url

    def get_avatar_url(self, request: HttpRequest | None = None) -> str:
        return self.contributor.get_avatar_url(request)

    def get_avatar_rendition_url(self, request: HttpRequest | None = None) -> str:
        return self.contributor.get_avatar_rendition_url(request)
