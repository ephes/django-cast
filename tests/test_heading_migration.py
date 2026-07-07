from __future__ import annotations

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.db.migrations.loader import MigrationLoader
from django.test import override_settings
from django.utils import timezone
from wagtail.models import Revision

from cast.models import Episode, HomePage, Post
from tests.factories import EpisodeFactory, HomePageFactory, PostFactory

migration = __import__("cast.migrations.0080_convert_heading_to_paragraph", fromlist=["*"])


def _heading(block_id: str, value: object = "A & B <x>") -> dict[str, object]:
    return {"type": "heading", "value": value, "id": block_id}


def _post_body() -> list[dict[str, object]]:
    return [
        {
            "type": "overview",
            "value": [
                _heading("overview-heading"),
                _heading("overview-empty", None),
                {"type": "heading", "id": "missing"},
            ],
            "id": "ov",
        },
        {"type": "detail", "value": [_heading("detail-heading")], "id": "de"},
    ]


def _set_raw_body(model: type[Post | HomePage | Episode], pk: int, body: list[dict[str, object]]) -> None:
    field = model._meta.get_field("body")
    adapted_body = connection.ops.adapt_json_value(body, getattr(field, "encoder", None))
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE {table} SET {body_column} = %s WHERE {pk_column} = %s".format(
                table=connection.ops.quote_name(model._meta.db_table),
                body_column=connection.ops.quote_name(field.column),
                pk_column=connection.ops.quote_name(model._meta.pk.column),
            ),
            [adapted_body, pk],
        )


def _get_raw_body(model: type[Post | HomePage | Episode], pk: int) -> list[dict[str, object]]:
    field = model._meta.get_field("body")
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT {body_column} FROM {table} WHERE {pk_column} = %s".format(
                body_column=connection.ops.quote_name(field.column),
                table=connection.ops.quote_name(model._meta.db_table),
                pk_column=connection.ops.quote_name(model._meta.pk.column),
            ),
            [pk],
        )
        raw_body = cursor.fetchone()[0]
    if isinstance(raw_body, str):
        return json.loads(raw_body)
    return raw_body


def test_convert_heading_blocks_is_defensive_and_idempotent():
    body = _post_body()

    changed = migration.convert_heading_blocks(body)
    second_input = deepcopy(body)
    changed_again = migration.convert_heading_blocks(body)

    assert changed is True
    assert changed_again is False
    assert body == second_input
    overview_heading = body[0]["value"][0]
    overview_empty = body[0]["value"][1]
    overview_missing = body[0]["value"][2]
    assert overview_heading == {
        "type": "paragraph",
        "value": "<h2>A &amp; B &lt;x&gt;</h2>",
        "id": "overview-heading",
    }
    assert overview_empty == {"type": "paragraph", "value": "<h2></h2>", "id": "overview-empty"}
    assert overview_missing == {"type": "paragraph", "value": "<h2></h2>", "id": "missing"}


@pytest.mark.django_db
def test_heading_migration_converts_live_bodies_and_revisions(blog, podcast, site):
    post = PostFactory(owner=blog.owner, parent=blog, title="Heading post", slug="heading-post", body=[])
    episode = EpisodeFactory(
        owner=podcast.owner, parent=podcast, title="Heading episode", slug="heading-episode", body=[]
    )
    home_page = HomePageFactory(parent=site.root_page, title="Heading home", slug="heading-home", body=[])
    post_body = _post_body()
    home_body = [_heading("home-heading"), _heading("home-empty", 12)]
    revision_body = [_heading("revision-heading")]
    episode_revision_body = [_heading("episode-revision-heading")]

    _set_raw_body(Post, post.pk, post_body)
    _set_raw_body(HomePage, home_page.pk, home_body)
    post_content_type = ContentType.objects.get_for_model(Post)
    episode_content_type = ContentType.objects.get_for_model(Episode)
    Revision.objects.create(
        content_type=post_content_type,
        base_content_type=post_content_type,
        object_id=str(post.pk),
        created_at=timezone.now(),
        object_str=post.title,
        content={"body": revision_body, "title": post.title},
    )
    Revision.objects.create(
        content_type=episode_content_type,
        base_content_type=episode_content_type,
        object_id=str(episode.pk),
        created_at=timezone.now(),
        object_str=episode.title,
        content={"body": episode_revision_body, "title": episode.title},
    )

    with override_settings(MIGRATION_MODULES={}):
        state = MigrationLoader(connection).project_state(("cast", "0080_convert_heading_to_paragraph"))

    migration.forward(state.apps, SimpleNamespace(connection=connection))
    post_converted = _get_raw_body(Post, post.pk)
    home_converted = _get_raw_body(HomePage, home_page.pk)
    revision_converted = Revision.objects.values_list("content", flat=True).get(
        content_type=post_content_type, object_id=str(post.pk)
    )
    episode_revision_converted = Revision.objects.values_list("content", flat=True).get(
        content_type=episode_content_type, object_id=str(episode.pk)
    )
    before_second_run = deepcopy((post_converted, home_converted, revision_converted, episode_revision_converted))

    migration.forward(state.apps, SimpleNamespace(connection=connection))

    assert _get_raw_body(Post, post.pk) == before_second_run[0]
    assert _get_raw_body(HomePage, home_page.pk) == before_second_run[1]
    assert (
        Revision.objects.values_list("content", flat=True).get(content_type=post_content_type, object_id=str(post.pk))
        == before_second_run[2]
    )
    assert (
        Revision.objects.values_list("content", flat=True).get(
            content_type=episode_content_type, object_id=str(episode.pk)
        )
        == before_second_run[3]
    )
    assert post_converted[0]["value"][0] == {
        "type": "paragraph",
        "value": "<h2>A &amp; B &lt;x&gt;</h2>",
        "id": "overview-heading",
    }
    assert post_converted[0]["value"][1] == {"type": "paragraph", "value": "<h2></h2>", "id": "overview-empty"}
    assert post_converted[0]["value"][2] == {"type": "paragraph", "value": "<h2></h2>", "id": "missing"}
    assert post_converted[1]["value"][0]["id"] == "detail-heading"
    assert post_converted[1]["value"][0]["type"] == "paragraph"
    assert home_converted == [
        {"type": "paragraph", "value": "<h2>A &amp; B &lt;x&gt;</h2>", "id": "home-heading"},
        {"type": "paragraph", "value": "<h2></h2>", "id": "home-empty"},
    ]
    assert revision_converted["body"] == [
        {"type": "paragraph", "value": "<h2>A &amp; B &lt;x&gt;</h2>", "id": "revision-heading"}
    ]
    assert revision_converted["title"] == post.title
    assert episode_revision_converted["body"] == [
        {"type": "paragraph", "value": "<h2>A &amp; B &lt;x&gt;</h2>", "id": "episode-revision-heading"}
    ]
