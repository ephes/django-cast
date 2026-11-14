"""Separate database connections exercise retraining publication authority."""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.db import close_old_connections

from cast.models.moderation import Evaluation, NaiveBayes, SpamFilter


@pytest.mark.django_db(transaction=True)
def test_older_retrain_cannot_replace_newer_publication(monkeypatch):
    spamfilter = SpamFilter.objects.create(name="overlap")
    old = [("spam", "old corpus")] * 3
    new = [("ham", "new corpus")] * 3
    evaluating = threading.Event()
    release = threading.Event()

    def evaluate(evaluation, messages):
        label = messages[0][0]
        if label == "spam":
            evaluating.set()
            assert release.wait(10)
        return {label: {"precision": 1, "recall": 1, "f1": 1}}

    monkeypatch.setattr(Evaluation, "evaluate", evaluate)

    def retrain(messages):
        close_old_connections()
        try:
            SpamFilter.objects.get(pk=spamfilter.pk).retrain_from_scratch(messages)
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(retrain, old)
        try:
            assert evaluating.wait(10)
            pool.submit(retrain, new).result(timeout=10)
        finally:
            release.set()
        first.result(timeout=10)
    spamfilter.refresh_from_db()
    assert spamfilter.model == NaiveBayes().fit(new)
    assert spamfilter.performance == {"ham": {"precision": 1, "recall": 1, "f1": 1}}


@pytest.mark.django_db
def test_failed_evaluation_keeps_published_model_and_metrics(monkeypatch):
    old = NaiveBayes().fit([("ham", "old")])
    metrics = {"ham": {"precision": 1, "recall": 1, "f1": 1}}
    spamfilter = SpamFilter.objects.create(name="failed", model=old, performance=metrics)

    def fail(evaluation, messages):
        raise ValueError("evaluation failed")

    monkeypatch.setattr(Evaluation, "evaluate", fail)
    with pytest.raises(ValueError, match="evaluation failed"):
        spamfilter.retrain_from_scratch([("spam", "new")] * 3)
    spamfilter.refresh_from_db()
    assert spamfilter.model == old
    assert spamfilter.performance == metrics


def test_unsaved_filter_refuses_retraining():
    with pytest.raises(ValueError, match="Save the spam filter"):
        SpamFilter(name="unsaved").retrain_from_scratch([])


@pytest.mark.django_db
def test_admin_style_retrain_reserves_before_snapshot(monkeypatch):
    spamfilter = SpamFilter.objects.create(name="snapshot")
    old = [("spam", "old corpus")] * 3
    new = [("ham", "new corpus")] * 3

    def collect(cls):
        # Another run publishes after this run entered snapshot collection.
        newer = SpamFilter.objects.get(pk=spamfilter.pk)
        assert newer.retrain_attempt is not None
        newer.retrain_from_scratch(new)
        return old

    monkeypatch.setattr(SpamFilter, "get_training_data_comments", classmethod(collect))
    spamfilter.retrain_from_scratch()
    spamfilter.refresh_from_db()
    assert spamfilter.model == NaiveBayes().fit(new)


@pytest.mark.django_db(transaction=True)
def test_newer_failed_attempt_still_supersedes_older_work(monkeypatch):
    initial = NaiveBayes().fit([("ham", "initial model")])
    spamfilter = SpamFilter.objects.create(name="failed newer", model=initial, performance={"initial": {}})
    old = [("spam", "old corpus")] * 3
    evaluating = threading.Event()
    release = threading.Event()

    def evaluate(evaluation, messages):
        if not messages:
            raise ValueError("corpus too small")
        evaluating.set()
        assert release.wait(10)
        return {"spam": {"precision": 1}}

    monkeypatch.setattr(Evaluation, "evaluate", evaluate)

    def older():
        close_old_connections()
        try:
            SpamFilter.objects.get(pk=spamfilter.pk).retrain_from_scratch(old)
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(older)
        try:
            assert evaluating.wait(10)
            # Validation refuses this before any model training.
            with pytest.raises(ValueError, match="corpus"):
                spamfilter.retrain_from_scratch([])
        finally:
            release.set()
        first.result(timeout=10)
    spamfilter.refresh_from_db()
    assert spamfilter.model == initial
    assert spamfilter.performance == {"initial": {}}
