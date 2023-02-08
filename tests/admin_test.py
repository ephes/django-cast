import pytest

from cast.admin import (
    AdminUserMixin,
    SpamfilterModelAdmin,
    VideoModelAdmin,
    cache_file_sizes,
    retrain,
)
from cast.models import SpamFilter, Video


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


@pytest.mark.django_db
def test_video_model_admin_calc_poster(mocker):
    class MockedForm:
        cleaned_data = {"poster": False}

    mocked_super = mocker.patch("cast.admin.ModelAdmin.save_model")
    vma = VideoModelAdmin(Video, None)

    # change=True, poster=False -> calc_poster=False
    vma.save_model(None, Video(), MockedForm(), True)
    processed_video = mocked_super.call_args[0][1]
    assert not processed_video.calc_poster

    # change=False, poster=False -> calc_poster=True
    vma.save_model(None, Video(), MockedForm(), False)
    processed_video = mocked_super.call_args[0][1]
    assert processed_video.calc_poster


def test_cache_file_sizes():
    class SpyAudio:
        cached = False

        def size_to_metadata(self):
            self.cached = True

        def save(self):
            pass

    spy = SpyAudio()
    cache_file_sizes(None, None, [spy])
    assert spy.cached


def test_admin_user_mixin():
    class SpyRequest:
        user = "foobar"

    aum = AdminUserMixin()
    initial_data = aum.get_changeform_initial_data(SpyRequest())
    assert initial_data == {"user": SpyRequest.user, "author": SpyRequest.user}
