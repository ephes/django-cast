from __future__ import annotations

from typing import TYPE_CHECKING

import django_comments
from django.apps import apps
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import transaction
from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseForbidden,
    HttpResponseNotFound,
    JsonResponse,
)
from django.template.loader import render_to_string
from django.utils.html import escape
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST
from django_comments import signals
from django_comments.forms import COMMENT_MAX_LENGTH
from django_comments.views.comments import CommentPostBadRequest

from . import appsettings, author_edits
from .utils import get_comment_context_data, get_comment_template_name

if TYPE_CHECKING:
    from django.forms.boundfield import BoundField

    from .forms import CastCommentForm
    from .models import BaseComment


@csrf_protect
@require_POST
def post_comment_ajax(request: HttpRequest, using: str | None = None) -> HttpResponse:
    is_ajax = request.headers.get("x-requested-with") == "XMLHttpRequest"
    if not is_ajax:
        return HttpResponseBadRequest("Expecting Ajax call")

    data = request.POST.copy()
    if request.user.is_authenticated:
        if not data.get("name", ""):
            data["name"] = request.user.get_full_name() or request.user.username
        if not data.get("email", ""):
            data["email"] = request.user.email

    ctype = data.get("content_type")
    object_pk = data.get("object_pk")
    if ctype is None or object_pk is None:
        return CommentPostBadRequest("Missing content_type or object_pk field.")

    try:
        app_label, dot, model_name = ctype.partition(".")
        if dot:
            model = apps.get_model(app_label, model_name)
        else:
            model = apps.get_model(app_label)
        target = model._default_manager.using(using).get(pk=object_pk)
    except ValueError:
        return CommentPostBadRequest(f"Invalid object_pk value: {escape(object_pk)}")
    except (TypeError, LookupError):
        return CommentPostBadRequest(f"Invalid content_type value: {escape(ctype)}")
    except AttributeError:
        return CommentPostBadRequest(f"The given content-type {escape(ctype)} does not resolve to a valid model.")
    except ObjectDoesNotExist:
        return CommentPostBadRequest(
            f"No object matching content-type {escape(ctype)} and object PK {escape(object_pk)} exists."
        )
    except (ValueError, ValidationError) as exc:
        return CommentPostBadRequest(
            "Attempting to get content-type {!r} and object PK {!r} exists raised {}".format(
                escape(ctype), escape(object_pk), exc.__class__.__name__
            )
        )

    is_preview = "preview" in data
    form = django_comments.get_form()(target, data=data, is_preview=is_preview)

    if form.security_errors():
        return CommentPostBadRequest(f"The comment form failed security verification: {form.security_errors()}")

    if is_preview:
        comment = form.get_comment_object() if not form.errors else None
        return _ajax_result(request, form, "preview", comment, object_id=object_pk)
    if form.errors:
        return _ajax_result(request, form, "post", object_id=object_pk)

    comment = form.get_comment_object()
    comment.ip_address = request.META.get("REMOTE_ADDR", None)
    if request.user.is_authenticated:
        comment.user = request.user

    responses = signals.comment_will_be_posted.send(sender=comment.__class__, comment=comment, request=request)
    for receiver, response in responses:
        if response is False:
            return CommentPostBadRequest(f"comment_will_be_posted receiver {receiver.__name__} killed the comment")

    feature_on = author_edits.author_edits_enabled()
    parent_id = getattr(comment, "parent_id", None)

    if feature_on and parent_id:
        # Coordinate with delete on the parent row: lock it and reject a reply to
        # a parent that is no longer a valid target (removed or author-deleted), so
        # no child is created under a deleted parent. (An *edited* but still-public
        # parent correctly accepts replies — the invariant is that a comment is
        # never edited or deleted *after* a reply exists, which the edit/delete
        # path enforces via its own re-check.)
        comment_model = django_comments.get_model()
        with transaction.atomic(using=using):
            try:
                parent = comment_model.objects.using(using).select_for_update().get(pk=parent_id)
            except comment_model.DoesNotExist:
                return CommentPostBadRequest("The parent comment no longer exists.")
            if not parent.is_public or parent.is_removed:
                return CommentPostBadRequest("The parent comment is no longer available.")
            comment.save(using=using)
    else:
        comment.save(using=using)

    # Sent after the comment is committed (outside the lock transaction) so
    # receivers do not run for a transaction that could still roll back. The
    # comment_was_posted receiver records session ownership for all post paths.
    signals.comment_was_posted.send(sender=comment.__class__, comment=comment, request=request)
    return _ajax_result(request, form, "post", comment, object_id=object_pk)


def _ajax_result(
    request: HttpRequest,
    form: CastCommentForm,
    action: str,
    comment: BaseComment | None = None,
    object_id: str | None = None,
) -> HttpResponse:
    success = True
    json_errors: dict[str, str] = {}

    if form.errors:
        for field_name in form.errors:
            field = form[field_name]
            json_errors[field_name] = _render_errors(field)
        success = False

    json_return: dict[str, object] = {
        "success": success,
        "action": action,
        "errors": json_errors,
        "object_id": object_id,
        "use_threadedcomments": bool(appsettings.USE_THREADEDCOMMENTS),
    }

    if comment is not None:
        context = get_comment_context_data(comment, action)
        context["request"] = request
        # A freshly saved comment is inserted client-side from this html, so it
        # must already carry the owner's edit/delete controls and raw-text source
        # (ownership was recorded just before this on the post path). Skipped for
        # unsaved previews (pk is None), which must not show controls.
        if getattr(comment, "pk", None) is not None:
            context.update(author_edits.comment_action_context(request, comment))
        template_name = get_comment_template_name(comment)
        comment_html = render_to_string(template_name, context, request=request)

        parent_id = getattr(comment, "parent_id", None)
        json_return.update(
            {
                "html": comment_html,
                # Serialize ids as strings so non-integer comment PKs (e.g. UUIDs)
                # round-trip safely to the client.
                "comment_id": str(comment.pk),
                "parent_id": str(parent_id) if parent_id is not None else None,
            }
        )
        if request.user.is_staff:
            json_return["is_moderated"] = not bool(getattr(comment, "is_public", True))

    return JsonResponse(json_return)


def _render_errors(field: BoundField) -> str:
    template = f"{appsettings.CRISPY_TEMPLATE_PACK}/layout/field_errors.html"
    return render_to_string(
        template,
        {
            "field": field,
            "form_show_errors": True,
        },
    )


def _is_ajax(request: HttpRequest) -> bool:
    return request.headers.get("x-requested-with") == "XMLHttpRequest"


def _generic_denial() -> HttpResponse:
    """Identical response for not-found / not-owned / ineligible (no oracle)."""
    return HttpResponseForbidden("This comment cannot be edited or deleted.")


def _author_action_guard(request: HttpRequest, action: str) -> HttpResponse | None:
    """Shared preamble for the edit/delete endpoints.

    Returns a rejection response, or ``None`` when the request may proceed (a
    present, session-owned ``comment_id`` is guaranteed in ``request.POST``).
    Ownership here is the cheap session check; the row-locked re-check of
    eligibility happens in ``_load_locked_actionable``.
    """
    if not _is_ajax(request):
        return HttpResponseBadRequest("Expecting Ajax call")
    if not author_edits.author_edits_enabled():
        return HttpResponseNotFound(f"Comment {action} is not enabled.")
    if author_edits.rate_limited(request, action):
        return HttpResponse("Too many requests.", status=429)
    session = getattr(request, "session", None)
    comment_id = request.POST.get("comment_id")
    if session is None or not comment_id or not author_edits.owns_id(session, comment_id):
        return _generic_denial()
    return None


def _load_locked_actionable(
    request: HttpRequest, model, comment_id: str, using: str | None
) -> BaseComment | HttpResponse:
    """Inside an open transaction: lock the comment and confirm it is still
    actionable (public, not removed, not answered). Returns the locked comment, or
    a denial response. Ownership was already established in the preamble and is
    request-stable, so it is not re-checked here."""
    try:
        comment = model.objects.using(using).select_for_update().get(pk=comment_id)
    except (model.DoesNotExist, ValueError, TypeError, ValidationError):
        return _generic_denial()
    if not author_edits.comment_is_actionable(comment):
        return _generic_denial()
    return comment


def _rendered_comment_json(request: HttpRequest, comment: BaseComment, extra: dict[str, object]) -> HttpResponse:
    context = get_comment_context_data(comment, "post")
    context["request"] = request
    context.update(author_edits.comment_action_context(request, comment))
    template_name = get_comment_template_name(comment)
    comment_html = render_to_string(template_name, context, request=request)
    payload: dict[str, object] = {
        "success": True,
        "comment_id": str(comment.pk),
        "html": comment_html,
        "is_public": bool(getattr(comment, "is_public", True)),
    }
    payload.update(extra)
    return JsonResponse(payload)


def _validate_comment_text(data) -> tuple[str | None, HttpResponse | None]:
    """Validate only the editable text + honeypot; identity fields are immutable."""
    if data.get("honeypot"):
        return None, CommentPostBadRequest("The comment form failed security verification.")
    text = (data.get("comment") or "").strip()
    if not text:
        return None, HttpResponseBadRequest("This field is required.")
    if len(text) > COMMENT_MAX_LENGTH:
        return None, HttpResponseBadRequest(f"Ensure this value has at most {COMMENT_MAX_LENGTH} characters.")
    return text, None


def post_comment(request: HttpRequest, next: str | None = None, using: str | None = None) -> HttpResponse:
    """Stock ``django_comments`` post view, overriding its URL.

    The AJAX reply path locks the parent row to coordinate with edit/delete so a
    reply cannot land under a concurrently removed/author-deleted parent. The
    stock non-AJAX path has no such lock, so while the author-edits feature is
    enabled we reject replies here and require the AJAX endpoint, closing that
    public bypass. Top-level comments still post through the stock view normally.
    CSRF and method checks are enforced by the wrapped stock view's decorators.
    """
    from django_comments.views.comments import post_comment as stock_post_comment

    if author_edits.author_edits_enabled() and request.POST.get("parent"):
        return CommentPostBadRequest("Replies must be posted through the reply form.")
    return stock_post_comment(request, next=next, using=using)


@csrf_protect
@require_POST
def post_comment_edit_ajax(request: HttpRequest, using: str | None = None) -> HttpResponse:
    guard = _author_action_guard(request, "editing")
    if guard is not None:
        return guard
    comment_id = request.POST["comment_id"]

    text, error = _validate_comment_text(request.POST)
    if error is not None:
        return error

    model = django_comments.get_model()
    with transaction.atomic(using=using):
        loaded = _load_locked_actionable(request, model, comment_id, using)
        if isinstance(loaded, HttpResponse):
            return loaded
        comment = loaded

        # Only the text is mutable; identity fields are preserved from the stored
        # comment and never read from the request.
        comment.comment = text

        # Re-moderate through the same signal path as a new post (no comment_was_posted).
        responses = signals.comment_will_be_posted.send(sender=comment.__class__, comment=comment, request=request)
        for receiver, response in responses:
            if response is False:
                return CommentPostBadRequest(f"comment_will_be_posted receiver {receiver.__name__} killed the comment")

        comment.save(using=using)
        author_edits.mark_edited(comment)

    return _rendered_comment_json(request, comment, {"action": "edit", "edited": True})


@csrf_protect
@require_POST
def post_comment_delete_ajax(request: HttpRequest, using: str | None = None) -> HttpResponse:
    guard = _author_action_guard(request, "deletion")
    if guard is not None:
        return guard
    comment_id = request.POST["comment_id"]

    model = django_comments.get_model()
    with transaction.atomic(using=using):
        loaded = _load_locked_actionable(request, model, comment_id, using)
        if isinstance(loaded, HttpResponse):
            return loaded
        comment = loaded

        # Soft delete: hide robustly across query/template paths, keep the row for
        # staff to restore in Django admin, and record the author deletion.
        comment.is_removed = True
        comment.is_public = False
        comment.save(using=using)
        author_edits.mark_deleted(comment)

    return JsonResponse({"success": True, "action": "delete", "comment_id": str(comment.pk)})
