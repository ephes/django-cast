"""Generic ``File`` uploads accept only allowlisted, non-active-content extensions."""

import pytest
from django.contrib.admin.sites import site as admin_site
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile

from cast.models import File
from cast.models.file import allowed_file_extensions, validate_file_extension


@pytest.mark.parametrize("name", ["notes.pdf", "Data.CSV", "dir/archive.tar", "readme.txt"])
def test_allowlisted_extensions_are_accepted(name):
    validate_file_extension(SimpleUploadedFile(name, b"x"))


@pytest.mark.parametrize(
    "name", ["page.html", "page.htm", "image.svg", "feed.xml", "app.js", "x.xhtml", "noext", "", "report.pdf.html"]
)
def test_active_content_and_unknown_extensions_are_rejected(name):
    with pytest.raises(ValidationError) as excinfo:
        validate_file_extension(SimpleUploadedFile(name, b"x") if name else SimpleUploadedFile("x", b""))
    assert excinfo.value.code == "invalid_extension"


def test_allowlist_is_configurable(settings):
    settings.CAST_FILE_EXTENSIONS = [".MOBI", " ", 3, "pdf"]
    assert allowed_file_extensions() == {"mobi", "pdf"}
    validate_file_extension(SimpleUploadedFile("book.mobi", b"x"))
    with pytest.raises(ValidationError, match="Allowed extensions are: mobi, pdf"):
        validate_file_extension(SimpleUploadedFile("notes.txt", b"x"))


@pytest.mark.django_db
def test_admin_form_rejects_html_upload(user, rf):
    model_admin = admin_site._registry[File]
    request = rf.get("/")
    request.user = user
    form_class = model_admin.get_form(request)
    form = form_class(
        data={"user": user.pk},
        files={"original": SimpleUploadedFile("evil.html", b"<script>alert(1)</script>", content_type="text/html")},
    )
    assert not form.is_valid()
    assert "is not allowed" in str(form.errors["original"])
    ok = form_class(data={"user": user.pk}, files={"original": SimpleUploadedFile("ok.pdf", b"%PDF-1.4")})
    assert ok.is_valid(), ok.errors
