import pytest
from wagtail.blocks import StructBlockValidationError

from cast.blocks import EmptyImageRepository, GalleryBlockWithLayout, GalleryItemBlock, gallery_item_parts


@pytest.mark.parametrize(
    "value,expected",
    [(None, (None, "")), (12, (12, "")), ({"value": 12}, (12, "")), ({"image": 12, "caption": "A"}, (12, "A"))],
)
def test_gallery_item_parts(value, expected):
    assert gallery_item_parts(value) == expected


@pytest.mark.django_db
def test_gallery_item_legacy_and_new_roundtrip(image):
    block = GalleryItemBlock()
    for raw in [image.pk, {"image": image.pk, "caption": ""}]:
        value = block.to_python(raw)
        assert value["image"] == image
        assert block.get_prep_value(value) == {"image": image.pk, "caption": ""}
    value = block.to_python({"image": image.pk, "caption": "<b>Caption</b>"})
    assert block.clean(value)["caption"] == "<b>Caption</b>"
    assert block.get_form_state(value)["caption"] == "<b>Caption</b>"
    value["caption"] = "x" * 251
    with pytest.raises(StructBlockValidationError):
        block.clean(value)
    assert block.bulk_to_python([image.pk, {"image": image.pk, "caption": "B"}])[1]["caption"] == "B"


@pytest.mark.django_db
def test_gallery_editor_roundtrip_preserves_order_ids_captions(image):
    block = GalleryBlockWithLayout()
    child = block.child_blocks["gallery"]
    raw = [
        {"type": "item", "id": "first", "value": image.pk},
        {"type": "item", "id": "second", "value": {"image": image.pk, "caption": "Second use"}},
        {"type": "item", "id": "empty", "value": {"image": None, "caption": ""}},
    ]
    value = child.to_python(raw)
    form = child.get_form_state(value)
    assert [item["id"] for item in form] == ["first", "second", "empty"]
    assert form[1]["value"]["caption"] == "Second use"
    stored = child.get_prep_value(value)
    assert [item["id"] for item in stored] == ["first", "second"]
    assert stored[0]["value"] == {"image": image.pk, "caption": ""}
    assert stored[1]["value"]["caption"] == "Second use"


@pytest.mark.django_db
@pytest.mark.parametrize("use_repository", [True, False])
def test_gallery_render_captions_per_occurrence_without_mutation(image, use_repository):
    block = GalleryBlockWithLayout()
    repository = EmptyImageRepository()
    if use_repository:
        repository.image_by_id = {image.pk: image}
    value = {
        "layout": "default",
        "gallery": [
            {"type": "item", "value": {"image": image.pk, "caption": "<script>First</script>"}},
            {"type": "item", "value": {"image": image.pk, "caption": "Second"}},
            {"type": "item", "value": None},
        ],
    }
    context = {"repository": repository, "template_base_dir": "plain"}
    rendered = block.render(value, context)
    assert "<figcaption>&lt;script&gt;First&lt;/script&gt;</figcaption>" in rendered
    assert "<figcaption>Second</figcaption>" in rendered
    assert not hasattr(image, "caption")
    assert value["gallery"][0]["value"]["caption"] == "<script>First</script>"
    assert block.render(value, context) == rendered


@pytest.mark.django_db
def test_gallery_fallback_drops_missing_image_with_caption(image):
    block = GalleryBlockWithLayout()
    value = {
        "gallery": [
            {"value": {"image": image.pk + 1000, "caption": "Missing"}},
            {"value": {"image": image.pk, "caption": "Present"}},
        ]
    }
    resolved = block.bulk_to_python_from_database(value)
    assert resolved["gallery"] == [{"image": image, "caption": "Present"}]
    assert block.get_prep_value(resolved)["gallery"][0]["value"]["caption"] == "Present"


@pytest.mark.django_db
def test_editor_api_caption_roundtrip(image, admin_user):
    from cast.api.editor.body import author_blocks_to_overview, overview_to_author_blocks
    from cast.api.editor.errors import EditorValidationError

    admin_user.is_superuser = True
    admin_user.save()
    author = [
        {"type": "gallery", "value": [{"id": image.pk, "caption": "First"}, {"id": image.pk, "caption": "Second"}]}
    ]
    assert overview_to_author_blocks(author_blocks_to_overview(author, user=admin_user)) == author
    for caption in [None, "x" * 251]:
        author[0]["value"][0]["caption"] = caption
        with pytest.raises(EditorValidationError) as exc:
            author_blocks_to_overview(author, user=admin_user)
        assert "overview.0.value.0.caption" in exc.value.error_map


@pytest.mark.django_db
def test_raw_gallery_form_and_serialization_preserve_item_ids(image):
    child = GalleryBlockWithLayout().child_blocks["gallery"]
    raw = [{"type": "item", "id": "original", "value": image.pk}, {"image": image.pk, "caption": "New"}]
    assert child.get_form_state(raw)[0]["id"] == "original"
    assert child.get_prep_value(raw)[0]["id"] == "original"
    assert child.get_api_representation(raw)[0] == {"image": image.pk, "caption": ""}
    assert "New" in child.get_searchable_content(raw)


@pytest.mark.django_db
def test_gallery_post_revision_and_media_discovery(post, image, admin_client):
    from django.urls import reverse
    from cast.post_media import prepare_post_media

    post.body = [
        {
            "type": "overview",
            "value": [
                {
                    "type": "gallery",
                    "value": {
                        "layout": "default",
                        "gallery": [
                            {"type": "item", "id": "old", "value": image.pk},
                            {
                                "type": "item",
                                "id": "new",
                                "value": {"image": image.pk, "caption": "Remember this caption"},
                            },
                        ],
                    },
                }
            ],
        }
    ]
    post.save()
    revision = post.save_revision()
    restored = revision.as_object()
    prepare_post_media(restored, create_renditions=False)
    assert list(restored.galleries.get().images.values_list("pk", flat=True)) == [image.pk]
    values = restored.body.get_prep_value()[0]["value"][0]["value"]["gallery"]
    assert [item["id"] for item in values] == ["old", "new"]
    assert values[1]["value"]["caption"] == "Remember this caption"
    response = admin_client.get(reverse("wagtailadmin_pages:edit", args=[post.pk]))
    assert response.status_code == 200
    assert b"Remember this caption" in response.content


@pytest.mark.django_db
def test_legacy_gallery_chooser_search_still_supports_integer_wrappers(image):
    from cast.blocks import GalleryImageChooserBlock

    block = GalleryImageChooserBlock()
    assert block.get_searchable_content({"value": image.pk}) == [image.default_alt_text]
    image.title = ""
    image.description = ""
    assert block.get_searchable_content(image) == []


@pytest.mark.django_db
@pytest.mark.parametrize("use_lookup", [False, True])
def test_migration_reconstructed_gallery_reads_legacy_items(image, use_lookup):
    from django.utils.module_loading import import_string
    from wagtail.blocks.definition_lookup import BlockDefinitionLookup, BlockDefinitionLookupBuilder

    original = GalleryBlockWithLayout()
    if use_lookup:
        builder = BlockDefinitionLookupBuilder()
        index = builder.add_block(original)
        reconstructed = BlockDefinitionLookup(builder.get_lookup_as_dict()).get_block(index)
    else:
        path, args, kwargs = original.child_blocks["gallery"].child_block.deconstruct()
        item = import_string(path)(*args, **kwargs)
        from cast.blocks import CaptionedGalleryBlock

        reconstructed = GalleryBlockWithLayout([("gallery", CaptionedGalleryBlock(item))])
    value = reconstructed.to_python(
        {
            "layout": "default",
            "gallery": [
                {"type": "item", "id": "old", "value": image.pk},
                {"type": "item", "id": "new", "value": {"image": image.pk, "caption": "Retained"}},
            ],
        }
    )
    stored = reconstructed.get_prep_value(value)["gallery"]
    assert [item["id"] for item in stored] == ["old", "new"]
    assert stored[0]["value"] == {"image": image.pk, "caption": ""}
    assert stored[1]["value"] == {"image": image.pk, "caption": "Retained"}


@pytest.mark.django_db
@pytest.mark.parametrize("use_repository", [True, False])
def test_reloaded_post_render_and_resave_keep_captions(post, image, use_repository):
    from cast.models import Post

    post.body = [
        {
            "type": "overview",
            "value": [
                {
                    "type": "gallery",
                    "value": {
                        "layout": "default",
                        "gallery": [
                            {"type": "item", "id": "first", "value": {"image": image.pk, "caption": "First"}},
                            {"type": "item", "id": "second", "value": {"image": image.pk, "caption": "Second"}},
                        ],
                    },
                }
            ],
        }
    ]
    post.save()
    loaded = Post.objects.get(pk=post.pk)
    repository = EmptyImageRepository()
    if use_repository:
        repository.image_by_id = {image.pk: image}
    gallery = loaded.body[0].value[0]
    context = {"repository": repository, "template_base_dir": "plain"}
    for _ in range(2):
        html = gallery.render(context)
        assert "<figcaption>First</figcaption>" in html
        assert "<figcaption>Second</figcaption>" in html
    loaded.save()
    saved = Post.objects.get(pk=post.pk).body.get_prep_value()[0]["value"][0]["value"]["gallery"]
    assert [item["value"]["caption"] for item in saved] == ["First", "Second"]
    resolved = gallery.block.from_repository_to_python(repository, gallery.value)
    converted_again = gallery.block.from_repository_to_python(repository, resolved)
    assert [item["value"]["caption"] for item in gallery.block.get_prep_value(converted_again)["gallery"]] == [
        "First",
        "Second",
    ]
    assert set(resolved) == {"gallery", "layout"}


@pytest.mark.django_db
def test_normalized_gallery_children_are_struct_values(image):
    from wagtail.blocks import StructValue

    child = GalleryBlockWithLayout().child_blocks["gallery"]
    value = child.normalize([{"type": "item", "id": "kept", "value": image.pk}])
    assert isinstance(value[0], StructValue)
    assert value[0].bound_blocks["image"].value == image.pk
    assert value.bound_blocks[0].id == "kept"
