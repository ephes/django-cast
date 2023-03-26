from cast.cast_and_wagtail_urls import urlpatterns


def test_convenience_urls():
    assert len(urlpatterns) == 4
