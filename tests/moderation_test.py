import pytest

from cast.models.moderation import Evaluation, NaiveBayes, SpamFilter, normalize


@pytest.mark.parametrize(
    "train, expected_initial_probabilities",
    [
        ([], {}),
        ([("ham", ""), ("spam", "")], {"ham": 0.5, "spam": 0.5}),
        ([(i, "") for i in range(3)], {k: 1 / 3 for k in range(3)}),
    ],
)
def test_initial_probabilities(train, expected_initial_probabilities):
    model = NaiveBayes().fit(train)
    assert model.predict("") == expected_initial_probabilities


@pytest.mark.parametrize(
    "probabilities, counts_per_label, number_of_words, expected",
    [
        ({}, {}, {}, {}),
        ({"spam": 1}, {"spam": 10}, 100, {"spam": 0.1}),
        (
            {"spam": 1, "ham": 0.5},
            {"spam": 10, "ham": 5},
            100,
            {"spam": 0.1, "ham": 0.025},
        ),
        # no word count -> make sure probability is > 0
        ({"spam": 1}, {}, 100, {"spam": 0.005}),
    ],
)
def test_predict_word_probabilities(probabilities, counts_per_label, number_of_words, expected):
    model = NaiveBayes()
    updated = model.update_probabilities(probabilities, counts_per_label, number_of_words)
    assert updated == expected


@pytest.mark.parametrize(
    "message, expected_probabilities",
    [("foo", {"ham": (1 / 3) * (0.5 / 6), "spam": (2 / 3) * (2 / 6)})],
)
def test_predict(message, expected_probabilities):
    train = [
        ("spam", "foo bar baz"),
        ("spam", "foo asdf bsdf"),
        ("ham", "asdf csdf"),
    ]
    model = NaiveBayes().fit(train)
    expected_probabilities = normalize(expected_probabilities)
    probabilities = model.predict(message)
    for label, probability in probabilities.items():
        assert probability == pytest.approx(expected_probabilities[label])


@pytest.mark.parametrize(
    "train, message, expected_label",
    [
        ([], "asdf", None),
        ([("spam", "foo bar baz")], "asdf", "spam"),
    ],
)
def test_predict_label(train, message, expected_label):
    model = NaiveBayes().fit(train)
    label = model.predict_label(message)
    assert label == expected_label


def test_lots_of_unknown_tokens_lead_to_ham_if_spam_has_more_words():
    """
    There was a bug calculating the probabilities of unknown tokens:

    The probability for unknown tokens was calculated as 0.5 / number_of_words_in_class.
    Since there are much more tokens in spam than in ham, the probability for unknown
    tokens was much higher for ham than for spam. This lead to comments with lots of unknown tokens
    to be classified as ham. Doh.
    """
    train = [
        ("spam", " ".join([str(i) for i in range(100)])),
        ("ham", "asdf bsdf"),
    ]
    model = NaiveBayes().fit(train)
    message = "foo bar baz 87"  # should be spam because of 87
    predicted_label = model.predict_label(message)
    assert predicted_label == "spam"


@pytest.mark.django_db()
def test_model_default_serialization():
    class StubModel:
        foo = "blub"

    spamfilter = SpamFilter(name="stub model", model=StubModel())
    with pytest.raises(TypeError):
        # StubModel is not json serializable -> TypeError
        # makes sure return super().default(obj) for ModelEncoder is called
        spamfilter.save()


@pytest.mark.django_db()
def test_model_naive_bayes_serialization():
    train = [
        ("spam", "foo bar baz"),
        ("ham", "asdf bsdf csdf"),
    ]
    model = NaiveBayes().fit(train)
    spamfilter = SpamFilter(name="naive bayes", model=model)
    spamfilter.save()

    spamfilter.refresh_from_db()
    model_from_db = spamfilter.model
    assert model_from_db == model


@pytest.mark.django_db()
def test_spamfilter_retrain_from_scratch(comment, comment_spam):
    """
    Make sure data from comments is used when retraining
    spamfilter from scratch.
    """
    model = NaiveBayes().fit([])
    spamfilter = SpamFilter(name="naive bayes", model=model)
    spamfilter.save()
    assert spamfilter.model.prior_probabilities == {}

    train = SpamFilter.get_training_data_comments()
    # Three rows are required by the default three-fold evaluation.
    spamfilter.retrain_from_scratch(train * 2)
    assert spamfilter.model.prior_probabilities == {"ham": 0.5, "spam": 0.5}


def test_evaluate_model_non_empty_test_messages():
    class Model:
        prior_probabilities = {"spam": 0.5, "ham": 0.5}

        @staticmethod
        def predict_label(message):
            return "spam"

    messages = [("spam", "foo bar baz"), ("ham", "asdf bsdf csdf")]
    label_results = Evaluation.evaluate_model(Model(), messages)
    assert label_results["spam"]["true_positive"] == 1  # first message is tp
    assert label_results["spam"]["false_positive"] == 1  # second message is fp


def test_get_precision_recall_f1():
    counts = {
        "ham": {"true_positive": 1, "true_negative": 1, "false_positive": 1, "false_negative": 1},
    }
    precision, recall, f1 = Evaluation.get_precision_recall_f1(counts["ham"])
    assert (precision, recall, f1) == (0.5, 0.5, 0.5)


def test_calc_performance():
    counts = {
        "spam": {"true_positive": 1, "true_negative": 1, "false_positive": 1, "false_negative": 1},
        "ham": {"true_positive": 1, "true_negative": 1, "false_positive": 1, "false_negative": 1},
    }
    performance = Evaluation().calc_performance(counts)
    assert tuple(performance["spam"].values()) == (0.5, 0.5, 0.5)
    assert tuple(performance["ham"].values()) == (0.5, 0.5, 0.5)


def test_evaluate_with_some_messages():
    class Model:
        prior_probabilities = {"spam": 0.5, "ham": 0.5}

        @staticmethod
        def predict_label(message):
            return "spam"

        def fit(self, _train):
            return self

    messages = [("spam", "foo bar baz"), ("ham", "asdf bsdf csdf")]
    evaluation = Evaluation(model_class=Model, num_folds=1)
    performance = evaluation.evaluate(messages)
    assert performance["spam"]["precision"] == 0.5

    messages = []
    with pytest.raises(ValueError):
        evaluation.evaluate(messages)


@pytest.mark.parametrize("restore", [False, True])
def test_refit_replaces_all_training_state(restore):
    import json

    from cast.models.moderation import ModelDecoder, ModelEncoder

    model = NaiveBayes().fit([("ham", "oldword"), ("spam", "spamword")])
    if restore:
        model = json.loads(json.dumps(model, cls=ModelEncoder), cls=ModelDecoder)
    train = [("newlabel", "newword newword")]
    model.fit(train)
    fresh = NaiveBayes().fit(train)
    assert model == fresh
    assert model.number_of_words == fresh.number_of_words
    assert model.number_of_all_words == fresh.number_of_all_words
    model.fit([])
    assert model == NaiveBayes().fit([])
    assert model.number_of_all_words == 0


@pytest.mark.django_db
@pytest.mark.parametrize("message", ["", "ordinary incoming comment"])
def test_tokenless_persisted_classifier_uses_priors(message):
    from types import SimpleNamespace

    from cast.moderation import Moderator

    train = [("ham", ""), ("ham", "a"), ("spam", "x")]
    spamfilter = SpamFilter.objects.create(name="tokenless", model=NaiveBayes().fit(train))
    spamfilter.refresh_from_db()
    assert spamfilter.model.predict(message) == {"ham": 2 / 3, "spam": 1 / 3}
    comment = SimpleNamespace(name="", email="", title="", comment=message)
    assert Moderator(None, spamfilter).moderate(comment, None, None) is False
    assert comment.is_public and not comment.is_removed


@pytest.mark.parametrize("stratified", [False, True])
def test_folds_retain_every_row_without_mutating_input(stratified):
    messages = [("ham", str(i)) for i in range(5)] + [("spam", str(i)) for i in range(5, 9)]
    original = messages[:]
    folds = (
        Evaluation(num_folds=4).stratified_split_into_folds(messages)
        if stratified
        else Evaluation.split_into_folds(messages, 4)
    )
    assert messages == original
    assert sorted(row for fold in folds for row in fold) == sorted(messages)
    assert max(map(len, folds)) - min(map(len, folds)) <= 1
    if stratified:
        for label in ("ham", "spam"):
            counts = [sum(row[0] == label for row in fold) for fold in folds]
            assert max(counts) - min(counts) <= 1


def test_evaluation_pools_confusion_counts_from_all_folds(monkeypatch):
    class Model:
        prior_probabilities = {"ham": 0.5, "spam": 0.5}

        def fit(self, train):
            return self

        def predict_label(self, message):
            return message

    folds = [[("ham", "ham")], [("ham", "spam"), ("spam", "spam")], [("spam", "ham")]]
    evaluation = Evaluation(model_class=Model)
    monkeypatch.setattr(evaluation, "stratified_split_into_folds", lambda messages: folds)
    performance = evaluation.evaluate([row for fold in folds for row in fold])
    assert performance == {label: {"precision": 0.5, "recall": 0.5, "f1": 0.5} for label in ("ham", "spam")}


@pytest.mark.parametrize("prediction", ["ham", "alien", None])
def test_evaluate_unseen_actual_and_predicted_labels(prediction):
    class Model:
        prior_probabilities = {"ham": 1.0}

        def predict_label(self, message):
            return prediction

    results = Evaluation.evaluate_model(Model(), [("spam", "new message")])
    assert results["spam"]["false_negative"] == 1
    if prediction is not None:
        assert results[prediction]["false_positive"] == 1
    assert None not in results


def test_evaluate_empty_model_counts_miss():
    results = Evaluation.evaluate_model(NaiveBayes().fit([]), [("spam", "message")])
    assert results["spam"]["false_negative"] == 1


@pytest.mark.parametrize("folds", [0, True, False, -1, 1.5, "3", None])
def test_invalid_fold_count_refused(folds):
    with pytest.raises(ValueError, match="fold count"):
        Evaluation(num_folds=folds)
    with pytest.raises(ValueError, match="fold count"):
        Evaluation.split_into_folds([("ham", "hello")], folds)


@pytest.mark.parametrize("messages,folds", [([], 3), ([("ham", "hi")], 3), ([("ham", "hi")], 2)])
def test_evaluation_refuses_undersized_corpus_before_training(messages, folds, mocker):
    model = mocker.Mock()
    with pytest.raises(ValueError, match="corpus"):
        Evaluation(model_class=model, num_folds=folds).evaluate(messages)
    model.assert_not_called()


@pytest.mark.django_db
def test_retrain_preserves_concurrent_name_edit(monkeypatch):
    spamfilter = SpamFilter.objects.create(name="original")
    train = [("ham", "greetings")] * 3

    def evaluate(evaluation, messages):
        SpamFilter.objects.filter(pk=spamfilter.pk).update(name="renamed concurrently")
        return {"ham": {"precision": 1, "recall": 1, "f1": 1}}

    monkeypatch.setattr(Evaluation, "evaluate", evaluate)
    spamfilter.retrain_from_scratch(train)
    spamfilter.refresh_from_db()
    assert spamfilter.name == "renamed concurrently"
    assert spamfilter.model == NaiveBayes().fit(train)
    assert spamfilter.performance["ham"]["f1"] == 1


@pytest.mark.parametrize("probabilities", [{}, {"ham": 0, "spam": 0}])
def test_normalize_zero_sum_keeps_probabilities(probabilities):
    assert normalize(probabilities.copy()) == probabilities
