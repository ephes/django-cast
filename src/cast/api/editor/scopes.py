from __future__ import annotations

from typing import Any

_REQUIRED_SCOPE_UNSET = object()


def get_request_scopes(auth: Any) -> set[str] | None:
    """Read OAuth/IndieAuth-style scopes off ``request.auth``.

    Returns ``None`` only when there is no scope information at all (``auth is None`` or a
    token whose ``scope``/``scopes`` attributes are both absent or ``None``), which callers
    treat as "unscoped -> full authority, defer to Wagtail". A token that *advertises*
    scope info — even malformed or empty (``""``, ``[]``) — returns a (possibly empty) set
    that is matched against the requirement, so a present-but-empty scope fails closed
    rather than falling open to ``None``.
    """
    if auth is None:
        return None
    scope = getattr(auth, "scope", None)
    if isinstance(scope, str):
        # OAuth/IndieAuth convention: ``scope`` is a space-separated string ("" -> set()).
        return set(scope.split())
    scopes = getattr(auth, "scopes", None)
    if scopes is not None and not isinstance(scopes, (str, bytes)):
        # ``scopes`` is any iterable of scope strings (list, tuple, set, generator, ...).
        # ``str``/``bytes`` are excluded so they are not split into characters.
        try:
            return set(scopes)
        except TypeError:
            return set()  # present but not actually iterable -> malformed, fail closed
    if scope is None and scopes is None:
        # No scope information advertised at all -> unscoped, defer to Wagtail.
        return None
    # A scope attribute is present but malformed (a non-string ``scope``, or a
    # ``str``/``bytes``/non-iterable ``scopes``); fail closed rather than fall open.
    return set()
