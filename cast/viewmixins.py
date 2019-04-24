import logging

from django.template import Context
from django.template import Template

from django.shortcuts import get_object_or_404

from .models import Blog

logger = logging.getLogger(__name__)


class RenderPostMixin:
    def render_post(self, post, javascript=True):
        content = "{}\n{}".format("{% load cast_extras %}", post.content)
        template = Template(content)
        blog_context = Context({"javascript": javascript, "post": post})
        blog_context.update(post.media_lookup)
        post.description = template.render(blog_context)


class AddRequestUserMixin:
    user_field_name = "user"

    def form_valid(self, form):
        model = form.save(commit=False)
        setattr(model, self.user_field_name, self.request.user)
        return super().form_valid(form)


class PostChangeMixin:
    def form_valid(self, form):
        post = form.save(commit=False)
        if len(form.cleaned_data["slug"]) == 0:
            post.slug = post.get_slug()
        blog = get_object_or_404(Blog, slug=self.blog_slug)
        post.blog = blog
        return super().form_valid(form)

    def form_invalid(self, form):
        logger.info("form invalid: {}".format(form.errors))
        return super().form_invalid(form)


class GetParamsMixin:
    """Collect all request.GET parameters in a querystring and make them
    available to the template. Needed for pagination:
    href="?page={{ page_obj.next_page_number }}{{ parameters }}"
    """

    initial_params = {}

    def get_other_get_params(self):
        get_copy = self.request.GET.copy()
        get_copy.update(self.initial_params.copy())
        parameters = get_copy.pop("page", True) and get_copy.urlencode()
        if len(parameters) > 0:
            parameters = f"&{parameters}"
        return parameters

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["parameters"] = self.get_other_get_params()
        return context
