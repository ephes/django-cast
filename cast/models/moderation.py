import json
import random
import re
from collections import defaultdict

from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django_comments import get_model as get_comments_model
from model_utils.models import TimeStampedModel

token_pattern = re.compile(r"(?u)\b\w\w+\b")
standard_tokenizer = token_pattern.findall


def regex_tokenize(message):
    return standard_tokenizer(message.lower())


def normalize(probabilities):
    try:
        factor = 1.0 / float(sum(probabilities.values()))
    except ZeroDivisionError:
        # not possible to scale -> skip
        return probabilities
    for name, value in probabilities.items():
        probabilities[name] *= factor
    return probabilities


class NaiveBayes:
    def __init__(self, tokenize=regex_tokenize, prior_probabilities=None, word_label_counts=None):
        self.tokenize = tokenize
        if prior_probabilities is None:
            prior_probabilities = {}
        self.prior_probabilities = prior_probabilities
        if word_label_counts is None:
            self.word_label_counts = defaultdict(lambda: defaultdict(int))
        else:
            self.word_label_counts = word_label_counts
        self.number_of_words = self.get_number_of_words(self.word_label_counts)
        self.number_of_all_words = 0

    @staticmethod
    def get_label_counts(messages):
        label_counts = defaultdict(int)
        for label, text in messages:
            label_counts[label] += 1
        return label_counts

    def set_prior_probabilities(self, label_counts):
        number_of_messages = sum(label_counts.values())
        self.prior_probabilities = {label: count / number_of_messages for label, count in label_counts.items()}

    def set_word_label_counts(self, messages):
        counts = self.word_label_counts
        for label, text in messages:
            for word in self.tokenize(text):
                counts[word][label] += 1

    @staticmethod
    def get_number_of_words(word_label_counts):
        number_of_words = defaultdict(int)
        for word, counts in word_label_counts.items():
            for label, count in counts.items():
                number_of_words[label] += 1
        return number_of_words

    def fit(self, messages):
        self.set_prior_probabilities(self.get_label_counts(messages))
        self.set_word_label_counts(messages)
        self.number_of_words = self.get_number_of_words(self.word_label_counts)
        self.number_of_all_words = sum(self.number_of_words.values())
        return self

    @staticmethod
    def update_probabilities(probabilities, counts_per_label, number_of_all_words):
        updated_probabilities = {}
        for label, prior_probability in probabilities.items():
            word_count = counts_per_label.get(label, 0.5)
            word_probability = word_count / number_of_all_words
            updated_probabilities[label] = prior_probability * word_probability
        return updated_probabilities

    def predict(self, message):
        probabilities = dict(self.prior_probabilities)
        for word in self.tokenize(message):
            counts_per_label = self.word_label_counts.get(word, {})
            probabilities = normalize(
                self.update_probabilities(probabilities, counts_per_label, self.number_of_all_words)
            )
        return probabilities

    def predict_label(self, message):
        probabilities = self.predict(message)
        if len(probabilities) == 0:
            return None
        return sorted(((prob, label) for label, prob in probabilities.items()), reverse=True)[0][1]

    def dict(self):
        return {
            "class": "NaiveBayes",
            "prior_probabilities": self.prior_probabilities,
            "word_label_counts": self.word_label_counts,
        }

    def __eq__(self, other):
        return (
            self.prior_probabilities == other.prior_probabilities and self.word_label_counts == other.word_label_counts
        )


class ModelEncoder(DjangoJSONEncoder):
    def default(self, obj):
        if isinstance(obj, NaiveBayes):
            return obj.dict()
        return super().default(obj)


class ModelDecoder(json.JSONDecoder):
    def __init__(self, *args, **kwargs):
        kwargs["object_hook"] = self.model_decode
        super().__init__(*args, **kwargs)

    @staticmethod
    def model_decode(obj):
        if obj.get("class") == "NaiveBayes":
            del obj["class"]
            return NaiveBayes(**obj)
        return obj


def comment_to_message(comment):
    return f"{comment.name} {comment.email} {comment.title} {comment.comment}"


def get_training_data_from_comments():
    """
    Get all comments from database and label them as spam or ham.

    If a comment is public and not removed, it is ham. In all other
    cases it is labeled as spam.
    """
    comment_model = get_comments_model()
    train = []
    for comment in comment_model.objects.all():
        label = "ham" if (comment.is_public and not comment.is_removed) else "spam"
        message = comment_to_message(comment)
        train.append((label, message))
    return train


def flatten(items):
    """Flatten a list of lists into one list."""
    return [item for sublist in items for item in sublist]


def precision_recall_f1(result):
    tp = result["true_positive"]
    fp = result["false_positive"]
    fn = result["false_negative"]
    precision = tp / (tp + fp)
    recall = tp / (tp + fn)
    f1 = 2 * (precision * recall) / (precision + recall)
    return precision, recall, f1


def show_result(label_results):
    for label, result in label_results.items():
        precision, recall, f1 = precision_recall_f1(result)
        print(f"{label: >4} f1: {f1:.3f} precision: {precision:.3f} recall: {recall:.3f}")


class Evaluation:
    def __init__(self, model_class=NaiveBayes, num_folds=3):
        self.model_class = model_class
        self.num_folds = num_folds

    @staticmethod
    def split_into_labels(messages):
        data_per_label = defaultdict(list)
        for label, message in messages:
            data_per_label[label].append((label, message))
        return data_per_label

    @staticmethod
    def split_into_folds(messages, folds):
        k, m = divmod(len(messages), folds)
        return [messages[i * k + min(i, m) : (i + 1) * k + min(i + 1, m)] for i in range(folds)]  # noqa: E203

    def stratified_split_into_folds(self, messages):
        data_per_label = self.split_into_labels(messages)
        labeled_folds = []
        for label, labeled_messages in data_per_label.items():
            random.shuffle(labeled_messages)
            labeled_folds.append(self.split_into_folds(labeled_messages, self.num_folds))
        folds = []
        for nested_fold in zip(*labeled_folds):
            folds.append(flatten(nested_fold))
        return folds

    @staticmethod
    def generate_train_test(folds):
        for i, n in enumerate(folds):
            all_but_n = flatten(folds[:i]) + flatten(folds[i + 1 :])  # noqa: E203
            yield n, all_but_n

    @staticmethod
    def generate_outcomes(model, test_messages):
        outcomes = (("true", "false"), ("positive", "negative"))
        possible_results = [f"{a}_{b}" for b in outcomes[1] for a in outcomes[0]]
        result_template = dict.fromkeys(possible_results, 0)

        labels = set(model.prior_probabilities)
        label_results = {label: dict(result_template) for label in labels}

        for label, message in test_messages:
            predicted = model.predict_label(message)
            if label == predicted:
                label_results[label]["true_positive"] += 1
            else:
                label_results[label]["false_negative"] += 1
                label_results[predicted]["false_positive"] += 1
        return label_results

    @staticmethod
    def calc_performance(results):
        performance = {}
        for label, result in results.items():
            precision, recall, f1 = precision_recall_f1(result)
            performance[label] = {"precision": precision, "recall": recall, "f1": f1}
        return performance

    def evaluate(self, messages):
        folds = self.stratified_split_into_folds(messages)
        results = None
        for test, train in self.generate_train_test(folds):
            model = self.model_class().fit(train)
            label_result = self.generate_outcomes(model, test)
            if results is None:
                results = label_result
            else:
                for label, counts in label_result.items():
                    for name, count in counts.items():
                        results[label][name] += count
        return self.calc_performance(results)


class SpamFilter(TimeStampedModel):
    name = models.CharField(unique=True, max_length=128)
    model = models.JSONField(verbose_name="Spamfilter Model", default=dict, encoder=ModelEncoder, decoder=ModelDecoder)
    performance = models.JSONField(verbose_name="Performance Indicators", default=dict)

    def retrain_from_scratch(self, train):
        """
        Retrain on all comments for now. Later on there might be
        different spam filters for different blogs/sites..
        """
        model = NaiveBayes().fit(train)
        self.model = model
        evaluator = Evaluation(model_class=NaiveBayes, num_folds=3)
        self.performance = evaluator.evaluate(train)
        self.save()

    @classmethod
    @property
    def default(cls):
        return cls.objects.first()
