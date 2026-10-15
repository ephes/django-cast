import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from wagtail.models import Locale

from cast.models import Contributor, TranscriptGlossaryTerm, VoxhelmSettings, get_podcast_transcript_language
from cast.models.contributors import validate_contributor_variants
from tests.factories import PodcastFactory


@pytest.fixture()
def other_podcast(user, site):
    return PodcastFactory(owner=user, title="other podcast", slug="other_podcast", parent=site.root_page)


def make_term(podcast, term, variants="", notes=""):
    return TranscriptGlossaryTerm.objects.create(podcast=podcast, term=term, variants=variants, notes=notes)


def clean_errors(instance):
    with pytest.raises(ValidationError) as excinfo:
        instance.full_clean()
    return excinfo.value.message_dict


class TestContributorVariants:
    def test_valid_lines(self):
        text = "John Gould => Jon Gould\nJohn => Jon\n\n  Jon  Goold \nJohn => Jon"
        assert validate_contributor_variants("Jon Gould", text) == []

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("John => Jon => Jonny", 'Line 1: use "=>" only once.'),
            ("--- => Jon", "Line 1: the variant needs letters or digits."),
            ("John =>", "Line 1: the replacement needs letters or digits."),
            ("jon  gould", 'Line 1: "jon gould" is the same as its replacement.'),
            ("John => Jon\nJohn => Jonathan", 'Line 2: "John" is already listed with another replacement.'),
        ],
    )
    def test_invalid_lines(self, text, expected):
        assert [str(error) for error in validate_contributor_variants("Jon Gould", text)] == [expected]

    @pytest.mark.django_db
    def test_clean_reports_errors_on_field(self):
        contributor = Contributor(display_name="Jon Gould", slug="jon-gould", transcript_variants="Jon Gould")
        assert "transcript_variants" in clean_errors(contributor)

    @pytest.mark.django_db
    def test_common_words_are_allowed(self):
        contributor = Contributor(
            display_name="Charlie Marsh", slug="charlie", transcript_variants="marsh\nrough => Ruff"
        )
        contributor.full_clean()


@pytest.mark.django_db
class TestTranscriptLanguage:
    def test_defaults_to_podcast_locale(self, podcast):
        assert get_podcast_transcript_language(podcast) == podcast.locale.language_code

    def test_voxhelm_site_setting_wins(self, podcast, settings):
        settings.CAST_VOXHELM_LANGUAGE = "en"
        setting = VoxhelmSettings.for_site(podcast.get_site())
        setting.language = " de "
        setting.save()
        assert get_podcast_transcript_language(podcast) == "de"

    def test_django_setting_then_environment(self, podcast, settings, monkeypatch):
        settings.CAST_VOXHELM_LANGUAGE = "fr"
        monkeypatch.setenv("CAST_VOXHELM_LANGUAGE", "de")
        assert get_podcast_transcript_language(podcast) == "fr"
        settings.CAST_VOXHELM_LANGUAGE = ""
        assert get_podcast_transcript_language(podcast) == "de"

    def test_auto_falls_back_to_locale(self, podcast, settings, monkeypatch):
        settings.CAST_VOXHELM_LANGUAGE = "auto"
        monkeypatch.setenv("CAST_VOXHELM_LANGUAGE", "de")
        assert get_podcast_transcript_language(podcast) == podcast.locale.language_code

    def test_podcast_without_site_uses_settings(self, podcast, settings, mocker):
        mocker.patch.object(type(podcast), "get_site", return_value=None)
        settings.CAST_VOXHELM_LANGUAGE = "de"
        assert get_podcast_transcript_language(podcast) == "de"


@pytest.mark.django_db
class TestTranscriptGlossaryTerm:
    def test_str_and_variants(self, podcast):
        term = make_term(podcast, "Gunicorn", "Gunacorn\n\n gunacorn \nGunna Corn")
        assert str(term) == "Gunicorn"
        assert term.variant_list == ["Gunacorn", "Gunna Corn"]
        assert term.variant_count() == 2

    def test_valid_term_cleans_whitespace(self, podcast):
        term = TranscriptGlossaryTerm(podcast=podcast, term="  Django   Chat ", variants="Jango Chat")
        term.full_clean()
        assert term.term == "Django Chat"

    def test_term_unique_per_podcast_ignoring_case(self, podcast, other_podcast):
        make_term(podcast, "Gunicorn")
        assert clean_errors(TranscriptGlossaryTerm(podcast=podcast, term="GUNICORN")) == {
            "term": ["This podcast already has this term."]
        }
        TranscriptGlossaryTerm(podcast=other_podcast, term="gunicorn").full_clean()

    def test_database_constraint(self, podcast):
        make_term(podcast, "Gunicorn")
        with pytest.raises(IntegrityError), transaction.atomic():
            make_term(podcast, "gunicorn")

    def test_editing_term_does_not_clash_with_itself(self, podcast):
        term = make_term(podcast, "Gunicorn", "Gunacorn")
        term.term = "gunicorn"
        term.full_clean()

    def test_term_must_not_be_variant_of_other_term(self, podcast):
        make_term(podcast, "Django", "Jango")
        assert clean_errors(TranscriptGlossaryTerm(podcast=podcast, term="jango")) == {
            "term": ['"jango" is a variant of the term "Django".']
        }

    def test_variant_rules(self, podcast):
        make_term(podcast, "Django", "Jango")
        make_term(podcast, "Heroku")
        term = TranscriptGlossaryTerm(podcast=podcast, term="Gunicorn", variants="gunicorn\nheroku\nJANGO\nrough")
        assert clean_errors(term) == {
            "variants": [
                '"gunicorn" is the term itself.',
                '"heroku" is the term "Heroku".',
                '"JANGO" is already a variant of "Django".',
                '"rough" is a common word in this podcast\'s transcript language (en-us) and would be replaced '
                "everywhere. Leave it to the transcript review.",
            ]
        }

    def test_multi_word_variant_of_common_words_is_allowed(self, podcast):
        TranscriptGlossaryTerm(podcast=podcast, term="Six Feet Up", variants="six feed up").full_clean()

    def test_common_words_depend_on_language(self, podcast, settings):
        settings.CAST_VOXHELM_LANGUAGE = "de"
        TranscriptGlossaryTerm(podcast=podcast, term="Ruff", variants="rough").full_clean()
        assert "variants" in clean_errors(TranscriptGlossaryTerm(podcast=podcast, term="Ruff", variants="Rauf\nund"))

    def test_language_without_list_allows_any_variant(self, podcast):
        podcast.locale = Locale.objects.create(language_code="fr")
        TranscriptGlossaryTerm(podcast=podcast, term="Ruff", variants="rough").full_clean()

    def test_missing_podcast_skips_cross_checks(self):
        errors = clean_errors(TranscriptGlossaryTerm(term="Ruff", variants="rough"))
        assert list(errors) == ["podcast"]
