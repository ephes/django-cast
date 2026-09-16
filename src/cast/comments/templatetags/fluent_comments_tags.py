from __future__ import annotations

from copy import copy
from typing import TYPE_CHECKING, Any, cast

from django import template
from django.template.base import FilterExpression, Parser, Token
from django.template.exceptions import TemplateSyntaxError
from django.template.loader import render_to_string
from django.utils.safestring import SafeString, mark_safe

from .. import appsettings
from ..utils import (
    comments_are_moderated,
    comments_are_open,
    get_comment_context_data,
    get_comment_template_name,
)

if TYPE_CHECKING:
    from ..models import BaseComment

register = template.Library()


@register.filter
def safe_fill_tree(comments: Any) -> Any:
    """Fill a paginated thread path without crossing its target or visibility boundary."""
    from threadedcomments.models import PATH_DIGITS, PATH_SEPARATOR

    if not comments:
        return comments
    comments = list(comments)
    first = comments[0]
    path_ids = first.tree_path.split(PATH_SEPARATOR)[:-1]
    valid_path_ids = [path_id for path_id in path_ids if path_id.isdecimal()]
    ancestors = (
        first.__class__.objects.filter(
            pk__in=valid_path_ids,
            content_type_id=first.content_type_id,
            object_pk=first.object_pk,
            site_id=first.site_id,
            is_public=True,
            is_removed=False,
        ).order_by("tree_path")
        if valid_path_ids
        else []
    )
    ancestors_by_path_id = {str(ancestor.pk).zfill(PATH_DIGITS): ancestor for ancestor in ancestors}
    safe_ancestors: list[Any] = []
    for path_id in reversed(path_ids):
        ancestor = ancestors_by_path_id.get(path_id)
        if ancestor is None:
            # Do not reconnect a descendant across a hidden middle ancestor.
            # No further ancestors are fetched; the paths are rebased below to
            # whichever safe comments are already present in the rendered slice.
            break
        ancestor.added_path = True
        safe_ancestors.insert(0, ancestor)

    visible_ids = {str(comment.pk).zfill(PATH_DIGITS) for comment in [*safe_ancestors, *comments]}
    rendered = []
    for comment in [*safe_ancestors, *comments]:
        rendered_comment = copy(comment)
        rendered_path = [path_id for path_id in comment.tree_path.split(PATH_SEPARATOR) if path_id in visible_ids]
        rendered_comment.tree_path = PATH_SEPARATOR.join(rendered_path)
        rendered_comment.parent_id = int(rendered_path[-2]) if len(rendered_path) > 1 else None
        rendered.append(rendered_comment)
    return rendered


class AjaxCommentTagsNode(template.Node):
    def __init__(self, target_object_expr: FilterExpression) -> None:
        self.target_object_expr = target_object_expr

    def render(self, context: template.Context) -> str:
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
def ajax_comment_tags(parser: Parser, token: Token) -> AjaxCommentTagsNode:
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
def render_comment(context: template.Context, comment: BaseComment) -> SafeString:
    request = context.get("request")
    template_name = get_comment_template_name(comment)
    ctx = get_comment_context_data(comment)
    ctx["request"] = request
    if request is not None:
        from .. import author_edits

        edited_pks = getattr(request, "_cast_edited_pks", None)
        ctx.update(author_edits.comment_action_context(request, comment, edited_pks))
    return mark_safe(render_to_string(template_name, ctx, request=request))


@register.filter("comments_are_open")
def comments_are_open_filter(content_object: object) -> bool:
    return comments_are_open(content_object)


@register.filter("comments_are_moderated")
def comments_are_moderated_filter(content_object: object) -> bool:
    return comments_are_moderated(content_object)


@register.filter
def comments_count(content_object: object) -> int:
    from django_comments import get_model as get_comments_model

    return get_comments_model().objects.for_model(content_object).count()


@register.simple_tag(takes_context=True)
def fluent_comments_list(context: template.Context) -> SafeString:
    comment_list = context.get("comment_list")
    request = context.get("request")
    # Precompute the 'edited' set once for the whole list to avoid an N+1 query
    # in render_comment. Stored on the request; read by render_comment above.
    # Skip entirely when the feature is off: comment_action_context will early-
    # return without touching the DB, so _cast_edited_pks is not needed.
    if request is not None:
        from .. import author_edits

        if author_edits.author_edits_enabled():
            ids = [c.pk for c in comment_list] if comment_list else []
            request._cast_edited_pks = author_edits.edited_pks_for(ids)
    target_object_id = context.get("target_object_id")
    if not target_object_id and comment_list:
        try:
            first = comment_list[0]
        except Exception:
            first = None
        if first is not None:
            target_object_id = getattr(first, "object_pk", None)

    ctx = cast(dict[str, Any], context.flatten())
    ctx["USE_THREADEDCOMMENTS"] = appsettings.USE_THREADEDCOMMENTS
    ctx["target_object_id"] = target_object_id

    template_name = (
        "fluent_comments/templatetags/threaded_list.html"
        if appsettings.USE_THREADEDCOMMENTS
        else "fluent_comments/templatetags/flat_list.html"
    )
    return mark_safe(render_to_string(template_name, ctx, request=context.get("request")))
