import json
import random
import re
import uuid
from collections import defaultdict
from collections.abc import Callable, Iterator
from typing import Any, Optional

from django.core.serializers.json import DjangoJSONEncoder
from django.db import models, router
from django.utils import timezone
from model_utils.models import TimeStampedModel

token_pattern = re.compile(r"(?u)\b\w\w+\b")
standard_tokenizer = token_pattern.findall


def regex_tokenize(message: str) -> list[str]:
    return standard_tokenizer(message.lower())


Probabilities = dict[str, float]
Counts = dict[str, int]


def normalize(probabilities: Probabilities) -> Probabilities:
    try:
        factor = 1.0 / float(sum(probabilities.values()))
    except ZeroDivisionError:
        # not possible to scale -> skip
        return probabilities
    for name, value in probabilities.items():
        probabilities[name] *= factor
    return probabilities


Messages = list[tuple[str, str]]


class NaiveBayes:
    def __init__(
        self,
        tokenize: Callable = regex_tokenize,
        prior_probabilities: Probabilities | None = None,
        word_label_counts: dict[str, Counts] | None = None,
    ):
        self.tokenize = tokenize
        if prior_probabilities is None:
            prior_probabilities = {}
        self.prior_probabilities = prior_probabilities
        if word_label_counts is None:
            self.word_label_counts: dict[str, Counts] = defaultdict(lambda: defaultdict(int))
        else:
            self.word_label_counts = word_label_counts
        self.number_of_words = self.get_number_of_words(self.word_label_counts)
        self.number_of_all_words = sum(self.number_of_words.values())

    @staticmethod
    def get_label_counts(messages: Messages) -> Counts:
        label_counts: Counts = defaultdict(int)
        for label, text in messages:
            label_counts[label] += 1
        return label_counts

    def set_prior_probabilities(self, label_counts: Counts) -> None:
        number_of_messages = sum(label_counts.values())
        self.prior_probabilities = {label: count / number_of_messages for label, count in label_counts.items()}

    def set_word_label_counts(self, messages: Messages) -> None:
        self.word_label_counts = defaultdict(lambda: defaultdict(int))
        counts = self.word_label_counts
        for label, text in messages:
            for word in self.tokenize(text):
                counts[word][label] += 1

    @staticmethod
    def get_number_of_words(word_label_counts: dict[str, Counts]) -> Counts:
        number_of_words: Counts = defaultdict(int)
        for word, counts in word_label_counts.items():
            for label, count in counts.items():
                number_of_words[label] += 1
        return number_of_words

    def fit(self, messages: Messages) -> "NaiveBayes":
        self.set_prior_probabilities(self.get_label_counts(messages))
        self.set_word_label_counts(messages)
        self.number_of_words = self.get_number_of_words(self.word_label_counts)
        self.number_of_all_words = sum(self.number_of_words.values())
        return self

    @staticmethod
    def update_probabilities(
        probabilities: Probabilities, counts_per_label: Counts, number_of_all_words: int
    ) -> Probabilities:
        updated_probabilities = {}
        for label, prior_probability in probabilities.items():
            word_count = counts_per_label.get(label, 0.5)
            word_probability = word_count / number_of_all_words
            updated_probabilities[label] = prior_probability * word_probability
        return updated_probabilities

    def predict(self, message: str) -> Probabilities:
        probabilities = dict(self.prior_probabilities)
        if not self.number_of_all_words:
            return probabilities
        for word in self.tokenize(message):
            counts_per_label = self.word_label_counts.get(word, {})
            probabilities = normalize(
                self.update_probabilities(probabilities, counts_per_label, self.number_of_all_words)
            )
        return probabilities

    def predict_label(self, message: str) -> str | None:
        probabilities = self.predict(message)
        if len(probabilities) == 0:
            return None
        return sorted(((prob, label) for label, prob in probabilities.items()), reverse=True)[0][1]

    def dict(self) -> dict[str, Any]:
        return {
            "class": "NaiveBayes",
            "prior_probabilities": self.prior_probabilities,
            "word_label_counts": self.word_label_counts,
        }

    def __eq__(self, other: Any) -> bool:
        return (
            self.prior_probabilities == other.prior_probabilities and self.word_label_counts == other.word_label_counts
        )


class ModelEncoder(DjangoJSONEncoder):
    def default(self, obj: Any) -> dict:
        if isinstance(obj, NaiveBayes):
            return obj.dict()
        return super().default(obj)


class ModelDecoder(json.JSONDecoder):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs["object_hook"] = self.model_decode
        super().__init__(*args, **kwargs)

    @staticmethod
    def model_decode(obj: dict[str, Any]) -> Any:
        if obj.get("class") == "NaiveBayes":
            del obj["class"]
            return NaiveBayes(**obj)
        return obj


Performance = dict[str, float]


class Evaluation:
    """Simple cross validation evaluation."""

    def __init__(self, model_class: type = NaiveBayes, num_folds: int = 3):
        self.validate_fold_count(num_folds)
        self.model_class = model_class
        self.num_folds = num_folds

    @staticmethod
    def validate_fold_count(num_folds: int) -> None:
        if type(num_folds) is not int or num_folds < 1:
            raise ValueError("fold count must be a positive integer")

    @staticmethod
    def split_into_labels(messages: Messages) -> dict[str, Messages]:
        """Split messages into a dict of labels and labeled messages."""
        data_per_label = defaultdict(list)
        for label, text in messages:
            data_per_label[label].append((label, text))
        return data_per_label

    @staticmethod
    def split_into_folds(messages: Messages, num_folds: int) -> list[Messages]:
        """
        Split the messages into num_folds folds.
        """
        Evaluation.validate_fold_count(num_folds)
        shuffled = list(messages)
        random.shuffle(shuffled)
        return [shuffled[i::num_folds] for i in range(num_folds)]

    def stratified_split_into_folds(self, messages: Messages) -> list[Messages]:
        """Balance every label and the total population without dropping rows."""
        folds: list[Messages] = [[] for _ in range(self.num_folds)]
        offset = 0
        for labeled_messages in self.split_into_labels(messages).values():
            for i, fold in enumerate(self.split_into_folds(labeled_messages, self.num_folds)):
                folds[(offset + i) % self.num_folds].extend(fold)
            offset = (offset + len(labeled_messages)) % self.num_folds
        return folds

    @staticmethod
    def generate_train_test(folds: list[Messages]) -> Iterator[tuple[Messages, Messages]]:
        """From a list of n cross-validation folds, generate n train and test sets."""
        for i, n in enumerate(folds):
            all_but_n = []
            for j, m in enumerate(folds):
                if i != j:
                    all_but_n.extend(m)
            yield all_but_n, n

    @staticmethod
    def evaluate_model(model: Any, test_messages: Messages) -> dict[str, Counts]:
        """Build a confusion matrix for the model on the test messages."""
        outcomes = (("true", "false"), ("positive", "negative"))
        possible_results = [f"{a}_{b}" for b in outcomes[1] for a in outcomes[0]]
        result_template = dict.fromkeys(possible_results, 0)

        labels = set(model.prior_probabilities) | {label for label, _ in test_messages}
        label_results = {label: dict(result_template) for label in labels}

        for label, message in test_messages:
            predicted = model.predict_label(message)
            if label == predicted:
                label_results[label]["true_positive"] += 1
            else:
                label_results[label]["false_negative"] += 1
                if predicted is not None:
                    label_results.setdefault(predicted, dict(result_template))["false_positive"] += 1
        return label_results

    @staticmethod
    def get_precision_recall_f1(result: Counts) -> tuple[float, float, float]:
        """Actual implementation of precision, recall and f1 from tp, fp, fn."""
        tp = result["true_positive"]
        fp = result["false_positive"]
        fn = result["false_negative"]
        precision = tp / (tp + fp) if tp + fp > 0 else 0
        recall = tp / (tp + fn) if tp + fn > 0 else 0
        try:
            f1 = 2 * precision * recall / (precision + recall)
        except ZeroDivisionError:
            f1 = 0
        return precision, recall, f1

    def calc_performance(self, results: dict[str, Counts]) -> dict[str, Performance]:
        """Calc precision, recall and f1 for each label."""
        performance = {}
        for label, result in results.items():
            precision, recall, f1 = self.get_precision_recall_f1(result)
            performance[label] = {
                "precision": precision,
                "recall": recall,
                "f1": f1,
            }
        return performance

    def evaluate(self, messages: Messages) -> dict[str, Performance]:
        """
        Evaluate the model on the given messages. Use stratified cross validation
        to determine precision, recall and f1 score.
        """
        self.validate_fold_count(self.num_folds)
        if len(messages) < self.num_folds:
            raise ValueError("corpus must contain at least one message per fold")
        folds = self.stratified_split_into_folds(messages)
        results: dict[str, Counts] = {}
        for train, test in self.generate_train_test(folds):
            model = self.model_class().fit(train)
            for label, counts in self.evaluate_model(model, test).items():
                pooled = results.setdefault(label, dict.fromkeys(counts, 0))
                for outcome, count in counts.items():
                    pooled[outcome] += count
        return self.calc_performance(results)


class SpamFilter(TimeStampedModel):
    """
    A Django model that stores a trained spam filter.

    The model itself is stored in the model JSONField. There's a second JSONField
    where some performance indicators like precision, recall and f1 are stored.

    There are some helper methods to generate training data from comments and
    retrain the model from scratch for example when a significant amount of
    new training data was added.
    """

    name = models.CharField(unique=True, max_length=128)
    model = models.JSONField(verbose_name="Spamfilter Model", default=dict, encoder=ModelEncoder, decoder=ModelDecoder)
    performance = models.JSONField(verbose_name="Spamfilter Performance Indicators", default=dict)
    retrain_attempt = models.UUIDField(null=True, editable=False)

    @classmethod
    def comment_to_message(cls, comment: Any) -> str:
        return f"{comment.name} {comment.email} {comment.title} {comment.comment}"

    @classmethod
    def get_training_data_comments(cls) -> Messages:
        """
        Keep this as a classmethod in SpamFilter to make it available for all code importing SpamFilter.
        """
        from django_comments import get_model as get_comments_model

        from cast.comments import author_edits

        comment_class = get_comments_model()
        # Author-deleted comments are excluded entirely: a legitimate comment the
        # author removed must not be labelled spam and poison the filter.
        deleted_pks = author_edits.deleted_comment_pks()
        train = []
        for comment in comment_class.objects.all():
            if str(comment.pk) in deleted_pks:
                continue
            label = "ham" if (comment.is_public and not comment.is_removed) else "spam"
            message = cls.comment_to_message(comment)
            train.append((label, message))
        return train

    def retrain_from_scratch(self, train: Messages | None = None) -> None:
        """Publish only the most recently started attempt's model and metrics."""
        if self.pk is None:
            raise ValueError("Save the spam filter before retraining")
        using = self._state.db or router.db_for_write(type(self), instance=self)
        filters = type(self).objects.using(using).filter(pk=self.pk)
        attempt = uuid.uuid4()
        filters.update(retrain_attempt=attempt)
        # Reserve authority before taking the admin corpus snapshot. Callers may
        # also supply an explicit corpus, whose attempt starts at this method.
        if train is None:
            train = self.get_training_data_comments()
        performance = Evaluation().evaluate(train)
        model = NaiveBayes().fit(train)
        filters.filter(retrain_attempt=attempt).update(model=model, performance=performance, modified=timezone.now())
        self.refresh_from_db(using=using)

    @property
    def is_trained(self) -> bool:
        return isinstance(self.model, NaiveBayes) and bool(self.model.prior_probabilities)

    @classmethod
    def get_default(cls) -> Optional["SpamFilter"]:
        return next((spamfilter for spamfilter in cls.objects.order_by("pk") if spamfilter.is_trained), None)
