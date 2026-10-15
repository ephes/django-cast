import pytest
from django.contrib.messages import get_messages
from django.urls import reverse
from wagtail.models import Locale
from wagtail.test.utils.form_data import inline_formset, nested_form_data

from cast.models import Contributor, TranscriptGlossaryTerm
from tests.factories import PodcastFactory

LIST_URL = "wagtailsnippets_cast_transcriptglossaryterm:list"
ADD_URL = "wagtailsnippets_cast_transcriptglossaryterm:add"
EDIT_URL = "wagtailsnippets_cast_transcriptglossaryterm:edit"


@pytest.fixture()
def other_podcast(user, site):
    return PodcastFactory(owner=user, title="other podcast", slug="other_podcast", parent=site.root_page)


def messages_of(response):
    return [str(message) for message in get_messages(response.wsgi_request)]


@pytest.mark.django_db
class TestGlossarySnippetAdmin:
    def test_list_filters_by_podcast_and_searches(self, admin_client, podcast, other_podcast):
        TranscriptGlossaryTerm.objects.create(podcast=podcast, term="Gunicorn", variants="Gunacorn")
        TranscriptGlossaryTerm.objects.create(podcast=other_podcast, term="Heroku")

        response = admin_client.get(reverse(LIST_URL))
        assert response.status_code == 200
        assert b"Gunicorn" in response.content and b"Heroku" in response.content

        response = admin_client.get(reverse(LIST_URL), {"podcast": podcast.pk})
        assert b"Gunicorn" in response.content and b"Heroku" not in response.content

        response = admin_client.get(reverse(LIST_URL), {"q": "gunacorn"})
        assert b"Gunicorn" in response.content and b"Heroku" not in response.content

    def test_create(self, admin_client, podcast):
        data = {"podcast": podcast.pk, "term": "Gunicorn", "variants": "Gunacorn\nGunna Corn", "notes": "server"}
        response = admin_client.post(reverse(ADD_URL), data)
        assert response.status_code == 302
        term = TranscriptGlossaryTerm.objects.get()
        assert (term.podcast_id, term.term, term.variant_list) == (podcast.pk, "Gunicorn", ["Gunacorn", "Gunna Corn"])
        assert not any("no common-word list" in message for message in messages_of(response))

    def test_create_refuses_common_word_and_duplicate(self, admin_client, podcast):
        TranscriptGlossaryTerm.objects.create(podcast=podcast, term="Ruff")
        response = admin_client.post(reverse(ADD_URL), {"podcast": podcast.pk, "term": "ruff", "variants": "rough"})
        assert response.status_code == 200
        assert "This podcast already has this term." in response.content.decode()
        assert "is a common word" in response.content.decode()
        assert TranscriptGlossaryTerm.objects.count() == 1

    def test_edit_warns_without_common_word_list(self, admin_client, podcast):
        podcast.locale = Locale.objects.create(language_code="fr")
        podcast.save()
        term = TranscriptGlossaryTerm.objects.create(podcast=podcast, term="Ruff")
        response = admin_client.get(reverse(EDIT_URL, args=(term.pk,)))
        assert response.status_code == 200

        response = admin_client.post(
            reverse(EDIT_URL, args=(term.pk,)), {"podcast": podcast.pk, "term": "Ruff", "variants": "rough"}
        )
        assert response.status_code == 302
        term.refresh_from_db()
        assert term.variants == "rough"
        assert any("no common-word list" in message and "(fr)" in message for message in messages_of(response))


@pytest.mark.django_db
class TestContributorTranscriptVariantsAdmin:
    @staticmethod
    def post_data(variants):
        return nested_form_data(
            {
                "display_name": "Jon Gould",
                "slug": "jon-gould",
                "visible": "on",
                "default_role": "guest",
                "short_bio": "",
                "transcript_variants": variants,
                "links": inline_formset([]),
                "voice_references": inline_formset([]),
            }
        )

    def test_edit_form_saves_and_validates_variants(self, admin_client):
        contributor = Contributor.objects.create(display_name="Jon Gould", slug="jon-gould")
        url = reverse("wagtailsnippets_cast_contributor:edit", args=(contributor.pk,))
        assert b"transcript_variants" in admin_client.get(url).content

        response = admin_client.post(url, self.post_data("Jon => Jon"))
        assert response.status_code == 200
        assert "is the same as its replacement" in response.content.decode()

        response = admin_client.post(url, self.post_data("John Gould\nJohn => Jon"))
        assert response.status_code == 302
        contributor.refresh_from_db()
        assert contributor.transcript_variants == "John Gould\nJohn => Jon"
