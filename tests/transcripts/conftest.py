import pytest
from django.urls import reverse


def get_endpoint_urls_without_args():
    urls = {}
    view_names = ["index", "add", "chooser", "chooser_upload"]
    for view_name in view_names:
        urls[view_name] = reverse(f"cast-transcript:{view_name}")
    return urls


def get_endpoint_urls_with_args(transcript):
    urls = {}
    view_names = ["edit", "delete", "chosen"]
    for view_name in view_names:
        urls[view_name] = reverse(f"cast-transcript:{view_name}", args=(transcript.id,))
    return urls


class TranscriptUrls:
    def __init__(self, transcript):
        self.transcript = transcript
        self.urls = get_endpoint_urls_without_args()
        self.urls.update(get_endpoint_urls_with_args(transcript))

    def __getattr__(self, item):
        return self.urls[item]


@pytest.fixture()
def transcript_urls(transcript):
    return TranscriptUrls(transcript)
