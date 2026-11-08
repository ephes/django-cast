"""Drop the admin-editable Voxhelm API base URL.

The Voxhelm API base is deployment configuration only
(``CAST_VOXHELM_API_BASE`` as a Django setting or environment variable). Before
the column is dropped, every stored site value that differs from the deployment
value is reported as a warning so operators can move it into deploy config.
"""

import logging
import os
from urllib.parse import urlsplit

from django.conf import settings
from django.db import migrations, models

logger = logging.getLogger("cast.migrations")

SETTING_NAME = "CAST_VOXHELM_API_BASE"


def _deployment_api_base() -> str:
    """Mirror the runtime resolution: a Django credential pair wins over the environment."""
    names = (SETTING_NAME, "CAST_VOXHELM_API_KEY")
    if any(getattr(settings, name, None) not in {None, ""} for name in names):
        value = getattr(settings, SETTING_NAME, None)
    else:
        value = os.environ.get(SETTING_NAME)
    return value.strip() if isinstance(value, str) else ""


def _redacted(url: str) -> str:
    """Return ``url`` without userinfo, query or fragment, safe for logs."""
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        port = f":{parts.port}" if parts.port else ""
    except ValueError:
        return "<unparseable URL>"
    return f"{parts.scheme}://{host}{port}{parts.path}"


def _normalized(url: str) -> str:
    stripped = url.strip().rstrip("/")
    return stripped[: -len("/v1")] if stripped.endswith("/v1") else stripped


def warn_about_stored_api_bases(apps, schema_editor):
    VoxhelmSettings = apps.get_model("cast", "VoxhelmSettings")
    deployment = _deployment_api_base()
    rows = VoxhelmSettings.objects.using(schema_editor.connection.alias).exclude(api_base="")
    for row in rows.values("site_id", "api_base", "api_token"):
        stored = row["api_base"].strip()
        if not stored or _normalized(stored) == _normalized(deployment):
            continue
        if deployment:
            consequence = f"Voxhelm requests will use the deployment {SETTING_NAME} ({_redacted(deployment)})."
        else:
            consequence = f"Voxhelm transcript generation stays disabled until {SETTING_NAME} is set in deploy config."
        token_note = " A site API token is still stored and will be sent to that base." if row["api_token"] else ""
        logger.warning(
            "Removing the Voxhelm site setting API base %s for site %s: it differs from the deployment %s. %s%s",
            _redacted(stored),
            row["site_id"],
            SETTING_NAME,
            consequence,
            token_note,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("cast", "0087_transcriptgeneration_attempt_id"),
    ]

    operations = [
        migrations.RunPython(warn_about_stored_api_bases, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="voxhelmsettings",
            name="api_base",
        ),
        migrations.AlterField(
            model_name="voxhelmsettings",
            name="api_token",
            field=models.CharField(
                blank=True,
                help_text=(
                    "Bearer token used for Voxhelm job submission and artifact access. The API base URL comes from "
                    "the CAST_VOXHELM_API_BASE deployment setting."
                ),
                max_length=255,
                verbose_name="API token",
            ),
        ),
    ]
