import logging

from django.contrib.syndication.views import Feed

from django.utils.feedgenerator import Atom1Feed, rfc2822_date, Rss201rev2Feed

from django.http import Http404
from django.shortcuts import get_object_or_404

from .models import Blog, Post, Audio

from .viewmixins import RenderPostMixin

logger = logging.getLogger(__name__)


class LatestEntriesFeed(RenderPostMixin, Feed):
    def get_object(self, request, *args, **kwargs):
        slug = kwargs["slug"]
        self.object = get_object_or_404(Blog, slug=slug)

    def title(self):
        return self.object.title

    def description(self):
        return self.object.description

    def link(self):
        return self.object.get_absolute_url()

    def items(self):
        queryset = Post.published.filter(blog=self.object).order_by("-pub_date")
        return queryset

    def item_title(self, item):
        return item.title

    def item_description(self, item):
        self.render_post(item, javascript=False)
        return item.description


class ITunesElements:
    def add_artwork(self, blog, handler):
        if blog.itunes_artwork is None:
            return

        haqe = handler.addQuickElement
        itunes_artwork_url = blog.itunes_artwork.original.url
        handler.addQuickElement("itunes:image", attrs={"href": itunes_artwork_url})
        handler.startElement("image", {})
        haqe("url", itunes_artwork_url)
        haqe("title", self.feed["title"])
        handler.endElement("image")

    def add_itunes_categories(self, blog, handler):
        itunes_categories = blog.itunes_categories_parsed
        if len(itunes_categories) == 0:
            return
        for category, subcategories in itunes_categories.items():
            handler.startElement("itunes:category", {"text": category})
            for subcategory in subcategories:
                handler.addQuickElement("itunes:category", attrs={"text": subcategory})
            handler.endElement("itunes:category")

    def add_root_elements(self, handler):
        """ Add additional elements to the blog object"""
        super(ITunesElements, self).add_root_elements(handler)
        haqe = handler.addQuickElement
        blog = self.feed["blog"]

        self.add_artwork(blog, handler)

        haqe("itunes:subtitle", self.feed["subtitle"])
        haqe("itunes:author", blog.user.get_full_name())
        handler.startElement("itunes:owner", {})
        haqe("itunes:name", blog.user.get_full_name())
        haqe("itunes:email", blog.user.email)
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
        haqe("docs", "http://blogs.law.harvard.edu/tech/rss")

    def add_item_elements(self, handler, item):
        """ Add additional elements to the post object"""
        super(ITunesElements, self).add_item_elements(handler, item)
        haqe = handler.addQuickElement

        post = item["post"]
        haqe("guid", str(post.uuid), attrs={"isPermaLink": "false"})
        # Maybe add license later
        # year = timezone.now().year
        # haqe("copyright", "{0} {1}".format("insert license", year))
        haqe("itunes:author", post.author.get_full_name())
        haqe("itunes:subtitle", post.description)
        haqe("itunes:summary", post.description)
        haqe("itunes:duration", post.podcast_audio.duration_str)
        haqe("itunes:keywords", post.keywords)
        haqe("itunes:explicit", post.get_explicit_display())
        if post.block:
            haqe("itunes:block", "yes")

    def namespace_attributes(self):
        return {"xmlns:itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd"}


class AtomITunesFeedGenerator(ITunesElements, Atom1Feed):
    def root_attributes(self):
        atom_attrs = super(AtomITunesFeedGenerator, self).root_attributes()
        atom_attrs.update(self.namespace_attributes())
        return atom_attrs


class RssITunesFeedGenerator(ITunesElements, Rss201rev2Feed):
    def rss_attributes(self):
        rss_attrs = super(RssITunesFeedGenerator, self).rss_attributes()
        rss_attrs.update(self.namespace_attributes())
        return rss_attrs


class PodcastFeed(RenderPostMixin, Feed):
    """
    A feed of podcasts for iTunes and other compatible podcatchers.
    """

    def set_audio_format(self, audio_format):
        format_to_mime = Audio.mime_lookup
        if audio_format not in format_to_mime:
            raise Http404("unkown audio format")
        else:
            self.audio_format = audio_format
            self.mime_type = format_to_mime[audio_format]

    def get_object(self, request, *args, **kwargs):
        self.set_audio_format(kwargs["audio_format"])

        slug = kwargs["slug"]
        self.object = get_object_or_404(Blog, slug=slug)
        return self.object

    def link(self):
        return self.object.get_absolute_url()

    def title(self, blog):
        return self.object.title

    def categories(self, blog):
        return (blog.keywords.split(",")[0],)

    def itunes_categories(self, blog):
        return blog.itunes_categories.split(",")

    def items(self, blog):
        queryset = Post.published.podcast_episodes.filter(blog=self.object).order_by(
            "-pub_date"
        )
        return queryset

    def item_title(self, item):
        return item.title

    def item_description(self, item):
        self.render_post(item, javascript=False)
        return item.description

    def item_link(self, item):
        return item.get_absolute_url()

    def item_pubdate(self, item):
        return item.pub_date

    # def item_categories(self, post):
    #    return self.categories(self.blog)

    def item_enclosure_url(self, item):
        return item.get_enclosure_url(self.audio_format)

    def item_enclosure_length(self, item):
        return item.get_enclosure_size(self.audio_format)

    def item_enclosure_mime_type(self, item):
        return self.mime_type

    def item_keywords(self, item):
        return item.keywords

    def feed_extra_kwargs(self, obj):
        return {"blog": self.object}

    def item_extra_kwargs(self, item):
        return {"blog": self.object, "post": item}


class AtomPodcastFeed(PodcastFeed):
    feed_type = AtomITunesFeedGenerator

    def subtitle(self, blog):
        return blog.description

    def author_name(self, blog):
        return blog.user.get_full_name()

    def author_email(self, blog):
        return blog.user.email

    def link(self):
        """atom link is still wrong, dunno why FIXME"""
        return self.object.get_absolute_url()


class RssPodcastFeed(PodcastFeed):
    feed_type = RssITunesFeedGenerator

    def item_guid(self, post):
        "ITunesElements can't add isPermaLink attr unless None is returned here."
        return None

    def description(self, blog):
        return blog.description
