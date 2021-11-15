import pytest

from cast.models.moderation import NaiveBayes, SpamFilter, normalize


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
        ({"spam": 1}, {"spam": 10}, {"spam": 100}, {"spam": 0.1}),
        (
            {"spam": 1, "ham": 0.5},
            {"spam": 10, "ham": 5},
            {"spam": 100, "ham": 50},
            {"spam": 0.1, "ham": 0.05},
        ),
        # no word count -> make sure probability is > 0
        ({"spam": 1}, {}, {"spam": 100}, {"spam": 0.005}),
    ],
)
def test_predict_word_probabilities(probabilities, counts_per_label, number_of_words, expected):
    model = NaiveBayes()
    updated = model.update_probabilities(probabilities, counts_per_label, number_of_words)
    assert updated == expected


@pytest.mark.parametrize(
    "message, expected_probabilities",
    [("foo", {"ham": (1 / 3) * (0.5 / 2), "spam": (2 / 3) * (2 / 5)})],
)
def test_predict(message, expected_probabilities):
    train = [
        ("spam", "foo bar baz"),
        ("spam", "foo asdf bsdf"),
        ("ham", "asdf csdf"),
    ]
    model = NaiveBayes().fit(train)
    probabilities = model.predict(message)
    assert probabilities == normalize(expected_probabilities)


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

    spamfilter.retrain_from_scratch()
    assert spamfilter.model.prior_probabilities == {"ham": 0.5, "spam": 0.5}
