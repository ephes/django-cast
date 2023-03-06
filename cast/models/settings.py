from django.db import models
from django.utils.translation import gettext_lazy as _
from wagtail.contrib.settings.models import BaseSiteSetting, register_setting


class TemplateName(models.TextChoices):
    BOOTSTRAP4 = "bootstrap4", _("Bootstrap 4")
    PLAIN = "plain", _("Just HTML")


@register_setting
class TemplateBaseDirectory(BaseSiteSetting):
    """
    The base directory for templates. Makes it possible to use different
    templates for different sites / change look and feel of the site from
    the wagtail admin.
    """

    name = models.CharField(choices=TemplateName.choices, max_length=10, default=TemplateName.BOOTSTRAP4)
