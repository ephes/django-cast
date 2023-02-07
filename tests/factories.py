import factory
from django.contrib.auth import get_user_model
from wagtail.models import Site

from cast.models import Blog, Episode, Gallery, Podcast, Post, Video


class SiteFactory(factory.django.DjangoModelFactory):
    hostname = "localhost"

    class Meta:
        model = Site
        django_get_or_create = ("hostname",)


class UserFactory(factory.django.DjangoModelFactory):
    username = factory.Sequence(lambda n: f"user-{n}")
    email = factory.Sequence(lambda n: f"user-{n}@example.com")
    password = factory.PostGenerationMethodCall("set_password", "password")

    class Meta:
        model = get_user_model()
        django_get_or_create = ("username",)


class VideoFactory(factory.django.DjangoModelFactory):
    user = None
    original = factory.django.ImageField(color="blue")

    class Meta:
        model = Video


class GalleryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Gallery


class PageFactory(factory.django.DjangoModelFactory):
    class Meta:
        abstract = True

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        parent = kwargs.pop("parent")
        page = model_class(*args, **kwargs)
        parent.add_child(instance=page)
        return page


class BlogFactory(PageFactory):
    author = None
    title = factory.Sequence(lambda n: f"blog-{n}")
    slug = factory.Sequence(lambda n: f"blog-{n}")

    class Meta:
        model = Blog
        django_get_or_create = ("slug",)


class PodcastFactory(PageFactory):
    author = None
    title = factory.Sequence(lambda n: f"blog-{n}")
    slug = factory.Sequence(lambda n: f"blog-{n}")

    class Meta:
        model = Podcast
        django_get_or_create = ("slug",)


class PostFactory(PageFactory):
    class Meta:
        model = Post
        django_get_or_create = ("slug",)


class EpisodeFactory(PageFactory):
    class Meta:
        model = Episode
        django_get_or_create = ("slug",)
