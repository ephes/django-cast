"""Facet membership stays in SQL and all facet reads share one generation."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from django.db import close_old_connections, connection, transaction
from taggit.models import Tag

from cast import modal_facet_counts as facets
from cast.models import Post


@pytest.mark.django_db
def test_fallback_keeps_large_membership_in_sql():
    Tag.objects.bulk_create([Tag(name=f"Synthetic {i}", slug=f"synthetic-{i}") for i in range(1100)])
    result = facets._queryset_from_pk_fallback(Tag.objects.filter(slug__startswith="synthetic-"))
    _, params = result.query.sql_with_params()
    assert len(params) < 10
    assert result.count() == 1100


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("change", ["withdraw", "retag"])
def test_facets_keep_committed_generation_during_concurrent_publish(pg_editor_actors, request, monkeypatch, change):
    _, blog = pg_editor_actors
    post = request.getfixturevalue("post")
    post.tags.add("old")
    post.save()
    original_mode = None
    if connection.vendor == "sqlite":
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA journal_mode")
            original_mode = cursor.fetchone()[0]
            cursor.execute("PRAGMA journal_mode=WAL")
    try:
        before = facets.get_modal_facet_counts(blog, {})
        original = facets._count_posts
        changed = False

        def change_publication():
            close_old_connections()
            try:
                with transaction.atomic():
                    if change == "withdraw":
                        Post.objects.filter(pk=post.pk).update(live=False)
                    else:
                        updated = Post.objects.get(pk=post.pk)
                        updated.tags.set(["new"])
                        updated.save()
            finally:
                close_old_connections()

        def after_first_read(*args):
            nonlocal changed
            result = original(*args)
            if not changed:
                changed = True
                with ThreadPoolExecutor(max_workers=1) as pool:
                    pool.submit(change_publication).result(timeout=10)
            return result

        monkeypatch.setattr(facets, "_count_posts", after_first_read)
        during = facets.get_modal_facet_counts(blog, {})
        assert changed
        assert during == before
        after = facets.get_modal_facet_counts(blog, {})
        assert after != before
        assert after["result_count"] == (0 if change == "withdraw" else 1)
    finally:
        if original_mode is not None:
            with connection.cursor() as cursor:
                cursor.execute(f"PRAGMA journal_mode={original_mode}")


@pytest.mark.django_db
@pytest.mark.parametrize(
    "nested,isolation", [(False, None), (True, "repeatable read"), (True, "serializable"), (True, "read committed")]
)
def test_postgres_snapshot_isolation_contract(mocker, nested, isolation):
    fake = mocker.MagicMock(vendor="postgresql", in_atomic_block=nested)
    fake.cursor.return_value.__enter__.return_value.fetchone.return_value = (isolation,)
    mocker.patch.object(facets, "connections", {"snapshot": fake})
    atomic = mocker.patch.object(facets.transaction, "atomic")
    if isolation == "read committed":
        with pytest.raises(facets.FacetSnapshotUnavailable):
            with facets._facet_snapshot("snapshot"):
                pass
    else:
        with facets._facet_snapshot("snapshot"):
            pass
    atomic.assert_called_once_with(using="snapshot")
    sql = fake.cursor.return_value.__enter__.return_value.execute.call_args.args[0]
    assert sql == (
        "SHOW transaction_isolation" if nested else "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
    )


def test_unsupported_snapshot_backend(mocker):
    mocker.patch.object(facets, "connections", {"unsupported": mocker.Mock(vendor="other")})
    with pytest.raises(facets.FacetSnapshotUnavailable):
        with facets._facet_snapshot("unsupported"):
            pass
    with pytest.raises(facets.FacetSnapshotUnavailable):
        facets._queryset_from_pk_fallback(object())


@pytest.mark.django_db
@pytest.mark.parametrize("backend", [object(), "invalid-queryset", "queryset"])
def test_search_requires_database_membership(mocker, backend):
    from types import SimpleNamespace

    if isinstance(backend, str):
        result = Post.objects.none() if backend == "queryset" else []
        backend_result = SimpleNamespace(get_queryset=lambda: result)
    else:
        backend_result = backend
    mocker.patch.object(facets, "safe_modelsearch_results", return_value=backend_result)
    selection = facets._normalize_selection({"search": "synthetic"})
    if backend == "queryset":
        assert not facets._apply_selection(Post.objects.all(), selection).exists()
    else:
        with pytest.raises(facets.FacetSnapshotUnavailable):
            facets._apply_selection(Post.objects.all(), selection)


@pytest.mark.django_db
def test_unsupported_search_snapshot_is_explicit_503(api_client, blog, mocker):
    from django.urls import reverse

    mocker.patch.object(facets, "safe_modelsearch_results", return_value=object())
    response = api_client.get(
        reverse("cast:api:facet-counts-detail", args=[blog.pk]), {"mode": "modal", "search": "synthetic"}
    )
    assert response.status_code == 503
    assert response.json()["code"] == "facet_snapshot_unavailable"


@pytest.mark.django_db
def test_normalized_empty_search_preserves_no_match_semantics(blog, post):
    result = facets.get_modal_facet_counts(blog, {"search": "\x00--"})
    assert result["result_count"] == 0
    for group in result["groups"].values():
        assert group["all_count"] == 0
