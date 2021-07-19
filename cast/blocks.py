from itertools import tee, islice, chain

from django.forms.utils import flatatt
from django.utils.html import format_html
from django.utils.html import format_html_join
from django.utils.functional import cached_property

from wagtail.core.blocks import ListBlock
from wagtail.core.blocks import ChooserBlock

from wagtailmedia.blocks import AbstractMediaChooserBlock


def previous_and_next(iterable):
    prevs, items, nexts = tee(iterable, 3)
    prevs = chain([None], prevs)
    nexts = chain(islice(nexts, 1, None), [None])
    return zip(prevs, items, nexts)


class GalleryBlock(ListBlock):
    class Meta:
        template = "cast/wagtail_gallery_block.html"

    def add_prev_next(self, gallery):
        for previous_image, current_image, next_image in previous_and_next(gallery):
            current_image.prev = (
                "false" if previous_image is None else f"img-{previous_image.pk}"
            )
            current_image.next = (
                "false" if next_image is None else f"img-{next_image.pk}"
            )

    def get_context(self, gallery, parent_context=None):
        self.add_prev_next(gallery)
        return super().get_context(gallery, parent_context=parent_context)


class VideoChooserBlock(ChooserBlock):
    @cached_property
    def target_model(self):
        from .models import Video
        return Video

    @cached_property
    def widget(self):
        from .wagtail_widgets import AdminVideoChooser
        return AdminVideoChooser

    def to_python(self, value):
        # the incoming serialised value should be None or an ID
        print("video to_python: ", value)
        if value is None:
            return value
        else:
            try:
                return self.target_model.objects.get(pk=value)
            except self.target_model.DoesNotExist:
                return None

    def bulk_to_python(self, values):
        """Return the model instances for the given list of primary keys.

        The instances must be returned in the same order as the values and keep None values.
        """
        print("video bulk_to_python: ", values)
        objects = self.target_model.objects.in_bulk(values)
        foo = [objects.get(id) for id in values]  # Keeps the ordering the same as in values.
        print("video objects: ", foo)
        # raise Exception("where is this called?")
        return foo

    def get_prep_value(self, value):
        print("video get_prep_value: ", value)
        # the native value (a model instance or None) should serialise to a PK or None
        if value is None:
            return None
        else:
            return value.pk

    def value_from_form(self, value):
        print("video value_from_form: ", value)
        # ModelChoiceField sometimes returns an ID, and sometimes an instance; we want the instance
        if value is None or isinstance(value, self.target_model):
            return value
        else:
            try:
                return self.target_model.objects.get(pk=value)
            except self.target_model.DoesNotExist:
                return None

    def clean(self, value):
        # ChooserBlock works natively with model instances as its 'value' type (because that's what you
        # want to work with when doing front-end templating), but ModelChoiceField.clean expects an ID
        # as the input value (and returns a model instance as the result). We don't want to bypass
        # ModelChoiceField.clean entirely (it might be doing relevant validation, such as checking page
        # type) so we convert our instance back to an ID here. It means we have a wasted round-trip to
        # the database when ModelChoiceField.clean promptly does its own lookup, but there's no easy way
        # around that...
        if isinstance(value, self.target_model):
            value = value.pk
        return super().clean(value)

    # def get_form_state(self, value):
    #     value_data = self.widget.get_value_data(value)
    #     if value_data is None:
    #         return None
    #     else:
    #         return {
    #             "id": value_data["id"],
    #             "edit_link": value_data["edit_url"],
    #             "title": value_data["title"],
    #             "preview": value_data["preview"],
    #         }

    # def get_context(self, video, parent_context=None):
    #     print("get context: ", video)
    #     context = super().get_context(video, parent_context=parent_context)
    #     context["video"] = video
    #     return context

    # class Meta:
    #     icon = "media"


class TestMediaBlock(AbstractMediaChooserBlock):
    def to_python(self, value):
        # the incoming serialised value should be None or an ID
        print("media to_python: ", value)
        if value is None:
            return value
        else:
            try:
                return self.target_model.objects.get(pk=value)
            except self.target_model.DoesNotExist:
                return None

    def bulk_to_python(self, values):
        """Return the model instances for the given list of primary keys.

        The instances must be returned in the same order as the values and keep None values.
        """
        print("media bulk_to_python: ", values)
        objects = self.target_model.objects.in_bulk(values)
        foo = [objects.get(id) for id in values]  # Keeps the ordering the same as in values.
        print("media objects: ", foo)
        # raise Exception("where is this called?")
        return foo

    def get_prep_value(self, value):
        print("media get_prep_value: ", value)
        # the native value (a model instance or None) should serialise to a PK or None
        if value is None:
            return None
        else:
            return value.pk

    def value_from_form(self, value):
        print("media value_from_form: ", value)
        # ModelChoiceField sometimes returns an ID, and sometimes an instance; we want the instance
        if value is None or isinstance(value, self.target_model):
            return value
        else:
            try:
                return self.target_model.objects.get(pk=value)
            except self.target_model.DoesNotExist:
                return None

    def render_basic(self, value, context=None):
        print("media render_basic: ", value)
        if not value:
            return ''

        if value.type == 'video':
            player_code = '''
            <div>
                <video width="320" height="240" controls>
                    {0}
                    Your browser does not support the video tag.
                </video>
            </div>
            '''
        else:
            player_code = '''
            <div>
                <audio controls>
                    {0}
                    Your browser does not support the audio element.
                </audio>
            </div>
            '''

        return format_html(player_code, format_html_join(
            '\n', "<source{0}>",
            [[flatatt(s)] for s in value.sources]
        ))

