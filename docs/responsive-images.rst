*****************
Responsive Images
*****************

Responsive images adapt to different screen sizes, ensuring optimal
display across devices. This project uses two types of responsive images:

- **Normal Images:** Displayed within page content.
- **Thumbnail Images:** Shown as thumbnails in content and enlarged in a modal upon clicking.

**Image Renditions:**
For each image, three renditions are created in AVIF and JPEG formats:
- **1x Width:** Standard size, used in the `src` attribute of the `img` tag.
- **2x Width:** Double size, used provided the image is not larger or nearly the same size as the original.
- **3x Width:** Triple size, used only when necessary.
These renditions are specified in the `srcset` attribute of the `source` or `img` elements.

Those three renditions are put into the `srcset` attribute of the related `source` or `img`
elements.

Normal Images
=============

Normal images fill a slot with a width of 1110px and a maximum height of 740px.
But you can configure those values in the :ref:`settings <image_slot_dimensions>`.

Therefore, if you have an image which is quadratic and has a width of 3000px it
will rendered with a maximum width of 740px, but delivered with a width of 2220px
to high pixel density devices.

Both AVIF and JPEG formats are supported.

Thumbnail Images
================

Thumbnail images have a width of 120px and a maximum height of 80px. But you can
also set those values in the :ref:`settings <image_slot_dimensions>`.

They also support AVIF and JPEG formats.
