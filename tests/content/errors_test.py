from django.core.exceptions import ValidationError as DjangoValidationError

from cast.content.errors import (
    ContentError,
    ContentValidationError,
    ErrorCollector,
    flatten_django_validation_error,
)


def test_error_collector_accumulates_errors_by_path():
    errors = ErrorCollector()

    assert not errors
    assert len(errors) == 0

    errors.add("body.0.value", "invalid", "Bad value")
    errors.extend(
        [
            ContentError("body.0.value", "required", "Value required"),
            ContentError("body.1.type", "unsupported", "Bad type"),
        ]
    )

    assert errors
    assert len(errors) == 3
    assert errors.error_map == {
        "body.0.value": [
            {"code": "invalid", "message": "Bad value"},
            {"code": "required", "message": "Value required"},
        ],
        "body.1.type": [{"code": "unsupported", "message": "Bad type"}],
    }


def test_content_validation_error_exposes_collected_error_map():
    errors = ErrorCollector()
    errors.add("body", "invalid", "Bad body")

    exc = ContentValidationError(errors)

    assert exc.errors is errors
    assert exc.error_map == {"body": [{"code": "invalid", "message": "Bad body"}]}
    assert str(exc) == "Content validation failed."

    errors.add("body.0", "required", "Block required")
    assert "body.0" in exc.error_map


def test_flatten_django_validation_error_returns_content_errors():
    exc = DjangoValidationError({"title": [DjangoValidationError("Bad title", code="invalid")]})

    assert flatten_django_validation_error(exc, "body.0.value") == [
        ContentError("body.0.value.title", "invalid", "Bad title")
    ]
