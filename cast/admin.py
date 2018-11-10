import logging

from django.contrib import admin

from .models import Blog, Post, File, Image, Video, Gallery, Audio

logger = logging.getLogger(__name__)


class AdminUserMixin:
    def get_changeform_initial_data(self, request):
        return {"user": request.user, "author": request.user}


class BlogModelAdmin(AdminUserMixin, admin.ModelAdmin):
    list_display = ("title", "user")


admin.site.register(Blog, BlogModelAdmin)


class PostModelAdmin(AdminUserMixin, admin.ModelAdmin):
    list_display = ("title", "author", "blog")

    class Media:
        js = ("js/cast/ckeditor_fix.js",)


admin.site.register(Post, PostModelAdmin)


class ImageModelAdmin(AdminUserMixin, admin.ModelAdmin):
    list_display = ("pk", "original", "user")
    fields = ("user", "original")


admin.site.register(Image, ImageModelAdmin)


class FileModelAdmin(AdminUserMixin, admin.ModelAdmin):
    list_display = ("original", "user")
    fields = ("user", "original")


admin.site.register(File, FileModelAdmin)


class AudioAdmin(AdminUserMixin, admin.ModelAdmin):
    list_display = ("user", "title", "subtitle", "flac", "mp3", "mp4")
    fields = ("user", "title", "subtitle", "flac", "mp3", "mp4")


admin.site.register(Audio, AudioAdmin)


class VideoModelAdmin(AdminUserMixin, admin.ModelAdmin):
    list_display = ("pk", "user")

    def save_model(self, request, obj, form, change):
        logger.info("poster: {}".format(obj.poster))
        logger.info("form: {}".format(form.cleaned_data))
        if change and not form.cleaned_data["poster"]:
            logger.info("poster was cleared")
            obj.calc_poster = False
        super().save_model(request, obj, form, change)


admin.site.register(Video, VideoModelAdmin)


class GalleryModelAdmin(AdminUserMixin, admin.ModelAdmin):
    list_display = ("pk",)
    fields = ("user", "images")


admin.site.register(Gallery, GalleryModelAdmin)
