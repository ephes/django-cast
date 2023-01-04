import logging

from django.contrib import admin

from .models import (  # Image,
    Audio,
    Blog,
    ChapterMark,
    File,
    Gallery,
    ItunesArtWork,
    Post,
    SpamFilter,
    Video,
)

logger = logging.getLogger(__name__)


class AdminUserMixin:
    def get_changeform_initial_data(self, request):
        return {"user": request.user, "author": request.user}


@admin.register(Blog)
class BlogModelAdmin(AdminUserMixin, admin.ModelAdmin):
    list_display = ("title", "owner")


@admin.register(Post)
class PostModelAdmin(AdminUserMixin, admin.ModelAdmin):
    list_display = ("title", "owner", "blog")


@admin.register(ItunesArtWork)
class ItunesArtWorkModelAdmin(AdminUserMixin, admin.ModelAdmin):
    list_display = ("pk", "original")
    fields = ("original",)


@admin.register(File)
class FileModelAdmin(AdminUserMixin, admin.ModelAdmin):
    list_display = ("original", "user")
    fields = ("user", "original")


@admin.register(Audio)
class AudioAdmin(AdminUserMixin, admin.ModelAdmin):
    list_display = ("user", "title", "subtitle", "m4a", "mp3", "oga", "opus")
    fields = ("user", "title", "subtitle", "m4a", "mp3", "oga", "opus")


@admin.register(ChapterMark)
class ChapterMarkModelAdmin(AdminUserMixin, admin.ModelAdmin):
    list_display = ("start", "title", "link", "image", "audio")


@admin.register(Video)
class VideoModelAdmin(AdminUserMixin, admin.ModelAdmin):
    list_display = ("pk", "user")

    def save_model(self, request, obj, form, change):
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
def retrain(modeladmin, request, queryset):
    for spamfilter in queryset:
        train = spamfilter.get_training_data_comments()
        spamfilter.retrain_from_scratch(train)


@admin.register(SpamFilter)
class SpamfilterModelAdmin(admin.ModelAdmin):
    readonly_fields = ["spam", "ham"]
    list_display = ["pk", "name"] + readonly_fields
    fields = ("name",)
    actions = [retrain]

    @staticmethod
    def spam(obj):
        return obj.performance["spam"]

    @staticmethod
    def ham(obj):
        return obj.performance["ham"]
