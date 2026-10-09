from hashlib import sha1
from io import BytesIO, StringIO

import pytest
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import reverse
from PIL import ExifTags, Image
from wagtail.images import get_image_model

from cast.image_metadata import GPS_INFO, has_gps, strip_upload_gps


def image_bytes(fmt="JPEG", gps=True, **options):
    exif = Image.Exif()
    exif[ExifTags.Base.Orientation] = 6
    exif[ExifTags.Base.Make] = "Test camera"
    exif[ExifTags.IFD.Exif] = {ExifTags.Base.DateTimeOriginal: "2026:10:09 12:00:00"}
    if gps:
        exif[GPS_INFO] = {1: "N", 2: (51.0, 0.0, 0.0), 3: "E", 4: (7.0, 0.0, 0.0)}
    output = BytesIO()
    Image.new("RGB", (16, 24), "red").save(output, format=fmt, exif=exif.tobytes(), **options)
    return output.getvalue()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "fmt,extension", [("JPEG", "jpg"), ("PNG", "png"), ("WEBP", "webp"), ("AVIF", "avif"), ("HEIF", "heic")]
)
def test_new_upload_strips_only_gps(fmt, extension):
    original = image_bytes(fmt)
    with Image.open(BytesIO(original)) as source:
        expected_orientation = source.getexif()[ExifTags.Base.Orientation]
        expected_size = source.size
    model = get_image_model()
    image = model.objects.create(title="GPS", file=ContentFile(original, name=f"gps.{extension}"))
    with image.file.storage.open(image.file.name, "rb") as stored:
        data = stored.read()
    with Image.open(BytesIO(data)) as result:
        assert not has_gps(result)
        assert result.getexif()[ExifTags.Base.Orientation] == expected_orientation
        assert result.getexif()[ExifTags.Base.Make] == "Test camera"
        assert result.getexif().get_ifd(ExifTags.IFD.Exif)[ExifTags.Base.DateTimeOriginal] == "2026:10:09 12:00:00"
        assert result.size == expected_size
    image.refresh_from_db()
    assert image.file_size == len(data)
    assert image.file_hash == sha1(data).hexdigest()


@pytest.mark.django_db
def test_no_gps_and_metadata_only_saves_are_unchanged():
    original = image_bytes(gps=False)
    image = get_image_model().objects.create(title="Clean", file=ContentFile(original, name="clean.jpg"))
    image.title = "Renamed"
    image.save()
    with image.file.storage.open(image.file.name, "rb") as stored:
        assert stored.read() == original
    image.file = ContentFile(image_bytes(), name="replacement.jpg")
    image.save()
    with image.file.storage.open(image.file.name, "rb") as stored, Image.open(stored) as raster:
        assert not has_gps(raster)


@pytest.mark.django_db
@pytest.mark.parametrize("memory_limit", [0, 2621440])
def test_editor_upload_metadata_matches_sanitized_file(api_client, admin_user, settings, memory_limit):
    settings.FILE_UPLOAD_MAX_MEMORY_SIZE = memory_limit
    admin_user.is_superuser = True
    admin_user.save()
    api_client.force_authenticate(user=admin_user)
    response = api_client.post(
        reverse("cast:api:editor_media_images"),
        {"title": "GPS", "file": SimpleUploadedFile("gps.jpg", image_bytes(), content_type="image/jpeg")},
        format="multipart",
    )
    assert response.status_code == 201, response.content
    image = get_image_model().objects.get(pk=response.json()["id"])
    with image.file.storage.open(image.file.name, "rb") as stored:
        data = stored.read()
    assert image.file_size == len(data)
    assert image.file_hash == sha1(data).hexdigest()
    with Image.open(BytesIO(data)) as raster:
        assert not has_gps(raster)


@pytest.mark.django_db
def test_raw_empty_and_svg_are_unchanged():
    model = get_image_model()
    strip_upload_gps(model, model(), raw=False)
    raw = model(file=ContentFile(image_bytes(), name="raw.jpg"))
    strip_upload_gps(model, raw, raw=True)
    assert raw.file.read() == image_bytes()
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="16" height="24"></svg>'
    image = model.objects.create(title="SVG", file=ContentFile(svg, name="image.svg"))
    with image.file.storage.open(image.file.name, "rb") as stored:
        assert stored.read() == svg


@pytest.mark.django_db
def test_failed_upload_does_not_write_storage(mocker):
    image = get_image_model()(title="Broken", file=ContentFile(image_bytes(), name="bad.jpg"))
    mocker.patch("cast.image_metadata.Image.open", side_effect=OSError("broken image"))
    save = mocker.patch.object(image.file.storage, "save")
    with pytest.raises(OSError):
        image.save()
    save.assert_not_called()
    assert image.file.tell() == 0


@pytest.mark.django_db
def test_multiframe_gps_upload_rejected(mocker):
    output = BytesIO()
    exif = Image.Exif()
    exif[GPS_INFO] = {1: "N"}
    first = Image.new("RGB", (16, 24), "red")
    first.save(output, format="TIFF", save_all=True, append_images=[first.copy()], exif=exif.tobytes())
    image = get_image_model()(title="Frames", file=ContentFile(output.getvalue(), name="multi.tif"))
    save = mocker.patch.object(image.file.storage, "save")
    with pytest.raises(ValueError, match="multi-frame"):
        image.save()
    save.assert_not_called()


@pytest.mark.django_db
def test_report_is_read_only_and_handles_unreadable_files(mocker):
    model = get_image_model()
    clean = model.objects.create(title="Clean", file=ContentFile(image_bytes(gps=False), name="clean.jpg"))
    gps = model.objects.create(title="Old", file=ContentFile(image_bytes(gps=False), name="old.jpg"))
    # Simulate a pre-policy original without invoking model signals.
    gps.file.storage.delete(gps.file.name)
    gps.file.storage.save(gps.file.name, ContentFile(image_bytes()))
    svg = model.objects.create(
        title="SVG", file=ContentFile(b'<svg xmlns="http://www.w3.org/2000/svg"/>', name="x.svg")
    )
    before = list(model.objects.values())
    originals = {row.file.name: row.file.storage.open(row.file.name).read() for row in (clean, gps, svg)}
    save_model = mocker.patch.object(model, "save", side_effect=AssertionError("report must not save"))
    save_storage = mocker.patch.object(gps.file.storage, "save", side_effect=AssertionError("report must not write"))
    delete_storage = mocker.patch.object(
        gps.file.storage, "delete", side_effect=AssertionError("report must not delete")
    )
    output = StringIO()
    call_command("report_image_gps", stdout=output)
    assert f"{gps.pk}\t{gps.file.name}" in output.getvalue()
    assert f"{clean.pk}\t" not in output.getvalue()
    assert "GPS images: 1; unreadable images: 0" in output.getvalue()
    assert list(model.objects.values()) == before
    for name, content in originals.items():
        with gps.file.storage.open(name) as stored:
            assert stored.read() == content
    save_model.assert_not_called()
    save_storage.assert_not_called()
    delete_storage.assert_not_called()
    mocker.patch.object(gps.file.storage, "open", side_effect=FileNotFoundError("missing"))
    errors = StringIO()
    with pytest.raises(CommandError, match="incomplete"):
        call_command("report_image_gps", stdout=StringIO(), stderr=errors)
    assert f"Could not inspect image {gps.pk}" in errors.getvalue()


@pytest.mark.django_db
def test_unsupported_gps_format_rejected():
    image = get_image_model()(title="TIFF", file=ContentFile(image_bytes("TIFF"), name="gps.tif"))
    with pytest.raises(ValueError, match="not supported"):
        image.save()


@pytest.mark.django_db
def test_raster_named_svg_still_sanitized():
    image = get_image_model().objects.create(title="Disguised", file=ContentFile(image_bytes(), name="gps.svg"))
    with image.file.storage.open(image.file.name, "rb") as stored, Image.open(stored) as raster:
        assert not has_gps(raster)


@pytest.mark.django_db
@pytest.mark.parametrize("memory_limit", [0, 2621440])
def test_admin_upload_strips_gps(admin_client, admin_user, settings, memory_limit):
    settings.FILE_UPLOAD_MAX_MEMORY_SIZE = memory_limit
    admin_user.is_superuser = True
    admin_user.save()
    response = admin_client.post(
        reverse("wagtailimages:add"),
        {"title": "Admin GPS", "file": SimpleUploadedFile("admin.jpg", image_bytes(), content_type="image/jpeg")},
    )
    assert response.status_code == 302
    image = get_image_model().objects.get(title="Admin GPS")
    with image.file.storage.open(image.file.name, "rb") as stored, Image.open(stored) as raster:
        assert not has_gps(raster)


def test_gps_detection_checks_later_frames(mocker):
    with Image.open(BytesIO(image_bytes(gps=False))) as first, Image.open(BytesIO(image_bytes())) as second:
        mocker.patch("cast.image_metadata.ImageSequence.Iterator", return_value=iter([first, second]))
        assert has_gps(first)


def mpo_bytes():
    first = Image.new("RGB", (16, 24), "red")
    exif = Image.Exif()
    exif[GPS_INFO] = {1: "N"}
    output = BytesIO()
    first.save(output, format="MPO", save_all=True, append_images=[first.copy()], exif=exif.tobytes())
    return output.getvalue()


@pytest.mark.django_db
def test_gps_mpo_has_validation_errors_in_api_and_admin(api_client, admin_client, admin_user):
    admin_user.is_superuser = True
    admin_user.save()
    api_client.force_authenticate(user=admin_user)
    data = mpo_bytes()
    with Image.open(BytesIO(data)) as raster:
        assert raster.format == "MPO"
        assert has_gps(raster)
    response = api_client.post(
        reverse("cast:api:editor_media_images"),
        {"title": "MPO", "file": SimpleUploadedFile("phone.jpg", data, content_type="image/jpeg")},
        format="multipart",
    )
    assert response.status_code == 400
    assert response.json()["errors"]["file"][0]["code"] == "gps_metadata"
    response = admin_client.post(
        reverse("wagtailimages:add"),
        {"title": "MPO", "file": SimpleUploadedFile("phone.jpg", data, content_type="image/jpeg")},
    )
    assert response.status_code == 200
    assert "multi-picture JPEG" in response.content.decode()
    assert not get_image_model().objects.filter(title="MPO").exists()


@pytest.mark.django_db
@pytest.mark.parametrize("memory_limit", [0, 2621440])
def test_deferred_multiple_upload_is_sanitized(admin_client, admin_user, mocker, settings, memory_limit):
    settings.FILE_UPLOAD_MAX_MEMORY_SIZE = memory_limit
    from django.core.exceptions import ValidationError
    from wagtail.images.forms import BaseImageForm
    from wagtail.models import Collection, UploadedFile

    admin_user.is_superuser = True
    admin_user.save()
    collection = Collection.get_first_root_node()
    reject_title = mocker.patch.object(
        BaseImageForm, "clean_title", create=True, side_effect=ValidationError("More metadata required")
    )
    response = admin_client.post(
        reverse("wagtailimages:add_multiple"),
        {
            "collection": collection.pk,
            "files[]": SimpleUploadedFile("deferred.jpg", image_bytes(), content_type="image/jpeg"),
        },
    )
    assert response.status_code == 200, response.content
    upload = UploadedFile.objects.get(pk=response.json()["uploaded_file_id"])
    with upload.file.storage.open(upload.file.name, "rb") as stored, Image.open(stored) as raster:
        assert not has_gps(raster)
    mocker.stop(reject_title)
    prefix = f"uploaded-image-{upload.pk}"
    response = admin_client.post(
        reverse("wagtailimages:create_multiple_from_uploaded_image", args=[upload.pk]),
        {f"{prefix}-title": "Completed", f"{prefix}-collection": collection.pk},
    )
    assert response.status_code == 200, response.content
    assert response.json()["success"]
    image = get_image_model().objects.get(pk=response.json()["image_id"])
    with image.file.storage.open(image.file.name, "rb") as stored, Image.open(stored) as raster:
        assert not has_gps(raster)


@pytest.mark.django_db
def test_form_wrapper_preserves_custom_base_and_is_idempotent(settings, monkeypatch):
    from wagtail.images.forms import BaseImageForm, get_image_form

    from cast import image_metadata

    class CustomImageForm(BaseImageForm):
        def clean(self):
            cleaned = super().clean()
            cleaned["title"] = "Custom title"
            return cleaned

    monkeypatch.setattr(image_metadata, "GPSImageForm", image_metadata.GPSImageForm)
    monkeypatch.setattr(image_metadata, "get_image_base_form", lambda: CustomImageForm)
    settings.WAGTAILIMAGES_IMAGE_FORM_BASE = "custom.example.Form"
    image_metadata.install_upload_gps_form()
    installed = image_metadata.GPSImageForm
    image_metadata.install_upload_gps_form()
    assert image_metadata.GPSImageForm is installed
    form = get_image_form(get_image_model())(
        {"title": "Original"}, {"file": SimpleUploadedFile("gps.jpg", image_bytes())}
    )
    assert form.is_valid(), form.errors
    assert form.cleaned_data["title"] == "Custom title"
    with Image.open(form.cleaned_data["file"]) as raster:
        assert not has_gps(raster)


@pytest.mark.django_db
def test_sanitizer_failure_is_form_error(mocker):
    from wagtail.images.forms import get_image_form

    mocker.patch("cast.image_metadata.sanitize_upload", side_effect=OSError("Unreadable GPS metadata"))
    form = get_image_form(get_image_model())(
        {"title": "Broken"}, {"file": SimpleUploadedFile("gps.jpg", image_bytes())}
    )
    assert not form.is_valid()
    assert form.errors.as_data()["file"][0].code == "gps_metadata"
