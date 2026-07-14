"""
Resolve the ``CAST_ENABLE_DEV_TOOLS`` setting with backwards compatibility
for the deprecated ``CAST_ENABLE_STYLEGUIDE`` alias.

Precedence:

* If only ``CAST_ENABLE_STYLEGUIDE`` is set → use its value, emit
  ``DeprecationWarning``.
* If only ``CAST_ENABLE_DEV_TOOLS`` is set → use its value, no warning.
* If **both** are set → ``CAST_ENABLE_DEV_TOOLS`` wins, emit
  ``DeprecationWarning`` telling the user to remove the old setting.
* If **neither** is set → default ``False``.
"""

import warnings

from django.conf import settings


def dev_tools_enabled() -> bool:
    """Return whether dev-only views (styleguide, components, health, theme-compare) should be active."""
    has_old = hasattr(settings, "CAST_ENABLE_STYLEGUIDE")
    has_new = hasattr(settings, "CAST_ENABLE_DEV_TOOLS")

    if has_old and has_new:
        warnings.warn(
            "Both CAST_ENABLE_STYLEGUIDE and CAST_ENABLE_DEV_TOOLS are set. "
            "CAST_ENABLE_DEV_TOOLS takes precedence. "
            "Please remove CAST_ENABLE_STYLEGUIDE from your settings.",
            DeprecationWarning,
            stacklevel=2,
        )
        return bool(getattr(settings, "CAST_ENABLE_DEV_TOOLS", False))

    if has_new:
        return bool(getattr(settings, "CAST_ENABLE_DEV_TOOLS", False))

    if has_old:
        warnings.warn(
            "CAST_ENABLE_STYLEGUIDE is deprecated. Use CAST_ENABLE_DEV_TOOLS instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return bool(getattr(settings, "CAST_ENABLE_STYLEGUIDE", False))

    return False
