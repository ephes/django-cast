import logging

from django.utils import timezone
from django.shortcuts import get_object_or_404
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView, DetailView, CreateView, UpdateView

from .forms import PostForm
from .models import Blog, Post
from .viewmixins import RenderPostMixin, AddRequestUserMixin, PostChangeMixin

logger = logging.getLogger(__name__)


class BlogsListView(ListView):
    model = Blog
    template_name = "cast/blog_list.html"
    context_object_name = "blogs"


class BlogDetailView(DetailView):
    model = Post
    template_name = "cast/blog_detail.html"
    context_object_name = "blog"


class PostsListView(RenderPostMixin, ListView):
    model = Post
    template_name = "cast/post_list.html"
    context_object_name = "posts"
    paginate_by = 5

    def get_queryset(self):
        self.blog = get_object_or_404(Blog, slug=self.kwargs["slug"])
        if not self.request.user.is_authenticated:
            queryset = Post.published.filter(blog=self.blog).order_by("-visible_date")
        else:
            queryset = Post.objects.filter(blog=self.blog).order_by("-created")
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["blog"] = self.blog
        for post in context[self.context_object_name]:
            self.render_post(post)
        return context


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
        Post = context[self.context_object_name]
        self.render_post(Post)
        return context


class PostCreateView(
    LoginRequiredMixin, PostChangeMixin, AddRequestUserMixin, CreateView
):
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


class PostUpdateView(
    LoginRequiredMixin, PostChangeMixin, AddRequestUserMixin, UpdateView
):
    model = Post
    form_class = PostForm
    template_name = "cast/post_edit.html"
    user_field_name = "author"
    success_msg = "Entry updated!"

    def get_initial(self):
        initial = super().get_initial()
        initial["is_published"] = self.object.is_published
        return initial

    def form_valid(self, form):
        self.blog_slug = self.kwargs["blog_slug"]
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # needed for back button
        context["blog_slug"] = self.kwargs["blog_slug"]
        return context
