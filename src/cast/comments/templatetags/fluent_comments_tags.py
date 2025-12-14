from __future__ import annotations

from django import template
from django.template.exceptions import TemplateSyntaxError
from django.template.loader import render_to_string
from django.utils.safestring import mark_safe

from .. import appsettings
from ..utils import (
    comments_are_moderated,
    comments_are_open,
    get_comment_context_data,
    get_comment_template_name,
)

register = template.Library()


class AjaxCommentTagsNode(template.Node):
    def __init__(self, target_object_expr):
        self.target_object_expr = target_object_expr

    def render(self, context):
        target_object = self.target_object_expr.resolve(context)
        return render_to_string(
            "fluent_comments/templatetags/ajax_comment_tags.html",
            {
                "USE_THREADEDCOMMENTS": appsettings.USE_THREADEDCOMMENTS,
                "target_object": target_object,
            },
            request=context.get("request"),
        )


@register.tag
def ajax_comment_tags(parser, token):
    """
    Backwards-compatible tag.

    Supports both:
    - {% ajax_comment_tags object %}
    - {% ajax_comment_tags for object %}
    """
    bits = token.split_contents()
    if len(bits) == 2:
        target_object_expr = parser.compile_filter(bits[1])
    elif len(bits) == 3 and bits[1] == "for":
        target_object_expr = parser.compile_filter(bits[2])
    else:
        raise TemplateSyntaxError(
            f"{bits[0]!r} tag requires either 1 argument or the syntax 'for <object>' (got: {' '.join(bits[1:])!r})."
        )
    return AjaxCommentTagsNode(target_object_expr)


@register.simple_tag(takes_context=True)
def render_comment(context, comment):
    template_name = get_comment_template_name(comment)
    ctx = get_comment_context_data(comment)
    ctx["request"] = context.get("request")
    return mark_safe(render_to_string(template_name, ctx, request=context.get("request")))


@register.filter("comments_are_open")
def comments_are_open_filter(content_object):
    return comments_are_open(content_object)


@register.filter("comments_are_moderated")
def comments_are_moderated_filter(content_object):
    return comments_are_moderated(content_object)


@register.filter
def comments_count(content_object):
    from django_comments import get_model as get_comments_model

    return get_comments_model().objects.for_model(content_object).count()


@register.simple_tag(takes_context=True)
def fluent_comments_list(context):
    comment_list = context.get("comment_list")
    target_object_id = context.get("target_object_id")
    if not target_object_id and comment_list:
        try:
            first = comment_list[0]
        except Exception:
            first = None
        if first is not None:
            target_object_id = getattr(first, "object_pk", None)

    ctx = context.flatten()
    ctx["USE_THREADEDCOMMENTS"] = appsettings.USE_THREADEDCOMMENTS
    ctx["target_object_id"] = target_object_id

    template_name = (
        "fluent_comments/templatetags/threaded_list.html"
        if appsettings.USE_THREADEDCOMMENTS
        else "fluent_comments/templatetags/flat_list.html"
    )
    return mark_safe(render_to_string(template_name, ctx, request=context.get("request")))
