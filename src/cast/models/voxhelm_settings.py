from __future__ import annotations

import json
from typing import Any

from django import forms
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import models, transaction
from django.utils.crypto import constant_time_compare, salted_hmac
from django.utils.html import format_html
from django.utils.safestring import SafeString
from django.utils.translation import gettext_lazy as _
from wagtail.admin.forms import WagtailAdminModelForm
from wagtail.admin.panels import FieldPanel
from wagtail.contrib.settings.models import BaseSiteSetting, register_setting

from ..media_derivation import normalize_model_save_arguments
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

    # The Voxhelm API base URL is deployment configuration only
    # (``CAST_VOXHELM_API_BASE`` as a Django setting or environment variable).
    # It is intentionally not editable here: a site-level URL let anyone with
    # the delegable settings permission point server-side requests elsewhere.
    api_token: models.CharField = models.CharField(
        blank=True,
        max_length=255,
        help_text=_(
            "Bearer token used for Voxhelm job submission and artifact access. The API base URL comes from the "
            "CAST_VOXHELM_API_BASE deployment setting."
        ),
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
        FieldPanel("api_token"),
        FieldPanel("clear_api_token"),
        FieldPanel("model"),
        FieldPanel("language"),
        FieldPanel("diarization_enabled"),
        FieldPanel("known_speaker_enabled"),
    ]

    class Meta:
        verbose_name = _("Voxhelm settings")

    def save(self, *args: Any, **kwargs: Any) -> None:
        intent = getattr(self, "_settings_save_intent", None)
        if intent is None:
            super().save(*args, **kwargs)
            return
        if self.pk is None:
            super().save(*args, **kwargs)
            del self._settings_save_intent
            return
        kwargs, using = normalize_model_save_arguments(self, args, kwargs)
        settings_version, token_version, replacement = intent
        with transaction.atomic(using=using):
            current = type(self).objects.using(using).filter(pk=self.pk)
            # Obtain the write lock before reading, including on SQLite.
            if not current.update(api_token=models.F("api_token")):
                raise VoxhelmSettingsConflict(SETTINGS_CONFLICT_MESSAGE)
            stored = current.get()
            if not constant_time_compare(settings_version, ordinary_settings_version(stored)):
                raise VoxhelmSettingsConflict(SETTINGS_CONFLICT_MESSAGE)
            if replacement is not None and api_token_version(stored.api_token) != token_version:
                raise VoxhelmSettingsConflict({"api_token": TOKEN_CONFLICT_MESSAGE})
            self.api_token = stored.api_token if replacement is None else replacement
            super().save(**kwargs)
        del self._settings_save_intent


class VoxhelmSettingsConflict(ValidationError):
    """A previously validated edit no longer matches persisted settings."""


SETTINGS_CONFLICT_MESSAGE = _("The Voxhelm settings changed. Reload settings before saving.")
TOKEN_CONFLICT_MESSAGE = _("The stored API token changed. Reload settings before replacing or removing it.")


def api_token_version(token: str) -> str:
    """Opaque fingerprint of a stored token; the form round-trips it instead of the secret."""
    return salted_hmac("cast.voxhelm.api_token_version", token).hexdigest()


def ordinary_settings_version(instance: VoxhelmSettings) -> str:
    """Fingerprint the persisted values and bind the snapshot to this settings row."""
    values = (
        instance.pk,
        instance.site_id,
        instance.model,
        instance.language,
        instance.diarization_enabled,
        instance.known_speaker_enabled,
    )
    return salted_hmac("cast.voxhelm.ordinary_settings_version", json.dumps(values), algorithm="sha256").hexdigest()


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


class TokenInput(forms.PasswordInput):
    """Never-prefilled token input that also carries the stored token's fingerprint."""

    version_name = ""
    version = ""

    def __init__(self, attrs: dict[str, str] | None = None) -> None:
        super().__init__(attrs, render_value=False)

    def render(self, name: str, value: Any, attrs: dict[str, Any] | None = None, renderer: Any = None) -> SafeString:
        html = super().render(name, value, attrs, renderer)
        if not self.version_name:
            return html
        return html + format_html('<input type="hidden" name="{}" value="{}">', self.version_name, self.version)


class VoxhelmSettingsForm(WagtailAdminModelForm):
    settings_version = forms.CharField(required=False, widget=forms.HiddenInput, strip=False, max_length=64)
    clear_api_token = forms.BooleanField(
        required=False,
        label=_("Remove stored API token"),
        help_text=_("Remove this site's token so the deployment CAST_VOXHELM_API_KEY applies."),
    )

    class Meta:
        widgets = {
            "api_token": TokenInput,
            "diarization_enabled": InheritableBooleanSelect,
            "known_speaker_enabled": InheritableBooleanSelect,
        }

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._initial_settings_version = ordinary_settings_version(self.instance)
        self.initial["settings_version"] = self._initial_settings_version
        # TokenInput renders the fingerprint of the token stored when the page was
        # rendered, so a replacement or removal from a page opened before another
        # administrator's change is refused. It is deliberately not a form field:
        # Wagtail would render an unclaimed field a second time, empty.
        rendered_version = api_token_version(self.instance.api_token)
        token_widget = self.fields["api_token"].widget
        if isinstance(token_widget, TokenInput):
            token_widget.version_name = self.add_prefix("api_token_version")
            token_widget.version = rendered_version
        posted_version = self.data.get(self.add_prefix("api_token_version"), "") if self.is_bound else ""
        self._original_api_token_version = posted_version or rendered_version
        self._describe_effective_boolean_settings()
        if self.instance.pk and self.instance.api_token:
            self.fields["api_token"].help_text = _(
                "A token is configured. The field is intentionally blank for security. Leave blank to keep the "
                "existing token, enter a new token to replace it, or tick the removal box below to delete it. "
                "The API base URL comes from the CAST_VOXHELM_API_BASE deployment setting."
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

    def clean_api_token(self) -> str:
        token = self.cleaned_data.get("api_token", "").strip()
        if token:
            return token
        return self.instance.api_token

    def clean(self) -> dict[str, object]:
        cleaned_data = super().clean()
        if not constant_time_compare(cleaned_data.get("settings_version", ""), self._initial_settings_version):
            self.add_error(None, SETTINGS_CONFLICT_MESSAGE)
        if cleaned_data.get("clear_api_token"):
            if self.data.get(self.add_prefix("api_token"), "").strip():
                self.add_error("clear_api_token", _("Either enter a new token or remove the stored one, not both."))
            else:
                cleaned_data["api_token"] = ""
        if self._token_replacement() is not None and self.instance.pk is not None:
            stored = (
                type(self.instance).objects.filter(pk=self.instance.pk).values_list("api_token", flat=True).first()
            )
            if stored is not None and api_token_version(stored) != self._original_api_token_version:
                self.add_error("api_token", TOKEN_CONFLICT_MESSAGE)
        return cleaned_data

    def _token_replacement(self) -> str | None:
        if self.cleaned_data.get("clear_api_token") or self.data.get(self.add_prefix("api_token"), "").strip():
            return str(self.cleaned_data.get("api_token", ""))
        return None

    def save(self, commit: bool = True) -> VoxhelmSettings:
        # Carry the submitted snapshots through Wagtail's save(commit=False) path.
        instance = super().save(commit=False)
        instance._settings_save_intent = (
            self.cleaned_data["settings_version"],
            self._original_api_token_version,
            self._token_replacement(),
        )
        if commit:
            instance.save()
            self.save_m2m()
        return instance

    def clean_model(self) -> str:
        return self.cleaned_data["model"].strip()

    def clean_language(self) -> str:
        return self.cleaned_data["language"].strip()


VoxhelmSettings.base_form_class = VoxhelmSettingsForm
