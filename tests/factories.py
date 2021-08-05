import factory

from django.contrib.auth import get_user_model

from wagtail.core.models import Page

from cast.models import Blog, Post, Image, Video, Gallery


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
    user = None

    class Meta:
        model = Gallery


class PostFactory(factory.django.DjangoModelFactory):
    author = None
    blog = None
    published = None

    class Meta:
        model = Post


class PageFactory(factory.django.DjangoModelFactory):
    class Meta:
        abstract = True

    @classmethod
    def _create(cls, model_class, *args, **kwargs):

        try:
            parent = kwargs.pop("parent")
        except KeyError:
            # no parent, appending page to root
            parent = Page.get_first_root_node()

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
