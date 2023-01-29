import logging
from typing import TYPE_CHECKING

from django.contrib import admin
from django.db.models import QuerySet

from .models import (
    Audio,
    Blog,
    ChapterMark,
    Episode,
    File,
    Gallery,
    ItunesArtWork,
    Post,
    SpamFilter,
    Video,
)

if TYPE_CHECKING:
    from django.forms import Form
    from django.http import HttpRequest

logger = logging.getLogger(__name__)


class AdminUserMixin:
    def get_changeform_initial_data(self, request: "HttpRequest") -> dict:
        return {"user": request.user, "author": request.user}


@admin.register(Blog)
class BlogModelAdmin(AdminUserMixin, admin.ModelAdmin):
    list_display = ("title", "owner")


@admin.register(Post)
class PostModelAdmin(AdminUserMixin, admin.ModelAdmin):
    list_display = ("title", "owner", "blog")
    fields = (
        "visible_date",
        "title",
        "slug",
        "seo_title",
        "search_description",
    )


@admin.register(Episode)
class EpisodeModelAdmin(AdminUserMixin, admin.ModelAdmin):
    list_display = ("title", "owner", "blog")
    fields = (
        "visible_date",
        "title",
        "slug",
        "seo_title",
        "search_description",
        "podcast_audio",
        "keywords",
        "explicit",
        "block",
    )


@admin.register(ItunesArtWork)
class ItunesArtWorkModelAdmin(AdminUserMixin, admin.ModelAdmin):
    list_display = ("pk", "original")
    fields = ("original",)


@admin.register(File)
class FileModelAdmin(AdminUserMixin, admin.ModelAdmin):
    list_display = ("original", "user")
    fields = ("user", "original")


@admin.action(description="Cache file  sizes")
def cache_file_sizes(_modeladmin: admin.ModelAdmin, _request: "HttpRequest", queryset: QuerySet[Audio]) -> None:
    for audio in queryset:
        audio.size_to_metadata()
        audio.save()


@admin.register(Audio)
class AudioAdmin(AdminUserMixin, admin.ModelAdmin):
    list_display = ("user", "title", "subtitle", "m4a", "mp3", "oga", "opus")
    fields = ("user", "title", "subtitle", "m4a", "mp3", "oga", "opus", "data")
    actions = [cache_file_sizes]


@admin.register(ChapterMark)
class ChapterMarkModelAdmin(AdminUserMixin, admin.ModelAdmin):
    list_display = ("start", "title", "link", "image", "audio")


@admin.register(Video)
class VideoModelAdmin(AdminUserMixin, admin.ModelAdmin):
    list_display = ("pk", "user")

    def save_model(self, request: "HttpRequest", obj: Video, form: "Form", change) -> None:
        logger.info(f"poster: {obj.poster}")
        logger.info(f"form: {form.cleaned_data}")
        if change and not form.cleaned_data["poster"]:
            logger.info("poster was cleared")
            obj.calc_poster = False
        super().save_model(request, obj, form, change)


@admin.register(Gallery)
class GalleryModelAdmin(AdminUserMixin, admin.ModelAdmin):
    list_display = ("pk",)
    fields = ("user", "images")


@admin.action(description="Retrain model from scratch using marked comments")
def retrain(_modeladmin: admin.ModelAdmin, _request: "HttpRequest", queryset: QuerySet[SpamFilter]) -> None:
    for spamfilter in queryset:
        train = spamfilter.get_training_data_comments()
        spamfilter.retrain_from_scratch(train)


@admin.register(SpamFilter)
class SpamfilterModelAdmin(admin.ModelAdmin):
    readonly_fields = ["spam", "ham"]
    list_display = tuple(["pk", "name"] + readonly_fields)
    fields = ("name",)
    actions = [retrain]

    @staticmethod
    def spam(obj: SpamFilter) -> dict:
        return obj.performance["spam"]

    @staticmethod
    def ham(obj: SpamFilter) -> dict:
        return obj.performance["ham"]
