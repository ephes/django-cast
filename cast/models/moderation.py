import re

from collections import defaultdict

from django.db import models

from model_utils.models import TimeStampedModel


token_pattern = re.compile(r"(?u)\b\w\w+\b")
standard_tokenizer = token_pattern.findall


def regex_tokenize(message):
    return standard_tokenizer(message.lower())


class NaiveBayes:
    def __init__(self, tokenize=regex_tokenize):
        self.tokenize = tokenize

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

    def get_number_of_words(self, word_label_counts):
        number_of_words = defaultdict(int)
        for word, counts in word_label_counts.items():
            for label, count in counts.items():
                number_of_words[label] += 1
        return number_of_words

    def fit(self, messages):
        self.prior_probabilities = self.get_prior_probabilities(self.get_label_counts(messages))
        self.word_label_counts = self.get_word_label_counts(messages)
        self.number_of_words = self.get_number_of_words(self.word_label_counts)
        return self

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


class SpamFilter(TimeStampedModel):
    name = models.CharField(unique=True, max_length=128)
    model = models.JSONField(verbose_name="Spamfilter Model", default=dict)

    @classmethod
    @property
    def default(cls):
        return cls.objects.first()
