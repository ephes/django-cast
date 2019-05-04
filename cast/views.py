import logging

from django.db import models
from django.utils import timezone
from django.shortcuts import get_object_or_404
from django.db.models.functions import TruncMonth
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView, DetailView, CreateView, UpdateView

from django_filters.views import FilterView

from .forms import PostForm
from .filters import PostFilter
from .filters import parse_date_facets
from .models import Blog, Post
from .viewmixins import (
    RenderPostMixin,
    AddRequestUserMixin,
    PostChangeMixin,
    GetParamsMixin,
)

logger = logging.getLogger(__name__)


class BlogsListView(ListView):
    model = Blog
    template_name = "cast/blog_list.html"
    context_object_name = "blogs"


class BlogDetailView(DetailView):
    model = Post
    template_name = "cast/blog_detail.html"
    context_object_name = "blog"


class PostsListView(RenderPostMixin, GetParamsMixin, FilterView):
    model = Post
    template_name = "cast/post_list.html"
    context_object_name = "posts"
    paginate_by = 5
    filterset_class = PostFilter

    def get_queryset(self):
        # self.blog is needed elsewhere
        self.blog = get_object_or_404(Blog, slug=self.kwargs["slug"])
        if not self.request.user.is_authenticated:
            queryset = Post.published.filter(blog=self.blog).order_by("-visible_date")
        else:
            queryset = Post.objects.filter(blog=self.blog).order_by("-created")
        return queryset

    def get_selected_facet(self):
        """Return the currently selected facet. Otherwise we would see
        all date facets that are choosable if no date facet was selected
        because in the final pass over the queryset facet_counts would be
        empty and the selected facet would not be accepted because it's
        not in the fields choices."""
        data = self.request.GET or None
        if data is None:
            return None
        date_facet = data.get("date_facets")
        if date_facet is None or len(date_facet) == 0:
            return None
        return parse_date_facets(date_facet)

    def get_facet_counts(self, filterset_class, kwargs):
        """This does a second pass over the queryset, yes. But facet counts
        are really nice to have, so it's worth it :)."""
        kwargs = {k: v for k, v in kwargs.items()}  # copy kwargs to avoid overwriting

        # get selected facet if set and build the facet counting queryset
        facet_counts = {}
        selected_facet = self.get_selected_facet()
        if selected_facet is not None:
            facet_counts = {"year_month": {selected_facet: 1}}
        kwargs["facet_counts"] = facet_counts
        post_filter = filterset_class(**kwargs)
        facet_queryset = (
            post_filter.qs.order_by()
            .annotate(month=TruncMonth("visible_date"))
            .values("month")
            .annotate(n=models.Count("pk"))
        )

        # build up the date facet counts for final filter pass
        year_month_counts = {}
        for row in facet_queryset:
            year_month_counts[row["month"]] = row["n"]
        return {"year_month": year_month_counts}

    def get_filterset_kwargs(self, filterset_class):
        """Collect kwargs for filterset class. Main point it to gather a list
        of date facets with counts."""
        kwargs = super().get_filterset_kwargs(filterset_class)
        # need to keep self.blog - it's used elsewhere too
        self.blog = get_object_or_404(Blog, slug=self.kwargs["slug"])
        kwargs["blog"] = self.blog
        kwargs["facet_counts"] = self.get_facet_counts(filterset_class, kwargs)
        return kwargs

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

    def get_initial_chaptermarks(self):
        chaptermarks = []
        if self.object.podcast_audio is not None:
            for chapter_mark in self.object.podcast_audio.chaptermarks.all():
                chaptermarks.append(chapter_mark.original_line)
        return "\n".join(chaptermarks)

    def get_initial(self):
        initial = super().get_initial()
        initial["is_published"] = self.object.is_published
        initial["chaptermarks"] = self.get_initial_chaptermarks()
        return initial

    def form_valid(self, form):
        self.blog_slug = self.kwargs["blog_slug"]
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # needed for back button
        context["blog_slug"] = self.kwargs["blog_slug"]
        return context
