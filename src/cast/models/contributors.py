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
        FieldPanel("avatar"),
        FieldPanel("short_bio"),
        MultiFieldPanel(
            [InlinePanel("links", label=_("Link"))],
            heading=_("Links"),
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

    ROLE_HOST = "host"
    ROLE_GUEST = "guest"
    ROLE_CHOICES = (
        (ROLE_HOST, _("Host")),
        (ROLE_GUEST, _("Guest")),
    )

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
