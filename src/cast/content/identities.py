"""Scoped StreamField identity lookup for author conversions."""

from typing import Any, TypeGuard


def valid_identity(identity: Any) -> TypeGuard[str]:
    return isinstance(identity, str) and 0 < len(identity) <= 64


def unique_identities(entries: list[Any]) -> dict[str, int | None]:
    """Map each valid stored ID to its index, or ``None`` when the list repeats it."""
    identities: dict[str, int | None] = {}
    for index, stored in enumerate(entries):
        identity = stored.get("id") if isinstance(stored, dict) else None
        if valid_identity(identity):
            identities[identity] = None if identity in identities else index
    return identities
