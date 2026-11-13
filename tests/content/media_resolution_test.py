import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from wagtail.images import get_image_model
from wagtail.models import Collection

from cast.content.blocks import ConversionContext
from cast.content.convert import author_blocks_to_section
from cast.content.errors import ContentValidationError
from cast.content.media_refs import MediaResolution, get_choosable_image, get_choosable_video
from tests.factories import UserFactory


def test_resolution_needs_one_user_and_valid_ids():
    with pytest.raises(TypeError):
        MediaResolution(None).resolve("image", 1)
    with pytest.raises(TypeError):
        MediaResolution(None).prefetch([{"type": "audio", "value": {"id": 1}}], stored=False)
    with pytest.raises(ValueError, match="another user"):
        author_blocks_to_section(
            [], ctx=ConversionContext(section="overview", user=object(), media_resolution=MediaResolution(object()))
        )
    assert get_choosable_image(True, object()) is None
    assert get_choosable_video("bad", object()) is None
    assert MediaResolution(object()).resolve("image", True) is None
    resolution = MediaResolution(object())
    resolution.prefetch([None, {"type": "gallery", "value": "bad"}], stored=False)


@pytest.mark.django_db
def test_missing_ids_are_batched_and_negative_results_reused():
    user = UserFactory(is_superuser=True)
    resolution = MediaResolution(user)
    refs = [{"type": "image", "value": {"id": 100000 + i}} for i in range(1001)]
    with CaptureQueriesContext(connection) as queries:
        resolution.prefetch(refs, stored=False)
        resolution.prefetch(refs, stored=False)
        for ref in refs:
            assert resolution.resolve("image", ref["value"]["id"]) is None
    assert len(queries) == 3


@pytest.mark.django_db
def test_permission_results_do_not_survive_a_conversion(image):
    user = UserFactory(is_superuser=True)
    payload = [{"type": "image", "value": {"id": image.pk}}]
    assert author_blocks_to_section(payload, ctx=ConversionContext(section="overview", user=user))
    get_user_model().objects.filter(pk=user.pk).update(is_superuser=False)
    current_user = get_user_model().objects.get(pk=user.pk)
    with pytest.raises(ContentValidationError):
        author_blocks_to_section(payload, ctx=ConversionContext(section="overview", user=current_user))


@pytest.mark.django_db(databases={"default", "migration_other"})
def test_resolution_separates_equal_ids_on_different_databases(settings, image):
    user = UserFactory(is_superuser=True)
    model = get_image_model()
    collection = Collection.objects.using("migration_other").create(name="Synthetic", path="9999", depth=1, numchild=0)
    model.objects.using("migration_other").create(
        pk=image.pk, title="Other synthetic image", file="synthetic.png", width=1, height=1, collection=collection
    )

    class ImageRouter:
        alias = "default"

        def db_for_read(self, model, **hints):
            return self.alias

    router = ImageRouter()
    settings.DATABASE_ROUTERS = [router]
    resolution = MediaResolution(user)
    assert resolution.resolve("image", image.pk).title == image.title
    router.alias = "migration_other"
    other = resolution.resolve("image", image.pk)
    assert other._state.db == "migration_other"
    assert other.title == "Other synthetic image"


@pytest.mark.django_db
def test_editor_sections_share_media_resolution(image):
    from cast.api.editor.views import PostEditorMixin

    user = UserFactory(is_superuser=True)
    blocks = [{"type": "image", "value": {"id": image.pk}}] * 20
    blocks += [{"type": "gallery", "value": [{"id": image.pk}]}]
    with CaptureQueriesContext(connection) as queries:
        sections = PostEditorMixin()._submitted_body_sections({"overview": blocks, "detail": blocks}, user=user)
    assert len(queries) == 1
    assert len(sections) == 2
    assert len({item["id"] for section in sections for item in section["value"]}) == 42
