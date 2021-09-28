from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string


def get_custom_form(form_setting):
    """Return custom form class if defined and available"""
    try:
        return import_string(getattr(settings, form_setting))
    except ImportError:
        raise ImproperlyConfigured(
            f"{form_setting} refers to a form '{getattr(settings, form_setting)}' that is not available"
        )
