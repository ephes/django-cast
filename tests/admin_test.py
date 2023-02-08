from cast.admin import SpamfilterModelAdmin, retrain
from cast.models import SpamFilter


def test_spamfilter_model_admin():
    expected_performance = {
        "spam": {"precision": 0.5, "recall": 0.5},
        "ham": {"precision": 0.5, "recall": 0.5},
    }
    spamfilter = SpamFilter(performance=expected_performance)
    sma = SpamfilterModelAdmin(SpamFilter, None)
    assert sma.spam(spamfilter) == expected_performance["spam"]
    assert sma.ham(spamfilter) == expected_performance["ham"]


class SpySpamfilter:
    got_training_data = False
    retrained = False

    def get_training_data_comments(self):
        self.got_training_data = True
        return []

    def retrain_from_scratch(self, train):
        self.retrained = True


def test_retrain():
    spy = SpySpamfilter()
    retrain(None, None, [spy])
    assert spy.got_training_data
    assert spy.retrained
