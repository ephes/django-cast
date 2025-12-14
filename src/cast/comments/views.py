from __future__ import annotations

import json

import django_comments
from django.apps import apps
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.http import HttpResponse, HttpResponseBadRequest
from django.template.loader import render_to_string
from django.utils.html import escape
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST
from django_comments import signals
from django_comments.views.comments import CommentPostBadRequest

from . import appsettings
from .utils import get_comment_context_data, get_comment_template_name


@csrf_protect
@require_POST
def post_comment_ajax(request, using=None):
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
        model = apps.get_model(*ctype.split(".", 1))
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

    comment.save()
    signals.comment_was_posted.send(sender=comment.__class__, comment=comment, request=request)
    return _ajax_result(request, form, "post", comment, object_id=object_pk)


def _ajax_result(request, form, action, comment=None, object_id=None):
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
        template_name = get_comment_template_name(comment)
        comment_html = render_to_string(template_name, context, request=request)

        json_return.update(
            {
                "html": comment_html,
                "comment_id": comment.id,
                "parent_id": getattr(comment, "parent_id", None),
            }
        )
        if request.user.is_staff:
            json_return["is_moderated"] = not bool(getattr(comment, "is_public", True))

    return HttpResponse(json.dumps(json_return), content_type="application/json")


def _render_errors(field):
    template = f"{appsettings.CRISPY_TEMPLATE_PACK}/layout/field_errors.html"
    return render_to_string(
        template,
        {
            "field": field,
            "form_show_errors": True,
        },
    )
