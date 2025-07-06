from typing import Any

from django import forms
from django.http import HttpResponse
from django.shortcuts import render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_GET
from wagtail.images.models import Image

from ..blocks import get_srcset_images_for_slots
from .htmx_helpers import HtmxHttpRequest


class CommaSeparatedIntegerField(forms.Field):
    def to_python(self, value: Any | None) -> list[int]:  # Any | None from super -> do not override
        if value is None or not value.strip():
            return []
        try:
            return [int(item.strip()) for item in value.split(",")]  # image_pks
        except ValueError:
            raise forms.ValidationError(_("Enter a list of image ids."))


class GalleryModalForm(forms.Form):
    image_pks = CommaSeparatedIntegerField()
    current_image_index = forms.IntegerField()
    block_id = forms.CharField()

    def clean(self):
        cleaned_data = super().clean()
        image_pks = cleaned_data.get("image_pks", [])
        current_image_index = cleaned_data.get("current_image_index")
        if current_image_index is not None and (current_image_index < 0 or current_image_index >= len(image_pks)):
            raise forms.ValidationError(
                f"current_image_index {current_image_index} is out of range for image_pks with length {len(image_pks)}"
            )
        return cleaned_data


def get_prev_next_indices(image_pks: list[int], current_index: int) -> tuple[int | None, int | None]:
    """
    Given a list of image pks and the current index, return the prev and next indices.
    """
    if len(image_pks) < 2:
        return None, None

    prev_index = current_index - 1 if current_index > 0 else None
    next_index = current_index + 1 if current_index < len(image_pks) - 1 else None
    return prev_index, next_index


@require_GET
def gallery_modal(request: HtmxHttpRequest, template_base_dir: str) -> HttpResponse:
    """
    This view is used to render the modal for a gallery of images. It is requested
    via htmx and opens the modal with the current image and buttons for the prev/next
    images.

    If the form is not valid, it returns a 400 -> htmx will not swap the content.
    """
    form = GalleryModalForm(request.GET)
    if not form.is_valid():
        return HttpResponse(status=400)
    image_pks = form.cleaned_data["image_pks"]
    current_index = form.cleaned_data["current_image_index"]
    block_id = form.cleaned_data["block_id"]
    prev_index, next_index = get_prev_next_indices(image_pks, current_index)

    # Get PKs for the images we need to fetch
    current_image_pk = image_pks[current_index]
    prev_pk = image_pks[prev_index] if prev_index is not None else None
    next_pk = image_pks[next_index] if next_index is not None else None

    images_to_fetch = [pk for pk in (prev_pk, current_image_pk, next_pk) if pk is not None]
    images = list(Image.objects.filter(pk__in=images_to_fetch).prefetch_renditions())

    for image in images:
        fetched_renditions = {r.filter_spec: r for r in image.renditions.all() if r.image_id == image.pk}
        images_for_slots = get_srcset_images_for_slots(image, "regular", renditions=fetched_renditions)
        [image.modal] = images_for_slots.values()

    pk_to_image = {image.pk: image for image in images}

    # Add index information to images for template
    current_image = pk_to_image[current_image_pk]
    current_image.gallery_index = current_index

    prev_image = pk_to_image[prev_pk] if prev_pk is not None else None
    if prev_image:
        prev_image.gallery_index = prev_index

    next_image = pk_to_image[next_pk] if next_pk is not None else None
    if next_image:
        next_image.gallery_index = next_index

    context = {
        "current_image": current_image,
        "prev_image": prev_image,
        "next_image": next_image,
        "image_pks": ",".join([str(pk) for pk in image_pks]),
        "template_base_dir": template_base_dir,
        "block_id": block_id,
    }
    return render(request, f"cast/{template_base_dir}/gallery_modal.html", context=context)
