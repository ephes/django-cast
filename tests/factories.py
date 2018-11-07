import factory

from django.contrib.auth import get_user_model

from cast.models import Blog, Post, Image, Video, Gallery


class UserFactory(factory.django.DjangoModelFactory):
    username = factory.Sequence(lambda n: "user-{0}".format(n))
    email = factory.Sequence(lambda n: "user-{0}@example.com".format(n))
    password = factory.PostGenerationMethodCall("set_password", "password")

    class Meta:
        model = get_user_model()
        django_get_or_create = ("username",)


class BlogFactory(factory.django.DjangoModelFactory):
    user = None
    title = factory.Sequence(lambda n: "blog-{0}".format(n))
    slug = factory.Sequence(lambda n: "blog-{0}".format(n))

    class Meta:
        model = Blog
        django_get_or_create = ("slug",)


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
    user = None

    class Meta:
        model = Gallery


class PostFactory(factory.django.DjangoModelFactory):
    author = None
    blog = None
    published = None

    class Meta:
        model = Post
