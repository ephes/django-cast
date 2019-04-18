from __future__ import absolute_import

from django import forms
from django.utils import timezone
from django.utils.translation import ugettext_lazy as _

from .models import Post, Image, Video, ChapterMark


class MyDateTimeInput(forms.DateTimeInput):
    def render(self, *args, **kwargs):
        value = kwargs.get("value")
        if value is not None and not isinstance(value, str):
            kwargs["value"] = str(value.date())
        return super().render(*args, **kwargs)


class ChapterMarkForm(forms.ModelForm):
    class Meta:
        model = ChapterMark
        fields = ("audio", "start", "title", "link", "image")


class PostForm(forms.ModelForm):
    is_published = forms.BooleanField(required=False)
    pub_date = forms.DateTimeField(input_formats=["%Y-%m-%dT%H:%M"])

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["slug"].required = False
        self.fields["title"].widget.attrs["size"] = 80
        self.fields["pub_date"].required = False
        self.fields["pub_date"].widget = forms.DateTimeInput(
            attrs={"type": "datetime-local"}
        )
        self.fields["pub_date"].label = _("Publication date")
        self.fields["pub_date"].help_text = _(
            "Article will be published after this date/time."
        )

        self.fields["visible_date"].required = False
        self.fields["visible_date"].widget = MyDateTimeInput(attrs={"type": "date"})
        self.fields["visible_date"].label = _("Visible date")
        self.fields["visible_date"].help_text = _("Date to be shown above article.")

        self.fields["podcast_audio"].help_text = _(
            "The audio object to be used as podcast episode."
        )

        if self.instance.podcast_audio:
            self.fields["chaptermarks"] = forms.CharField(widget=forms.Textarea)

    def _set_pub_date(self, cleaned_data):
        pub_date = cleaned_data.get("pub_date")
        is_published = cleaned_data.get("is_published")
        if pub_date is None and is_published:
            cleaned_data["pub_date"] = timezone.now()
        return cleaned_data

    def _set_visible_date(self, cleaned_data):
        # dunno why this is necessary. 2019-02-26 jochen
        # visible_date is neither None in tests nor in notebook, but using
        # browser it raises null constraint error :/ wtf?
        visible_date = cleaned_data.get("visible_date")
        if visible_date is None:
            cleaned_data["visible_date"] = timezone.now()
        return cleaned_data

    def _clean_chaptermarks(self, cleaned_data):
        audio = self.instance.podcast_audio
        if audio:
            errors = []
            lines = cleaned_data.get("chaptermarks", "").split("\n")
            if len(lines) > 0:
                audio.chaptermarks.all().delete()
            for line in cleaned_data.get("chaptermarks", "").split("\n"):
                start, *parts = line.split()
                title = " ".join(parts)
                row = {
                    "audio": audio.pk,
                    "start": start,
                    "title": title,
                    # "link": None,
                    # "image": None
                }
                form = ChapterMarkForm(row)
                if form.is_valid():
                    form.save()
                else:
                    errors.append(form.errors)
                # TODO:
                # * image/link handling + tests
            if len(errors) > 0:
                self.add_error("chaptermarks", errors)
        return cleaned_data

    def clean(self):
        cleaned_data = super().clean()
        cleaned_data = self._set_pub_date(cleaned_data)
        cleaned_data = self._set_visible_date(cleaned_data)
        cleaned_data = self._clean_chaptermarks(cleaned_data)
        return cleaned_data

    class Meta:
        model = Post
        fields = [
            "title",
            "content",
            "pub_date",
            "visible_date",
            "is_published",
            "podcast_audio",
            "keywords",
            "explicit",
            "block",
            "slug",
        ]


class ImageForm(forms.ModelForm):
    class Meta:
        model = Image
        fields = ["original"]


class VideoForm(forms.ModelForm):
    class Meta:
        model = Video
        fields = ["original"]
