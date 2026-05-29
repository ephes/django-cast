from __future__ import annotations

from django import forms
from django.db import models
from django.utils.translation import gettext_lazy as _
from wagtail.admin.forms import WagtailAdminModelForm
from wagtail.admin.panels import FieldPanel
from wagtail.contrib.settings.models import BaseSiteSetting, register_setting


@register_setting(icon="cog")
class VoxhelmSettings(BaseSiteSetting):
    base_form_class: type[WagtailAdminModelForm] | None = None

    api_base: models.URLField = models.URLField(
        blank=True,
        help_text=_("Voxhelm service root or /v1 API base, for example https://voxhelm.example.com."),
        verbose_name=_("API base URL"),
    )
    api_token: models.CharField = models.CharField(
        blank=True,
        max_length=255,
        help_text=_("Bearer token used for Voxhelm job submission and artifact access."),
        verbose_name=_("API token"),
    )
    model: models.CharField = models.CharField(
        blank=True,
        default="",
        max_length=128,
        help_text=_('Optional Voxhelm model preference. Leave blank to use the default "auto".'),
    )
    language: models.CharField = models.CharField(
        blank=True,
        default="",
        max_length=32,
        help_text=_("Optional language hint sent to Voxhelm jobs."),
    )
    diarization_enabled: models.BooleanField = models.BooleanField(
        blank=True,
        default=None,
        help_text=_(
            "Leave unset to use Django settings or environment variables. Enable to request Voxhelm speaker "
            "diarization for this site. Disable to explicitly turn it off for this site."
        ),
        null=True,
        verbose_name=_("Speaker diarization"),
    )
    known_speaker_enabled: models.BooleanField = models.BooleanField(
        blank=True,
        default=None,
        help_text=_(
            "Leave unset to use Django settings or environment variables. Enable to send approved contributor "
            "voice references for known-speaker recognition when diarization runs. Returned speaker identities "
            "remain reviewable suggestions and are not shown publicly until approved."
        ),
        null=True,
        verbose_name=_("Known-speaker recognition"),
    )

    panels = [
        FieldPanel("api_base"),
        FieldPanel("api_token"),
        FieldPanel("model"),
        FieldPanel("language"),
        FieldPanel("diarization_enabled"),
        FieldPanel("known_speaker_enabled"),
    ]

    class Meta:
        verbose_name = _("Voxhelm settings")


class VoxhelmSettingsForm(WagtailAdminModelForm):
    class Meta:
        widgets = {
            "api_token": forms.PasswordInput(render_value=False),
        }

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        if self.instance.pk and self.instance.api_token:
            self.fields["api_token"].help_text = _(
                "A token is configured. The field is intentionally blank for security. Leave blank to keep the "
                "existing token, or enter a new token to replace it."
            )

    def clean_api_base(self) -> str:
        return self.cleaned_data["api_base"].strip()

    def clean_api_token(self) -> str:
        token = self.cleaned_data.get("api_token", "").strip()
        if token:
            return token
        return self.instance.api_token

    def clean_model(self) -> str:
        return self.cleaned_data["model"].strip()

    def clean_language(self) -> str:
        return self.cleaned_data["language"].strip()


VoxhelmSettings.base_form_class = VoxhelmSettingsForm
