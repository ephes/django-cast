import pytest
from django import http
from django.db import connection
from django.db.utils import DatabaseError

from cast.models import TemplateBaseDirectory
from cast.views import defaults


@pytest.fixture
def my_theme(site):
    name = "my_theme"
    TemplateBaseDirectory.objects.create(name=name, site=site)
    return name


@pytest.mark.django_db
def test_get_template_base_directory_happy(my_theme, simple_request):
    actual_theme = defaults.get_template_base_directory(simple_request)
    assert actual_theme == my_theme


@pytest.mark.django_db
def test_get_template_base_directory_on_database_failure(my_theme, simple_request):
    def blocker(_execute, _sql, _params, _many, _context):
        raise DatabaseError("Simulated broken connection 😱")

    # make sure the default template base directory is used if the database fails
    with connection.execute_wrapper(blocker):
        actual_theme = defaults.get_template_base_directory(simple_request)

    assert actual_theme == "plain"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "view, error_text, expected_response",
    [
        (defaults.page_not_found, "Page not found", http.HttpResponseNotFound),
        (defaults.server_error, "Server Error", http.HttpResponseServerError),
        (defaults.bad_request, "Bad Request", http.HttpResponseBadRequest),
        (defaults.permission_denied, "Permission Denied", http.HttpResponseForbidden),
        (defaults.csrf_failure, "CSRF verification failed.", http.HttpResponseForbidden),
    ],
)
def test_error_handler_views(view, error_text, expected_response, simple_request):
    if error_text == "Server Error":
        response = view(simple_request)
    else:
        response = view(simple_request, Exception())

    # make sure the right response type is returned
    assert isinstance(response, expected_response)

    # make sure the response contains the right error text from the template
    content = response.content.decode("utf-8")
    assert error_text in content
