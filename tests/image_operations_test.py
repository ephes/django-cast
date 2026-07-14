from io import BytesIO

from PIL import Image, ImageCms
from willow.plugins.pillow import PillowImage

from cast.image_operations import TransformColorspaceToSrgbOperation
from cast.wagtail_hooks import register_image_operations


def _srgb_profile_bytes() -> bytes:
    return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


def _profiled_image_with_large_icc_profile() -> Image.Image:
    image = Image.new("RGB", (120, 80), (200, 50, 25))
    image.info["icc_profile"] = _srgb_profile_bytes() + (b"x" * 30_000)
    return image


def _save_as_jpeg_bytes(willow_image: PillowImage) -> bytes:
    output = BytesIO()
    willow_image.save_as_jpeg(output, quality=75, optimize=True, progressive=True)
    return output.getvalue()


def _save_as_avif_bytes(willow_image: PillowImage) -> bytes:
    output = BytesIO()
    willow_image.save_as_avif(output, apply_optimizers=False)
    return output.getvalue()


def test_register_image_operations_registers_srgb_operation():
    assert ("srgb", TransformColorspaceToSrgbOperation) in register_image_operations()


def test_transform_colorspace_to_srgb_operation_compacts_profiled_rgb_output():
    operation = TransformColorspaceToSrgbOperation("srgb")
    profiled_willow = PillowImage(_profiled_image_with_large_icc_profile())

    transformed_willow = operation.run(profiled_willow, image=None, env={})

    assert transformed_willow.image.mode == "RGB"
    assert len(transformed_willow.image.info["icc_profile"]) == len(_srgb_profile_bytes())
    assert len(_save_as_jpeg_bytes(transformed_willow)) < len(_save_as_jpeg_bytes(profiled_willow)) / 10


def test_transform_colorspace_to_srgb_operation_is_noop_without_profile():
    operation = TransformColorspaceToSrgbOperation("srgb")
    willow = PillowImage(Image.new("RGB", (20, 10), (20, 30, 40)))

    transformed_willow = operation.run(willow, image=None, env={})

    assert transformed_willow is willow
    assert "icc_profile" not in transformed_willow.image.info


def test_transform_colorspace_to_srgb_operation_is_noop_for_unsupported_willow_image():
    operation = TransformColorspaceToSrgbOperation("srgb")
    willow = object()

    transformed_willow = operation.run(willow, image=None, env={})

    assert transformed_willow is willow


def test_transform_colorspace_to_srgb_operation_keeps_image_with_malformed_profile(caplog):
    operation = TransformColorspaceToSrgbOperation("srgb")
    image = Image.new("RGB", (20, 10), (20, 30, 40))
    image.info["icc_profile"] = b"not-an-icc-profile"
    willow = PillowImage(image)

    transformed_willow = operation.run(willow, image=None, env={})

    assert transformed_willow is not willow
    assert "icc_profile" not in transformed_willow.image.info
    assert "Could not normalize image rendition to sRGB" in caplog.text


def test_transform_colorspace_to_srgb_operation_keeps_cmyk_image_with_malformed_profile_renderable():
    operation = TransformColorspaceToSrgbOperation("srgb")
    image = Image.new("CMYK", (20, 10), (20, 30, 40, 50))
    image.info["icc_profile"] = b"not-an-icc-profile"
    willow = PillowImage(image)

    transformed_willow = operation.run(willow, image=None, env={})

    assert "icc_profile" not in transformed_willow.image.info
    assert _save_as_avif_bytes(transformed_willow)


def test_transform_colorspace_to_srgb_operation_keeps_unstrippable_image_when_transform_fails():
    class BrokenWillow:
        def transform_colorspace_to_srgb(self):
            raise OSError("broken profile")

    operation = TransformColorspaceToSrgbOperation("srgb")
    willow = BrokenWillow()

    transformed_willow = operation.run(willow, image=None, env={})

    assert transformed_willow is willow
