from __future__ import annotations

from typing import Any

from rest_framework import status
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from ... import appsettings
from .errors import EditorFlatError

_REQUIRED_SCOPE_UNSET = object()
_NON_SCOPED_METHODS = frozenset({"OPTIONS", "HEAD"})


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


class HasEditorScope(BasePermission):
    """Enforce the per-method ``required_scopes`` mapping against ``request.auth`` scopes.

    Scope is necessary, not sufficient — the view body still runs Wagtail permission
    checks. Session auth (``request.auth is None``) and unscoped tokens defer to those
    Wagtail checks. A served method missing a ``required_scopes`` entry fails closed.
    """

    message = "Your token lacks the scope required for this action."

    def has_permission(self, request: Request, view: APIView) -> bool:
        if request.method in _NON_SCOPED_METHODS:
            return True
        required = getattr(view, "required_scopes", {}).get(request.method, _REQUIRED_SCOPE_UNSET)
        if required is _REQUIRED_SCOPE_UNSET:
            # An editor method without an explicit scope declaration is a configuration
            # error; fail closed so a forgotten declaration can never bypass enforcement.
            raise EditorFlatError(
                "insufficient_scope",
                "This action has no configured scope requirement.",
                status_code=status.HTTP_403_FORBIDDEN,
            )
        if required is None:
            return True
        scopes = get_request_scopes(request.auth)
        if scopes is None:
            # Unscoped token or session auth: defer to Wagtail permissions.
            return True
        accepted = appsettings.CAST_EDITOR_SCOPES.get(required, set())
        if scopes & accepted:
            return True
        raise EditorFlatError(
            "insufficient_scope",
            f"This action requires the {required!r} scope.",
            status_code=status.HTTP_403_FORBIDDEN,
        )
