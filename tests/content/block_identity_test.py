import pytest

from cast.content.blocks import ConversionContext
from cast.content.convert import author_blocks_to_section, section_to_author_blocks
from cast.content.errors import ContentValidationError

STORED = [
    {"id": "a", "type": "paragraph", "value": "<p>First</p>"},
    {"id": "b", "type": "code", "value": {"language": "python", "source": "pass"}},
    {"id": "c", "type": "embed", "value": "https://example.com/"},
]


def test_author_roundtrip_preserves_block_ids_and_reordering():
    ctx = ConversionContext(section="overview", user=None, existing_section=STORED)
    author = section_to_author_blocks(STORED, ctx=ctx)
    assert author[0]["existing_block_id"] == "a"
    assert author_blocks_to_section(author, ctx=ctx) == STORED
    assert author_blocks_to_section(author[::-1], ctx=ctx) == STORED[::-1]
    from uuid import UUID

    new = author_blocks_to_section([{"type": "paragraph", "value": "<p>New</p>"}] * 2, ctx=ctx)
    assert UUID(new[0]["id"]) != UUID(new[1]["id"])


@pytest.mark.parametrize("identity", ["foreign", 42, [], None, ""])
def test_foreign_or_invalid_identity_is_rejected(identity):
    ctx = ConversionContext(section="overview", user=None, existing_section=STORED)
    with pytest.raises(ContentValidationError) as exc:
        author_blocks_to_section(
            [{"type": "paragraph", "value": "<p>First</p>", "existing_block_id": identity}], ctx=ctx
        )
    assert "overview.0.existing_block_id" in exc.value.error_map


@pytest.mark.parametrize("mode", ["duplicate", "wrong_type", "create", "opaque", "ambiguous_source"])
def test_block_identity_cannot_alias_another_block(mode):
    existing = STORED if mode != "create" else None
    if mode == "ambiguous_source":
        existing = [STORED[0], STORED[0]]
    ctx = ConversionContext(section="overview", user=None, existing_section=existing)
    author = [{"type": "paragraph", "value": "<p>First</p>", "existing_block_id": "a"}]
    if mode == "duplicate":
        author *= 2
    elif mode == "wrong_type":
        author[0]["existing_block_id"] = "b"
    elif mode == "opaque":
        author = [
            {
                "type": "unsupported",
                "value": {"stored_type": "embed", "position": "overview.2"},
                "existing_block_id": "a",
            }
        ]
    with pytest.raises(ContentValidationError):
        author_blocks_to_section(author, ctx=ctx)


def test_duplicate_stored_identities_round_trip_as_new_blocks():
    stored = [
        {"id": "a", "type": "paragraph", "value": "<p>One</p>"},
        {"id": "a", "type": "paragraph", "value": "<p>Two</p>"},
        {"id": "b", "type": "code", "value": {"language": "python", "source": "pass"}},
    ]
    ctx = ConversionContext(section="overview", user=None, existing_section=stored)
    author = section_to_author_blocks(stored, ctx=ctx)
    assert ["existing_block_id" in block for block in author] == [False, False, True]
    section = author_blocks_to_section(author, ctx=ctx)
    assert [block["value"] for block in section] == [block["value"] for block in stored]
    assert section[2]["id"] == "b"
    assert len({section[0]["id"], section[1]["id"], "a", "b"}) == 4
