import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from wagtail.images import get_image_model

from cast.content.blocks import ConversionContext
from cast.content.convert import author_blocks_to_section, section_to_author_blocks
from cast.content.errors import ContentValidationError
from tests.factories import UserFactory


@pytest.fixture
def superuser(db):
    return UserFactory(is_staff=True, is_superuser=True)


@pytest.mark.django_db
@pytest.mark.parametrize("direction", ["read", "write"])
def test_repeated_and_distinct_media_have_batched_query_growth(image, superuser, direction):
    model = get_image_model()
    extra = model.objects.bulk_create(
        [
            model(title=f"Synthetic {i}", file=image.file.name, width=1, height=1, collection_id=image.collection_id)
            for i in range(20)
        ]
    )
    ids = [image.pk] * 50 + [obj.pk for obj in extra]
    if direction == "write":
        blocks = [{"type": "image", "value": {"id": pk}} for pk in ids]
        blocks.append({"type": "gallery", "value": [{"id": pk} for pk in ids]})
        convert = author_blocks_to_section
    else:
        blocks = [{"type": "image", "value": pk} for pk in ids]
        blocks.append({"type": "gallery", "value": {"gallery": [{"type": "item", "value": pk} for pk in ids]}})
        convert = section_to_author_blocks
    with CaptureQueriesContext(connection) as queries:
        result = convert(blocks, ctx=ConversionContext(section="overview", user=superuser))
    assert len(result) == len(blocks)
    assert all(block["type"] != "unsupported" for block in result)
    assert len(queries) <= 5


@pytest.mark.django_db
def test_denied_repeated_media_keep_each_validation_path(superuser):
    blocks = [{"type": "image", "value": {"id": 999999}}] * 3
    with CaptureQueriesContext(connection) as queries, pytest.raises(ContentValidationError) as exc:
        author_blocks_to_section(blocks, ctx=ConversionContext(section="overview", user=superuser))
    assert set(exc.value.error_map) == {f"overview.{i}.value.id" for i in range(3)}
    assert len(queries) <= 1
