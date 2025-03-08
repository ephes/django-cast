import logging
from datetime import datetime
from typing import cast

from django.contrib.syndication.views import Feed
from django.db.models import Model, QuerySet
from django.http import Http404, HttpRequest
from django.shortcuts import get_object_or_404
from django.utils.feedgenerator import (
    Atom1Feed,
    Rss201rev2Feed,
    SyndicationFeed,
    rfc2822_date,
)
from django.utils.safestring import SafeText, mark_safe
from wagtail.images.models import Image

from cast import appsettings

from .models import Audio, Blog, Podcast, Post
from .models.repository import FeedRepository
from .views import HtmxHttpRequest

logger = logging.getLogger(__name__)


class RepositoryMixin:
    is_podcast: bool = False
    request: HtmxHttpRequest

    def __init__(self, repository: FeedRepository | None = None) -> None:
        super().__init__()
        self.repository = repository

    def get_repository(self, request: HtmxHttpRequest, blog: Blog) -> FeedRepository:
        if self.repository is not None:
            if not self.repository.used:
                # don't use the same repository twice
                return self.repository  # use predefined repository
        # create new repository
        if appsettings.CAST_REPOSITORY == "default":
            # default repository from cachable data
            cachable_data = FeedRepository.data_for_feed_cachable(
                request=request, blog=blog, is_podcast=self.is_podcast
            )
            return FeedRepository.create_from_cachable_data(data=cachable_data)
        else:
            # create repository from django models
            blog.refresh_from_db()  # FIXME this is stale sometimes
            return FeedRepository.create_from_django_models(
                request=request,
                blog=blog,
                post_queryset=Post.objects.live().descendant_of(blog).order_by("-visible_date"),
            )

    def items(self) -> QuerySet[Post]:
        assert self.repository is not None
        queryset = self.repository.post_queryset
        # mark repository as used - the post_queryset might be empty if used twice
        self.repository.used = True
        return queryset

    def get_feed(self, obj, request) -> SyndicationFeed:
        # If we want to cache the site to avoid one additional db query, we should do it here
        blog = obj
        self.repository = repository = self.get_repository(self.request, blog)
        # now that we have the repository, we can set the template base dir
        # to avoid db queries in context_processors
        self.request.cast_site_template_base_dir = repository.template_base_dir
        feed = super().get_feed(obj, request)  # type: ignore
        feed.repository = repository  # pass repository to feed to be able to access it in PodcastIndexElements
        return feed


class LatestEntriesFeed(RepositoryMixin, Feed):
    object: Blog
    request: HtmxHttpRequest

    def get_object(self, request: HttpRequest, *args, **kwargs) -> Blog:
        self.request = cast(HtmxHttpRequest, request)  # need request for item.serve(request) later on
        slug = kwargs["slug"]
        blog = None
        if self.repository is not None:
            # use predefined repository which is kind of dangerous but makes testing easier.
            # Forgetting to check whether the repository is used led to a bug which resulted in
            # using the wrong blog for the feed :(.
            if not self.repository.used:
                blog = self.repository.blog
        if blog is None:
            blog = get_object_or_404(Blog, slug=slug)
        self.object = blog
        return self.object

    def title(self) -> str:
        return self.object.title

    def description(self) -> str:
        return self.object.description

    def link(self) -> str:
        if self.repository is not None:
            return self.repository.blog_url
        return self.object.get_full_url()

    def item_title(self, post: Model) -> SafeText:
        assert isinstance(post, Post)
        return mark_safe(post.title)

    def item_description(self, post: Model) -> SafeText:
        assert isinstance(post, Post)
        assert self.repository is not None
        repository = self.repository.get_post_detail_repository(post)
        post.description = post.get_description(
            request=self.request, render_detail=True, escape_html=False, repository=repository
        )
        return post.description

    def item_link(self, item) -> SafeText:
        return item.get_full_url()

    def get_context_data(self, **kwargs) -> dict:
        context = super().get_context_data(**kwargs)
        return context


class ITunesElements:
    feed: dict

    def add_artwork(self, podcast: Podcast, handler) -> None:
        if podcast.itunes_artwork is None:
            return

        haqe = handler.addQuickElement
        itunes_artwork_url = cast(Image, podcast.itunes_artwork).original.url
        handler.addQuickElement("itunes:image", attrs={"href": itunes_artwork_url})
        handler.startElement("image", {})
        haqe("url", itunes_artwork_url)
        haqe("title", self.feed["title"])
        handler.endElement("image")

    @staticmethod
    def add_itunes_categories(podcast: Podcast, handler) -> None:
        itunes_categories = podcast.itunes_categories_parsed
        if len(itunes_categories) == 0:
            return
        for category, subcategories in itunes_categories.items():
            handler.startElement("itunes:category", {"text": category})
            for subcategory in subcategories:
                handler.addQuickElement("itunes:category", attrs={"text": subcategory})
            handler.endElement("itunes:category")

    def add_root_elements(self, handler) -> None:
        """Add additional elements to the blog object"""
        super().add_root_elements(handler)  # type: ignore
        haqe = handler.addQuickElement
        blog = self.feed["blog"]

        self.add_artwork(blog, handler)

        haqe("itunes:subtitle", self.feed["subtitle"])
        haqe("itunes:author", blog.author_name)
        handler.startElement("itunes:owner", {})
        haqe("itunes:name", blog.author_name)
        haqe("itunes:email", blog.email)
        handler.endElement("itunes:owner")

        self.add_itunes_categories(blog, handler)

        haqe("itunes:summary", blog.description)
        haqe("itunes:explicit", blog.get_explicit_display())
        try:
            haqe("lastBuildDate", rfc2822_date(blog.last_build_date))
        except IndexError:
            pass
        generator = "Django Web Framework / django-cast"
        haqe("generator", generator)
        haqe("docs", "https://blogs.law.harvard.edu/tech/rss")

    def add_item_elements(self, handler, item) -> None:
        """Add additional elements to the post object"""
        super().add_item_elements(handler, item)  # type: ignore
        haqe = handler.addQuickElement

        post = item["post"]
        haqe("guid", str(post.uuid), attrs={"isPermaLink": "false"})
        # Maybe add license later
        # year = timezone.now().year
        # haqe("copyright", "{0} {1}".format("insert license", year))
        haqe("itunes:author", post.owner.get_full_name())
        haqe("itunes:subtitle", post.title)
        haqe("itunes:summary", post.description)
        haqe("itunes:duration", post.podcast_audio.duration_str)
        haqe("itunes:keywords", post.keywords)
        haqe("itunes:explicit", post.get_explicit_display())
        if post.block:
            haqe("itunes:block", "yes")

    def namespace_attributes(self) -> dict:
        namespace_attributes = {}
        namespace_attributes.update({"xmlns:itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd"})
        return namespace_attributes


class PodcastIndexElements:
    feed: dict
    request: HttpRequest
    repository: FeedRepository

    def add_item_elements(self, handler, item) -> None:
        """Add additional elements to the post object"""
        try:
            super().add_item_elements(handler, item)  # type: ignore
        except AttributeError:
            pass

        haqe = handler.addQuickElement
        episode = item["post"]
        repository = None
        if hasattr(self, "repository"):
            repository = self.repository.get_episode_feed_detail_repository(episode)

        if (vtt_transcript_url := episode.get_vtt_transcript_url(self.request, repository)) is not None:
            haqe("podcast:transcript", attrs={"type": "text/vtt", "url": vtt_transcript_url})
        if (
            podcastindex_transcript_url := episode.get_podcastindex_transcript_url(self.request, repository)
        ) is not None:
            haqe("podcast:transcript", attrs={"type": "application/json", "url": podcastindex_transcript_url})

    def namespace_attributes(self) -> dict:
        namespace_attributes = super().namespace_attributes()  # type: ignore
        namespace_attributes.update({"xmlns:podcast": "https://podcastindex.org/namespace/1.0/"})
        return namespace_attributes


class AtomITunesFeedGenerator(PodcastIndexElements, ITunesElements, Atom1Feed):
    def root_attributes(self) -> dict:
        atom_attrs = super().root_attributes()
        atom_attrs.update(self.namespace_attributes())
        return atom_attrs


class RssITunesFeedGenerator(PodcastIndexElements, ITunesElements, Rss201rev2Feed):
    def rss_attributes(self) -> dict:
        rss_attrs = super().rss_attributes()
        rss_attrs.update(self.namespace_attributes())
        return rss_attrs


class PodcastFeed(RepositoryMixin, Feed):
    """
    A feed of podcasts for iTunes and other compatible podcatchers.
    """

    audio_format: str
    mime_type: str
    object: Podcast
    request: HtmxHttpRequest
    is_podcast: bool = True

    def set_audio_format(self, audio_format: str) -> None:
        format_to_mime = Audio.mime_lookup
        if audio_format not in format_to_mime:
            raise Http404("unknown audio format")
        else:
            self.audio_format = audio_format
            self.mime_type = format_to_mime[audio_format]

    def get_object(self, request, *args, **kwargs) -> Podcast:
        self.set_audio_format(kwargs["audio_format"])

        slug = kwargs["slug"]
        self.object = get_object_or_404(Podcast, slug=slug)
        self.request = request  # need request for item.serve(request) later on
        return self.object

    def link(self) -> str:
        if self.repository is not None:
            return self.repository.blog_url
        return self.object.get_full_url()

    def title(self, _blog: Blog) -> str:
        return self.object.title

    def categories(self, blog: Blog) -> tuple[str]:
        if hasattr(blog, "categories"):
            return (blog.keywords.split(",")[0],)
        else:
            return ("",)

    def itunes_categories(self, blog: Blog) -> list[str]:
        return blog.itunes_categories.split(",")

    def item_title(self, item) -> str:
        return item.title

    def item_description(self, item) -> str:
        repository = None
        if self.repository is not None:
            repository = self.repository.get_post_detail_repository(item)
        item.description = item.get_description(
            request=self.request, render_detail=True, escape_html=False, repository=repository
        )
        return item.description

    def item_link(self, item) -> str:
        return item.get_full_url()

    def item_pubdate(self, item) -> datetime:
        return item.visible_date

    def item_updateddate(self, item: Post) -> datetime:
        return item.last_published_at

    # def item_categories(self, post):
    #    return self.categories(self.blog)

    def item_enclosure_url(self, item: Post) -> str:
        return item.get_enclosure_url(self.audio_format)

    def item_enclosure_length(self, item: Post) -> int:
        return item.get_enclosure_size(self.audio_format)

    def item_enclosure_mime_type(self, _item: Post) -> str:
        return self.mime_type

    def item_keywords(self, item: Post) -> str:
        return item.keywords

    def feed_extra_kwargs(self, obj) -> dict:
        return {"blog": self.object}

    def item_extra_kwargs(self, item) -> dict:
        return {"blog": self.object, "post": item}

    def get_feed(self, obj, request) -> SyndicationFeed:
        feed = super().get_feed(obj, request)
        feed.request = request  # type: ignore
        return feed


class AtomPodcastFeed(PodcastFeed):
    feed_type = AtomITunesFeedGenerator

    def subtitle(self, blog: Blog) -> str:
        return blog.description

    def author_name(self, blog: Blog) -> str:
        return blog.author_name

    def author_email(self, blog) -> str:
        return blog.email

    def link(self) -> str:
        """atom link is still wrong, dunno why FIXME"""
        return self.object.get_full_url()


class RssPodcastFeed(PodcastFeed):
    feed_type = RssITunesFeedGenerator

    def item_guid(self, _post: Post) -> None:
        """ITunesElements can't add isPermaLink attr unless None is returned here."""
        return None

    def description(self, blog: Blog) -> str:
        return blog.description
