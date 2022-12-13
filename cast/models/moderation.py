import json
import re
from collections import defaultdict

from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
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
    def __init__(self, tokenize=regex_tokenize, prior_probabilities={}, word_label_counts=None):
        self.tokenize = tokenize
        self.prior_probabilities = prior_probabilities
        if word_label_counts is None:
            self.word_label_counts = defaultdict(lambda: defaultdict(int))
        else:
            self.word_label_counts = word_label_counts
        self.number_of_words = self.get_number_of_words(self.word_label_counts)

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
        return self

    @staticmethod
    def update_probabilities(probabilities, counts_per_label, number_of_words):
        updated_probabilities = {}
        for label, prior_probability in probabilities.items():
            word_count = counts_per_label.get(label, 0.5)
            word_probability = word_count / number_of_words[label]
            updated_probabilities[label] = prior_probability * word_probability
        return updated_probabilities

    def predict(self, message):
        probabilities = dict(self.prior_probabilities)
        for word in self.tokenize(message):
            counts_per_label = self.word_label_counts.get(word, {})
            probabilities = normalize(self.update_probabilities(probabilities, counts_per_label, self.number_of_words))
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


class SpamFilter(TimeStampedModel):
    name = models.CharField(unique=True, max_length=128)
    model = models.JSONField(verbose_name="Spamfilter Model", default=dict, encoder=ModelEncoder, decoder=ModelDecoder)

    @classmethod
    def comment_to_message(cls, comment):
        return f"{comment.name} {comment.title} {comment.comment}"

    @classmethod
    def get_training_data_comments(cls):
        from django_comments import get_model as get_comments_model

        Comment = get_comments_model()
        train = []
        for comment in Comment.objects.all():
            label = "ham" if (comment.is_public and not comment.is_removed) else "spam"
            message = cls.comment_to_message(comment)
            train.append((label, message))
        return train

    def retrain_from_scratch(self):
        """
        Retrain on all comments for now. Later on there might be
        different spamfilters for different blogs/sites..
        """
        train = SpamFilter.get_training_data_comments()
        model = NaiveBayes().fit(train)
        self.model = model
        self.save()

    @classmethod
    @property
    def default(cls):
        return cls.objects.first()
