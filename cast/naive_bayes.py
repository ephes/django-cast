import re
import json

from pathlib import Path

from collections import defaultdict


token_pattern = re.compile(r"(?u)\b\w\w+\b")
standard_tokenizer = token_pattern.findall


def tokenize(message):
    return standard_tokenizer(message.lower())


def get_initial_probabilities(total):
    initial_probabilities = {}
    all_observations = sum(total.values())
    for label, observations_per_label in total.items():
        initial_probabilities[label] = observations_per_label / all_observations
    return initial_probabilities


def get_words_per_label(counts):
    words_per_label = defaultdict(int)
    for word, label_counts in counts.items():
        for label, count in label_counts.items():
            # words_per_label[label] = words_per_label.get(label, 0) + 1
            words_per_label[label] += 1
    return words_per_label


def build_model(counts, total):
    words_per_label = get_words_per_label(counts)
    return {
        "counts": counts,
        "labels": list(total.keys()),
        "words_per_label": words_per_label,
        "minimal_probability": 1.0 / sum(words_per_label.values()),
        "initial_probabilities": get_initial_probabilities(total),
    }


def train(messages):
    total = defaultdict(int)
    counts = defaultdict(lambda: defaultdict(int))
    for label, message in messages:
        total[label] += 1
        for word in tokenize(message):
            counts[word][label] += 1
    return build_model(counts, total)


def normalize(label_results):
    try:
        scale_factor = 1.0 / sum(label_results.values())
    except ZeroDivisionError:
        scale_factor = 1
    for label, probability in label_results.items():
        label_results[label] = probability * scale_factor
    return label_results


def predict(
    message,
    labels=[],
    counts={},
    words_per_label={},
    minimal_probability=None,
    initial_probabilities={},
):
    label_results = {}
    for word in tokenize(message):
        for label in labels:
            counts_per_label = counts.get(word, {})
            if label in counts_per_label:
                label_frequency = counts_per_label[label] / words_per_label[label]
            else:
                label_frequency = minimal_probability
            previous_result = label_results.get(label, initial_probabilities[label])
            label_results[label] = previous_result * label_frequency
    if label_results == {}:
        label_results = dict(initial_probabilities)
    return normalize(label_results)


def predict_label(message, **model):
    result = predict(message, **model)
    return sorted([(v, k) for k, v in result.items()], reverse=True)[0][1]


def get_pretrained_model():
    with (Path(__file__).parent / "naive_bayes_model.json").open("r") as f:
        model = json.loads(f.read())
    return model
