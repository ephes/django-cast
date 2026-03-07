import pytest
from django.contrib.auth import get_user_model
from django.http import Http404

from cast.site_lookup import get_site_specific_page_or_404, site_specific_queryset


@pytest.mark.django_db
def test_site_specific_queryset_without_site_returns_global_queryset(rf, blog, mocker):
    request = rf.get("/")
    mocker.patch("cast.site_lookup.Site.find_for_request", return_value=None)

    queryset = site_specific_queryset(type(blog), request)

    assert blog in queryset


@pytest.mark.django_db
def test_site_specific_queryset_supports_non_page_models_without_live(rf, user, mocker):
    request = rf.get("/")
    mocker.patch("cast.site_lookup.Site.find_for_request", return_value=None)

    queryset = site_specific_queryset(get_user_model(), request)

    assert user in queryset


@pytest.mark.django_db
def test_site_specific_queryset_supports_non_page_models_with_site_context(rf, user, mocker):
    request = rf.get("/")
    fake_site = mocker.Mock(root_page_id=1, root_page=mocker.Mock())
    mocker.patch("cast.site_lookup.Site.find_for_request", return_value=fake_site)

    queryset = site_specific_queryset(get_user_model(), request)

    assert user in queryset


@pytest.mark.django_db
def test_get_site_specific_page_or_404_converts_multiple_objects_returned_to_404(rf, blog, mocker):
    request = rf.get("/")
    mocker.patch("cast.site_lookup.get_object_or_404", side_effect=type(blog).MultipleObjectsReturned)

    with pytest.raises(Http404):
        get_site_specific_page_or_404(type(blog), request, slug=blog.slug)
