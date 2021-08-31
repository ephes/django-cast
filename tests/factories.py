from django.contrib.auth import get_user_model

from wagtail.core.models import Site

import factory

from cast.models import Blog, Gallery, Image, Post, Video


class SiteFactory(factory.django.DjangoModelFactory):
    hostname = "localhost"

    class Meta:
        model = Site
        django_get_or_create = ("hostname",)


class UserFactory(factory.django.DjangoModelFactory):
    username = factory.Sequence(lambda n: "user-{0}".format(n))
    email = factory.Sequence(lambda n: "user-{0}@example.com".format(n))
    password = factory.PostGenerationMethodCall("set_password", "password")

    class Meta:
        model = get_user_model()
        django_get_or_create = ("username",)


class ImageFactory(factory.django.DjangoModelFactory):
    user = None
    original = factory.django.ImageField(color="blue")

    class Meta:
        model = Image


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
    title = factory.Sequence(lambda n: "blog-{0}".format(n))
    slug = factory.Sequence(lambda n: "blog-{0}".format(n))

    class Meta:
        model = Blog
        django_get_or_create = ("slug",)


class PostFactory(PageFactory):
    class Meta:
        model = Post
        django_get_or_create = ("slug",)
