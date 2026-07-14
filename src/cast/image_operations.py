"""Custom Wagtail image rendition operations for django-cast."""

import logging
from typing import Any

from wagtail.images.image_operations import FilterOperation

logger = logging.getLogger(__name__)


class TransformColorspaceToSrgbOperation(FilterOperation):
    """Transform profiled raster images to compact sRGB renditions."""

    def construct(self) -> None:
        pass

    @staticmethod
    def _without_icc_profile(willow: Any) -> Any:
        pillow_image = getattr(willow, "image", None)
        if pillow_image is None or not hasattr(pillow_image, "info"):
            return willow
        image_without_profile = pillow_image.copy()
        image_without_profile.info.pop("icc_profile", None)
        return type(willow)(image_without_profile)

    def run(self, willow: Any, image: Any, env: dict[str, Any]) -> Any:
        transform_to_srgb = getattr(willow, "transform_colorspace_to_srgb", None)
        if transform_to_srgb is None:
            return willow
        try:
            return transform_to_srgb()
        except Exception as exc:
            logger.warning("Could not normalize image rendition to sRGB; stripping invalid ICC profile: %s", exc)
            return self._without_icc_profile(willow)
