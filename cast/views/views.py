import logging

from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils import timezone
from django.views.generic import CreateView, DetailView, ListView

from ..forms import PostForm
from ..models import Blog, Post
from .viewmixins import AddRequestUserMixin, PostChangeMixin, RenderPostMixin


logger = logging.getLogger(__name__)


class BlogsListView(ListView):
    model = Blog
    template_name = "cast/blog_list.html"
    context_object_name = "blogs"


class BlogDetailView(DetailView):
    model = Post
    template_name = "cast/blog_detail.html"
    context_object_name = "blog"


class PostDetailView(RenderPostMixin, DetailView):
    model = Post
    template_name = "cast/post_detail.html"
    context_object_name = "post"
    slug_url_kwarg = "slug"
    query_pk_and_slug = True

    def get_queryset(self):
        if not self.request.user.is_authenticated:
            queryset = Post.published.order_by("-pub_date")
        else:
            queryset = Post.objects.order_by("-created")
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        post = context[self.context_object_name]
        # self.render_post(post, include_detail=True)
        # context["next"] = post.get_absolute_url()
        context["comments_enabled"] = post.comments_are_enabled
        return context


class PostCreateView(LoginRequiredMixin, PostChangeMixin, AddRequestUserMixin, CreateView):
    model = Post
    form_class = PostForm
    template_name = "cast/post_edit.html"
    user_field_name = "author"
    success_msg = "Entry created!"

    def get_initial(self):
        initial = super().get_initial()
        initial["visible_date"] = timezone.now()
        return initial

    def form_valid(self, form):
        self.blog_slug = self.kwargs["slug"]
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # needed for back button
        context["blog_slug"] = self.kwargs["slug"]
        return context
