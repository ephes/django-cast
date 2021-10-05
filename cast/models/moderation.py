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


class NaiveBayes:
    def __init__(self, tokenize=regex_tokenize):
        self.tokenize = tokenize

    @classmethod
    def build_model_from_counts(cls, prior_probabilities={}, word_label_counts={}):
        model = cls()
        model.prior_probabilities = prior_probabilities
        model.word_label_counts = word_label_counts
        model.number_of_words = cls.get_number_of_words(model.word_label_counts)
        return model

    def get_label_counts(self, messages):
        label_counts = defaultdict(int)
        for label, text in messages:
            label_counts[label] += 1
        return label_counts

    def get_prior_probabilities(self, label_counts):
        number_of_messages = sum(label_counts.values())
        return {label: count / number_of_messages for label, count in label_counts.items()}

    def get_word_label_counts(self, messages):
        counts = defaultdict(lambda: defaultdict(int))
        for label, text in messages:
            for word in self.tokenize(text):
                counts[word][label] += 1
        return counts

    @classmethod
    def get_number_of_words(cls, word_label_counts):
        number_of_words = defaultdict(int)
        for word, counts in word_label_counts.items():
            for label, count in counts.items():
                number_of_words[label] += 1
        return number_of_words

    def fit(self, messages):
        return self.build_model_from_counts(
            prior_probabilities=self.get_prior_probabilities(self.get_label_counts(messages)),
            word_label_counts=self.get_word_label_counts(messages),
        )

    def update_probabilities(self, probabilities, counts_per_label, number_of_words):
        updated_probabilites = {}
        for label, prior_probability in probabilities.items():
            word_count = counts_per_label.get(label, 0.5)
            word_probability = word_count / number_of_words[label]
            updated_probabilites[label] = prior_probability * word_probability
        return updated_probabilites

    def predict(self, message):
        probabilities = dict(self.prior_probabilities)
        for word in self.tokenize(message):
            counts_per_label = self.word_label_counts.get(word, {})
            probabilities = self.update_probabilities(probabilities, counts_per_label, self.number_of_words)
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

    def json(self):
        return json.dumps(self.dict())


class ModelEncoder(DjangoJSONEncoder):
    def default(self, obj):
        if isinstance(obj, NaiveBayes):
            return obj.json()
        return super().default(obj)


class ModelDecoder(json.JSONDecoder):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.object_hook = self.model_decode

    @staticmethod
    def model_decode(obj):
        print(obj)
        print("obj: ", obj)
        if obj.get("class") == "NaiveBayes":
            return NaiveBayes.from_dict(**obj)
        return obj


class SpamFilter(TimeStampedModel):
    name = models.CharField(unique=True, max_length=128)
    model = models.JSONField(verbose_name="Spamfilter Model", default=dict, encoder=ModelEncoder, decoder=ModelDecoder)

    @classmethod
    @property
    def default(cls):
        return cls.objects.first()
