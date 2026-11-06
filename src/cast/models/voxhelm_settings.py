from __future__ import annotations

from django import forms
from django.core.exceptions import ImproperlyConfigured
from django.db import models
from django.utils.translation import gettext_lazy as _
from wagtail.admin.forms import WagtailAdminModelForm
from wagtail.admin.panels import FieldPanel
from wagtail.contrib.settings.models import BaseSiteSetting, register_setting

from ..setting_resolution import (
    SETTING_SOURCE_DEFAULT,
    SETTING_SOURCE_DJANGO,
    SETTING_SOURCE_ENVIRONMENT,
    SETTING_SOURCE_SITE,
    parse_bool_setting,
    resolve_layered_setting,
)


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


class InheritableBooleanSelect(forms.NullBooleanSelect):
    """Tri-state select whose empty choice reads as "inherit", not as an unknown value."""

    def __init__(self, attrs: dict[str, str] | None = None) -> None:
        super().__init__(attrs)
        self.choices = [
            ("unknown", _("Not set here: use the Django setting or environment variable")),
            ("true", _("Enabled for this site (overrides Django settings and environment)")),
            ("false", _("Disabled for this site (overrides Django settings and environment)")),
        ]


INHERITABLE_BOOLEAN_SETTINGS = {
    "diarization_enabled": "CAST_VOXHELM_DIARIZATION_ENABLED",
    "known_speaker_enabled": "CAST_VOXHELM_KNOWN_SPEAKER_ENABLED",
}


class VoxhelmSettingsForm(WagtailAdminModelForm):
    class Meta:
        widgets = {
            "api_token": forms.PasswordInput(render_value=False),
            "diarization_enabled": InheritableBooleanSelect,
            "known_speaker_enabled": InheritableBooleanSelect,
        }

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._describe_effective_boolean_settings()
        if self.instance.pk and self.instance.api_token:
            self.fields["api_token"].help_text = _(
                "A token is configured. The field is intentionally blank for security. Leave blank to keep the "
                "existing token when the API base URL remains set and unchanged, or enter a new token to replace it. "
                "Saving with both credential fields blank removes the stored token."
            )

    def _describe_effective_boolean_settings(self) -> None:
        """Append the value each tri-state boolean currently resolves to, and from which level."""
        source_labels = {
            SETTING_SOURCE_DJANGO: _("Django setting"),
            SETTING_SOURCE_ENVIRONMENT: _("environment variable"),
            SETTING_SOURCE_DEFAULT: _("built-in default"),
        }
        for field_name, setting_name in INHERITABLE_BOOLEAN_SETTINGS.items():
            field = self.fields.get(field_name)
            if field is None:
                continue
            try:
                resolved, resolved_source = resolve_layered_setting(
                    setting_name, getattr(self.instance, field_name), False
                )
                value, source = parse_bool_setting(setting_name, resolved, resolved_source, False)
            except ImproperlyConfigured as exc:
                effective = _("Currently invalid: %(error)s") % {"error": exc}
            else:
                state = _("enabled") if value else _("disabled")
                if source == SETTING_SOURCE_SITE:
                    effective = _("Currently %(state)s by this site setting.") % {"state": state}
                else:
                    effective = _("Currently %(state)s by the %(source)s %(setting)s.") % {
                        "state": state,
                        "source": source_labels[source],
                        "setting": setting_name,
                    }
            field.help_text = f"{field.help_text} {effective}"

    def clean_api_base(self) -> str:
        return self.cleaned_data["api_base"].strip()

    def clean_api_token(self) -> str:
        token = self.cleaned_data.get("api_token", "").strip()
        if token:
            return token
        if self.cleaned_data.get("api_base") == "":
            return ""
        if self.cleaned_data.get("api_base", self.instance.api_base) != self.instance.api_base:
            raise forms.ValidationError(_("Enter the API token when changing the API base URL."))
        return self.instance.api_token

    def clean_model(self) -> str:
        return self.cleaned_data["model"].strip()

    def clean_language(self) -> str:
        return self.cleaned_data["language"].strip()


VoxhelmSettings.base_form_class = VoxhelmSettingsForm
