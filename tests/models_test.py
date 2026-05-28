import os
from types import SimpleNamespace

import pytest
from django import forms
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.models import ProtectedError
from django.http import QueryDict
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from cast import appsettings
from cast.devdata import create_transcript
from cast.models import Audio, Blog, Contributor, ContributorLink, EpisodeContributor, File, Podcast
from cast.models.contributors import ContributorLinkSelect
from cast.models.pages import (
    PODLOVE_POSTER_RENDITION_SPEC,
    SOCIAL_COVER_RENDITION_SPEC,
    CustomEpisodeForm,
    Episode,
    HomePage,
    HtmlField,
    Post,
)
from cast.models.repository import BlogIndexContext
from cast.models.transcript import (
    Transcript,
    convert_dote_to_podcastindex_transcript,
    time_to_seconds,
)
from cast.models.video import Video
from tests.factories import EpisodeFactory


class TestVideoModel:
    pytestmark = pytest.mark.django_db

    def test_get_all_video_paths(self, video):
        all_paths = list(video.get_all_paths())
        assert len(all_paths) == 1

    def test_get_all_video_paths_with_poster(self, video_with_poster):
        all_paths = list(video_with_poster.get_all_paths())
        assert len(all_paths) == 2

    def test_get_all_video_paths_without_original(self, video_without_original):
        assert video_without_original.get_all_paths() == set()

    def test_get_all_video_paths_without_thumbnail(self, video):
        class Dummy:
            name = "foobar"
            closed = True

            def open(self):
                return None

            def close(self):
                return None

            def seek(self, position):
                return None

            def read(self, num_bytes):
                return b""

            def tell(self):
                return 0

        video.poster = Dummy()
        all_paths = list(video.get_all_paths())
        assert len(all_paths) == 2


class TestGalleryModel:
    @pytest.mark.django_db
    def test_get_image_ids(self, gallery):
        assert len(gallery.image_ids) == gallery.images.count()


class TestFileModel:
    @pytest.mark.django_db
    def test_get_all_file_paths(self, file_instance):
        all_paths = list(file_instance.get_all_paths())
        assert len(all_paths) == 1

    @pytest.mark.django_db
    def test_get_all_file_paths_without_original(self, user):
        file_instance = File(user=user)

        assert file_instance.get_all_paths() == set()


@pytest.fixture()
def use_django_blog_index_repo():
    previous = appsettings.CAST_REPOSITORY
    appsettings.CAST_REPOSITORY = "django"
    yield appsettings.CAST_REPOSITORY
    appsettings.CAST_REPOSITORY = previous


class TestBlogModel:
    pytestmark = pytest.mark.django_db

    def test_blog_str(self, blog):
        assert blog.title == str(blog)

    def test_blog_author_null(self, blog):
        blog.author = None
        assert blog.author_name == blog.owner.get_full_name()

    def test_blog_author_not_null(self, blog):
        blog.author = "Foobar"
        assert blog.author_name == blog.author

    # def test_paginate_queryset_request_is_none(self, blog):
    #     context = blog.paginate_queryset({}, blog.get_filterset(QueryDict()).qs, QueryDict())
    #     assert context["page_number"] == 1

    def test_paginate_has_previous(self, blog):
        class Page:
            def has_previous(self):
                return True

            def previous_page_number(self):
                return 1

            def has_next(self):
                return True

            def next_page_number(self):
                return 2

        context = blog.get_next_and_previous_pages(Page())
        assert context["has_next"] is True
        assert context["next_page_number"] == 2
        assert context["has_previous"] is True
        assert context["previous_page_number"] == 1

    def test_wagtail_api_pages_url(self, blog):
        assert blog.wagtail_api_pages_url == "/cast/api/wagtail/pages/"

    def test_pagination_page_size(self, blog):
        assert blog.pagination_page_size == appsettings.POST_LIST_PAGINATION

    def test_facet_counts_api_url(self, blog):
        assert blog.facet_counts_api_url == reverse("cast:api:facet-counts-detail", kwargs={"pk": blog.pk})

    def test_theme_list_api_url(self, blog):
        assert blog.theme_list_api_url == reverse("cast:api:theme-list")

    def test_theme_update_api_url(self, blog):
        assert blog.theme_update_api_url == reverse("cast:api:theme-update")

    def test_player_config_api_url(self, blog):
        assert blog.podlove_player_config_url == reverse("cast:api:player_config")

    def test_comment_post_url(self, blog):
        assert blog.comment_post_url == reverse("comments-post-comment-ajax")

    def test_has_selectable_themes(self, blog, simple_request):
        assert blog.get_context(simple_request)["has_selectable_themes"]

    def test_template_base_dir_is_none(self, blog, simple_request):
        template = blog.get_template(simple_request, template_base_dir="foobar")
        assert template == "cast/foobar/blog_list_of_posts.html"

    def test_get_django_repository(self, blog, simple_request, use_django_blog_index_repo):
        repository = blog.get_repository(simple_request, {})
        assert isinstance(repository, BlogIndexContext)

    def test_get_cover_image_url_for_blog(self, mocker):
        # just empty cover image
        blog = Blog(id=1)
        assert blog.get_cover_image_context() == {"cover_image_url": "", "cover_alt_text": ""}

        # cover image via blog.cover_image - using mock object because of the ImageField setter
        mock_image = mocker.MagicMock()
        mock_image.file.url = "https://example.org/cover.jpg"
        mocker.patch("cast.models.Blog.cover_image", mock_image)
        assert blog.get_cover_image_context() == {
            "cover_image_url": "https://example.org/cover.jpg",
            "cover_alt_text": "",
        }


class TestPodcastModel:
    def test_cover_image_from_super(self, mocker):
        podcast = Podcast(id=1)
        mocker_image = mocker.MagicMock()
        mocker_image.file.url = "https://example.org/cover.jpg"
        mocker.patch("cast.models.Blog.cover_image", mocker_image)
        assert podcast.get_cover_image_context() == {
            "cover_image_url": "https://example.org/cover.jpg",
            "cover_alt_text": "",
        }

    def test_podcast_get_context(self, rf, mocker):
        mocker.patch("cast.models.Blog.get_context", return_value={})
        request = rf.get("/")
        podcast = Podcast(id=1)
        context = podcast.get_context(request)
        assert context["podcast"] == podcast


class TestPostModel:
    pytestmark = pytest.mark.django_db

    def test_post_slug(self, post):
        assert post.get_slug() == "test-entry"

    def test_post_blog_returns_parent_blog(self, post):
        post = Post.objects.get(pk=post.pk)
        assert post.blog.pk == post.get_parent().blog.pk

    def test_post_blog_is_cached_after_first_access(self, post):
        post = Post.objects.get(pk=post.pk)

        with CaptureQueriesContext(connection) as first_access_queries:
            first_blog = post.blog
        with CaptureQueriesContext(connection) as second_access_queries:
            second_blog = post.blog

        assert len(first_access_queries.captured_queries) >= 1
        assert len(second_access_queries.captured_queries) == 0
        assert first_blog.pk == second_blog.pk

    def test_get_template_base_dir_uses_cached_blog_without_parent_lookup(self, mocker, post, simple_request):
        post = Post.objects.get(pk=post.pk)
        # Prime the blog cache
        _blog = post.blog

        get_parent_mock = mocker.patch.object(Post, "get_parent", autospec=True)
        template_base_dir = post.get_template_base_dir(simple_request)

        assert template_base_dir == post.blog.get_template_base_dir(simple_request)
        get_parent_mock.assert_not_called()

    def test_post_has_audio(self, post):
        assert post.has_audio is False

    def test_episode_has_audio(self, unpublished_episode_without_audio):
        episode = unpublished_episode_without_audio
        assert episode.has_audio is False

    def test_episode_has_audio_true(self, episode, audio):
        episode.podcast_audio = audio
        assert episode.has_audio is True

    def test_post_comments_enabled(self, post, comments_enabled):
        post.comments_enabled = True
        post.blog.comments_enabled = True
        assert post.comments_are_enabled

    def test_post_comments_disabled_settings(self, post, comments_not_enabled):
        post.comments_enabled = True
        post.blog.comments_enabled = True
        assert not post.comments_are_enabled

    def test_post_comments_disabled_blog(self, post, comments_enabled):
        post.comments_enabled = True
        post.blog.comments_enabled = False
        assert not post.comments_are_enabled

    def test_post_comments_disabled_post(self, post, comments_enabled):
        post.comments_enabled = False
        post.blog.comments_enabled = True
        assert not post.comments_are_enabled

    def test_post_media_lookup_value_error(self):
        assert Post().media_lookup == {}

    def test_post_has_audio_value_error(self):
        assert Post().has_audio is False

    def test_media_ids_from_body(self):
        class Block:
            block_type = "image"
            value = None

        class ContentBlock:
            value = (Block(),)

        block = ContentBlock()
        post = Post()
        assert post._media_ids_from_body([block]) == {}

    def test_media_ids_from_body_images_in_galleries(self):
        class GalleryBlock:
            block_type = "gallery"
            # test dict type, int and invalid (None) of "images" in the gallery
            value = {"gallery": [{"value": 2}, 1, None]}

        class ContentBlock:
            value = [GalleryBlock()]

        block = ContentBlock()
        post = Post()
        assert post._media_ids_from_body([block]) == {}

    def test_media_ids_from_body_is_int(self):
        class AudioBlock:
            block_type = "audio"
            value = 1

        class ContentBlock:
            value = [AudioBlock()]

        block = ContentBlock()
        post = Post()
        assert post._media_ids_from_body([block]) == {"audio": {1}}

    def test_media_ids_from_body_is_invalid(self):
        class AudioBlock:
            block_type = "audio"
            value = "asdf"

        class ContentBlock:
            value = [AudioBlock()]

        block = ContentBlock()
        post = Post()
        with pytest.raises(ValueError):
            post._media_ids_from_body([block])

    def test_get_site(self):
        post = Post()
        site = post.get_site()
        assert site is None

        class Repository:
            site = "foobar"

        post._repository = Repository()

        assert post.get_site() == "foobar"

    def test_get_full_url_prefers_page_url_attribute(self):
        post = Post()
        post.page_url = "/from-context/"
        assert post.get_full_url() == "/from-context/"

    def test_get_description_escape(self, mocker, simple_request, post):
        class Rendered:
            rendered_content = "<h1>foo</h1>"

        mocker.patch("cast.models.Post.serve", return_value=Rendered())
        description = post.get_description(request=simple_request, escape_html=True)
        assert "&lt" in description

    def test_get_description_newlines(self, mocker, simple_request, post):
        class Rendered:
            rendered_content = "<h1>foo</h1>\n"

        mocker.patch("cast.models.Post.serve", return_value=Rendered())
        description = post.get_description(request=simple_request, remove_newlines=False)
        assert "\n" in description

    def test_overview_html(self, mocker):
        expected_html = "<h1>foo</h1>"
        mock = mocker.patch("cast.models.Post.get_description", return_value=expected_html)
        html_field = HtmlField(source="*", render_detail=False)
        html_field._context = {"request": "foobar"}
        overview = html_field.to_representation(Post())
        assert overview == expected_html
        assert mock.call_args[1]["render_detail"] is False
        assert mock.call_args[1]["render_for_feed"] is True
        assert mock.call_args[1]["escape_html"] is False
        assert mock.call_args[1]["remove_newlines"] is False

    def test_detail_html(self, mocker):
        expected_html = "<h1>foo</h1><p>bar</p>"
        mock = mocker.patch("cast.models.Post.get_description", return_value=expected_html)
        html_field = HtmlField(source="*", render_detail=True)
        html_field._context = {"request": "foobar"}
        detail = html_field.to_representation(Post())
        assert detail == expected_html
        assert mock.call_args[1]["render_detail"] is True
        assert mock.call_args[1]["render_for_feed"] is True
        assert mock.call_args[1]["escape_html"] is False
        assert mock.call_args[1]["remove_newlines"] is False

    def test_detail_html_respects_render_for_feed_param(self, mocker, rf):
        expected_html = "<h1>foo</h1><p>bar</p>"
        mock = mocker.patch("cast.models.Post.get_description", return_value=expected_html)
        html_field = HtmlField(source="*", render_detail=True)
        html_field._context = {"request": rf.get("/?render_for_feed=false")}
        detail = html_field.to_representation(Post())
        assert detail == expected_html
        assert mock.call_args[1]["render_for_feed"] is False

    def test_detail_html_without_request_uses_default_render_for_feed(self, mocker):
        expected_html = "<h1>foo</h1><p>bar</p>"
        mock = mocker.patch("cast.models.Post.get_description", return_value=expected_html)
        html_field = HtmlField(source="*", render_detail=True)
        html_field._context = {"request": None}
        detail = html_field.to_representation(Post())
        assert detail == expected_html
        assert mock.call_args[1]["render_for_feed"] is True
        assert mock.call_args[1]["request"] is None

    @pytest.mark.parametrize(
        "local_template_name, expected_template",
        [
            (None, "cast/bootstrap4/post.html"),
            ("foobar.html", "cast/bootstrap4/foobar.html"),
        ],
    )
    def test_get_template_for_post(self, local_template_name, expected_template, mocker, simple_request):
        class TemplateBaseDirectory:
            name = "bootstrap4"

        mocker.patch("cast.models.pages.TemplateBaseDirectory.for_request", return_value=TemplateBaseDirectory())
        post = Post()
        post._local_template_name = local_template_name

        assert post.get_template(simple_request) == expected_template

    @pytest.mark.parametrize(
        "is_public, is_removed, contained_in_list",
        [
            (True, False, True),  # public, not removed, in list
            (True, True, False),  # public, removed, not in list
            (False, True, False),  # not public, removed, not in list
            (False, False, False),  # not public, not removed, not in list
        ],
    )
    def test_get_comments(self, is_public, is_removed, contained_in_list, post, comment):
        comment.is_public = is_public
        comment.is_removed = is_removed
        comment.save()
        if contained_in_list:
            [json_comment] = post.comments
            assert json_comment["comment"] == comment.comment
        else:
            assert list(post.comments) == []

    def test_get_comments_is_public_and_is_removed_not_in_fields(self, mocker, post, comment):
        from django_comments import get_model as get_comment_model

        comment_model = get_comment_model()
        exclude = {"is_public", "is_removed"}
        fields_without_excluded = [field for field in comment_model._meta.fields if field.name not in exclude]
        mocker.patch("cast.models.pages.comment_model._meta.fields", fields_without_excluded)
        [json_comment] = post.comments
        assert json_comment["comment"] == comment.comment

    def test_page_type(self):
        post = Post()
        assert post.page_type == "cast.Post"

    def test_podlove_players(self, post_with_audio):
        post = post_with_audio
        [audio] = post.audios.all()
        assert post.podlove_players == [
            (f"#audio_{audio.pk}", audio.get_podlove_url(post.pk)),
        ]

    def test_episode_podlove_players_includes_podcast_audio(self, episode):
        audio = episode.podcast_audio
        assert episode.podlove_players == [
            (f"#audio_{audio.pk}", audio.get_podlove_url(episode.pk)),
        ]

    def test_episode_podlove_players_without_podcast_audio(self, podcast, body):
        episode = EpisodeFactory(
            owner=podcast.owner,
            parent=podcast,
            title="test podcast episode",
            slug="test-podcast-entry-no-audio",
            podcast_audio=None,
            body=body,
        )
        assert episode.podlove_players == []

    def test_episode_podlove_players_with_unsaved_audio(self, podcast):
        audio = Audio(user=podcast.owner, title="unsaved audio")
        episode = Episode(title="draft episode", slug="draft-episode", owner=podcast.owner, podcast_audio=audio)
        assert episode.podlove_players == []

    def test_episode_podlove_players_deduplicates_body_audio(self, podcast, audio, body_with_audio):
        episode = EpisodeFactory(
            owner=podcast.owner,
            parent=podcast,
            title="test podcast episode",
            slug="test-podcast-entry-with-audio",
            podcast_audio=audio,
            body=body_with_audio,
        )
        assert episode.podlove_players == [
            (f"#audio_{audio.pk}", audio.get_podlove_url(episode.pk)),
        ]

    def test_episode_podlove_players_includes_body_and_podcast_audio(self, podcast, audio, body_with_audio):
        other_audio = Audio(user=podcast.owner, title="other audio")
        other_audio.save()
        episode = EpisodeFactory(
            owner=podcast.owner,
            parent=podcast,
            title="test podcast episode",
            slug="test-podcast-entry-with-two-audios",
            podcast_audio=other_audio,
            body=body_with_audio,
        )
        assert len(episode.podlove_players) == 2
        player_ids = {element_id for element_id, _url in episode.podlove_players}
        assert player_ids == {f"#audio_{audio.pk}", f"#audio_{other_audio.pk}"}

    def test_episode_visible_contributor_assignments_filters_and_orders(self, episode):
        hidden = Contributor.objects.create(display_name="Hidden Person", slug="hidden-person", visible=False)
        visible_guest = Contributor.objects.create(display_name="Visible Guest", slug="visible-guest")
        visible_host = Contributor.objects.create(display_name="Visible Host", slug="visible-host")
        EpisodeContributor.objects.create(
            episode=episode,
            contributor=visible_guest,
            role=EpisodeContributor.ROLE_GUEST,
            sort_order=2,
        )
        EpisodeContributor.objects.create(
            episode=episode,
            contributor=hidden,
            role=EpisodeContributor.ROLE_GUEST,
            sort_order=1,
        )
        EpisodeContributor.objects.create(
            episode=episode,
            contributor=visible_host,
            role=EpisodeContributor.ROLE_HOST,
            sort_order=0,
        )

        assert [assignment.display_name for assignment in episode.visible_contributor_assignments] == [
            "Visible Host",
            "Visible Guest",
        ]

    def test_episode_visible_contributor_assignments_uses_prefetched_assignments(self, episode):
        contributor = Contributor.objects.create(display_name="Prefetched Guest", slug="prefetched-guest")
        EpisodeContributor.objects.create(
            episode=episode,
            contributor=contributor,
            role=EpisodeContributor.ROLE_GUEST,
            sort_order=0,
        )
        prefetched_episode = Episode.objects.prefetch_related("contributor_assignments__contributor").get(
            pk=episode.pk
        )

        assert [assignment.display_name for assignment in prefetched_episode.visible_contributor_assignments] == [
            "Prefetched Guest",
        ]

    def test_unsaved_episode_visible_contributor_assignments(self, mocker):
        class BrokenAssignments:
            @staticmethod
            def select_related(*_args):
                raise ValueError

        episode = Episode()
        mocker.patch.object(Episode, "contributor_assignments", BrokenAssignments())

        assert episode.visible_contributor_assignments == []

    def test_unsaved_episode_visible_contributor_assignments_include_modelcluster_children(self):
        host = Contributor.objects.create(display_name="Draft Host", slug="draft-host")
        guest = Contributor.objects.create(display_name="Draft Guest", slug="draft-guest")
        hidden = Contributor.objects.create(display_name="Draft Hidden", slug="draft-hidden", visible=False)
        episode = Episode(title="Draft episode", slug="draft-episode")
        episode.contributor_assignments.add(
            EpisodeContributor(
                contributor=guest,
                role=EpisodeContributor.ROLE_GUEST,
                sort_order=1,
            )
        )
        episode.contributor_assignments.add(
            EpisodeContributor(
                contributor=hidden,
                role=EpisodeContributor.ROLE_GUEST,
                sort_order=2,
            )
        )
        episode.contributor_assignments.add(
            EpisodeContributor(
                role=EpisodeContributor.ROLE_GUEST,
                sort_order=3,
            )
        )
        episode.contributor_assignments.add(
            EpisodeContributor(
                contributor=host,
                role=EpisodeContributor.ROLE_HOST,
                sort_order=0,
            )
        )

        assert [assignment.display_name for assignment in episode.visible_contributor_assignments] == [
            "Draft Host",
            "Draft Guest",
        ]

    def test_contributor_helpers(self, rf, image):
        contributor = Contributor.objects.create(display_name="Visible Guest", slug="visible-guest", avatar=image)
        link = ContributorLink.objects.create(
            contributor=contributor,
            service=ContributorLink.SERVICE_WEBSITE,
            url="https://example.com/guest",
        )

        assert str(contributor) == "Visible Guest"
        assert str(link) == "Visible Guest: Website"
        assert Contributor(display_name="No Avatar", slug="no-avatar").get_avatar_url() == ""
        assert contributor.get_avatar_url() == image.file.url
        assert contributor.get_avatar_url(rf.get("/")) == f"http://testserver{image.file.url}"
        rendition_url = contributor.get_avatar_rendition_url()
        assert rendition_url
        assert "fill-80x80" in rendition_url
        assert contributor.get_avatar_rendition_url() == rendition_url  # cached

    def test_episode_contributor_link_must_belong_to_contributor(self, episode):
        contributor = Contributor.objects.create(display_name="Guest", slug="guest")
        other_contributor = Contributor.objects.create(display_name="Other Guest", slug="other-guest")
        other_link = ContributorLink.objects.create(
            contributor=other_contributor,
            service=ContributorLink.SERVICE_WEBSITE,
            url="https://example.com/other",
        )
        assignment = EpisodeContributor(
            episode=episode,
            contributor=contributor,
            role=EpisodeContributor.ROLE_GUEST,
            link=other_link,
        )

        with pytest.raises(ValidationError):
            assignment.clean()

    def test_episode_contributor_link_mismatch_rejected_by_direct_save(self, episode):
        contributor = Contributor.objects.create(display_name="Guest", slug="guest")
        other_contributor = Contributor.objects.create(display_name="Other Guest", slug="other-guest")
        other_link = ContributorLink.objects.create(
            contributor=other_contributor,
            service=ContributorLink.SERVICE_WEBSITE,
            url="https://example.com/other",
        )
        assignment = EpisodeContributor(
            episode=episode,
            contributor=contributor,
            role=EpisodeContributor.ROLE_GUEST,
            link=other_link,
        )

        with pytest.raises(ValidationError):
            assignment.save()

    def test_episode_contributor_link_mismatch_rejected_by_cluster_formset(self, episode):
        """Wagtail's InlinePanel save path runs through a modelcluster childformset."""
        from modelcluster.forms import childformset_factory

        contributor = Contributor.objects.create(display_name="Guest", slug="guest")
        other_contributor = Contributor.objects.create(display_name="Other Guest", slug="other-guest")
        other_link = ContributorLink.objects.create(
            contributor=other_contributor,
            service=ContributorLink.SERVICE_WEBSITE,
            url="https://example.com/other",
        )
        formset_class = childformset_factory(Episode, EpisodeContributor, fields=["contributor", "role", "link"])
        prefix = formset_class.get_default_prefix()
        formset = formset_class(
            data={
                f"{prefix}-TOTAL_FORMS": "1",
                f"{prefix}-INITIAL_FORMS": "0",
                f"{prefix}-MIN_NUM_FORMS": "0",
                f"{prefix}-MAX_NUM_FORMS": "1000",
                f"{prefix}-0-contributor": str(contributor.pk),
                f"{prefix}-0-role": EpisodeContributor.ROLE_GUEST,
                f"{prefix}-0-link": str(other_link.pk),
                f"{prefix}-0-ORDER": "0",
                f"{prefix}-0-id": "",
            },
            instance=episode,
        )
        assert not formset.is_valid()
        assert "link" in formset.errors[0]

    def test_episode_contributor_link_field_uses_filtering_widget(self, episode):
        form_class = Episode.get_edit_handler().get_form_class()
        form = form_class(instance=episode)
        link_widget = form.formsets["contributor_assignments"].empty_form.fields["link"].widget

        assert isinstance(link_widget, ContributorLinkSelect)
        assert link_widget.attrs["data-cast-contributor-link-select"] == "true"
        assert str(link_widget.attrs["data-cast-contributor-link-options-url"]) == reverse("cast-contributors:links")
        assert "cast/js/wagtail/contributor-link-select.js" in str(link_widget.media)
        assert "cast/js/wagtail/contributor-link-select.js" in str(form.media)

    def test_contributor_link_select_marks_options_with_contributor_id(self, episode):
        contributor = Contributor.objects.create(display_name="Guest", slug="guest")
        link = ContributorLink.objects.create(
            contributor=contributor,
            service=ContributorLink.SERVICE_WEBSITE,
            url="https://example.com/guest",
        )
        other_contributor = Contributor.objects.create(display_name="Other Guest", slug="other-guest")
        other_link = ContributorLink.objects.create(
            contributor=other_contributor,
            service=ContributorLink.SERVICE_MASTODON,
            url="https://example.com/other",
        )
        form_class = Episode.get_edit_handler().get_form_class()
        form = form_class(instance=episode)
        link_field = form.formsets["contributor_assignments"].empty_form.fields["link"]

        html = link_field.widget.render("link", str(link.pk), attrs={"id": "link"})

        assert '<option value="">---------</option>' in html
        assert f'<option value="{link.pk}" selected data-cast-contributor-id="{contributor.pk}">' in html
        assert f'<option value="{other_link.pk}" data-cast-contributor-id="{other_contributor.pk}">' in html

    def test_episode_contributor_is_unique_per_episode_contributor_and_role(self, episode):
        contributor = Contributor.objects.create(display_name="Guest", slug="guest")
        EpisodeContributor.objects.create(
            episode=episode,
            contributor=contributor,
            role=EpisodeContributor.ROLE_GUEST,
            sort_order=0,
        )

        with pytest.raises(IntegrityError), transaction.atomic():
            EpisodeContributor.objects.create(
                episode=episode,
                contributor=contributor,
                role=EpisodeContributor.ROLE_GUEST,
                sort_order=1,
            )

    def test_episode_contributor_allows_same_person_in_different_roles(self, episode):
        contributor = Contributor.objects.create(display_name="Polymath", slug="polymath")
        EpisodeContributor.objects.create(
            episode=episode,
            contributor=contributor,
            role=EpisodeContributor.ROLE_HOST,
            sort_order=0,
        )
        EpisodeContributor.objects.create(
            episode=episode,
            contributor=contributor,
            role=EpisodeContributor.ROLE_GUEST,
            sort_order=1,
        )

        assert EpisodeContributor.objects.filter(episode=episode, contributor=contributor).count() == 2

    def test_episode_contributor_helpers_with_valid_link(self, episode):
        contributor = Contributor.objects.create(display_name="Guest", slug="guest")
        link = ContributorLink.objects.create(
            contributor=contributor,
            service=ContributorLink.SERVICE_WEBSITE,
            url="https://example.com/guest",
        )
        assignment = EpisodeContributor(
            episode=episode,
            contributor=contributor,
            role=EpisodeContributor.ROLE_GUEST,
            link=link,
        )

        assignment.clean()

        assert str(assignment) == "Guest (Guest)"
        assert assignment.href == "https://example.com/guest"
        assert assignment.get_avatar_url() == ""

    def test_contributor_link_in_use_cannot_be_reparented(self, episode):
        contributor = Contributor.objects.create(display_name="Guest", slug="guest")
        other_contributor = Contributor.objects.create(display_name="Other Guest", slug="other-guest")
        link = ContributorLink.objects.create(
            contributor=contributor,
            service=ContributorLink.SERVICE_WEBSITE,
            url="https://example.com/guest",
        )
        EpisodeContributor.objects.create(
            episode=episode,
            contributor=contributor,
            role=EpisodeContributor.ROLE_GUEST,
            link=link,
        )

        link.url = "https://example.com/guest-updated"
        link.save()

        link.contributor = other_contributor

        with pytest.raises(ValidationError):
            link.save()
        link.refresh_from_db()
        assert link.contributor == contributor

    def test_contributor_link_reparenting_is_rejected_by_full_clean(self, episode):
        contributor = Contributor.objects.create(display_name="Guest", slug="guest")
        other_contributor = Contributor.objects.create(display_name="Other Guest", slug="other-guest")
        link = ContributorLink.objects.create(
            contributor=contributor,
            service=ContributorLink.SERVICE_WEBSITE,
            url="https://example.com/guest",
        )
        EpisodeContributor.objects.create(
            episode=episode,
            contributor=contributor,
            role=EpisodeContributor.ROLE_GUEST,
            link=link,
        )

        link.contributor = other_contributor

        with pytest.raises(ValidationError):
            link.full_clean()

    def test_contributor_link_in_use_cannot_be_deleted(self, episode):
        contributor = Contributor.objects.create(display_name="Guest", slug="guest")
        link = ContributorLink.objects.create(
            contributor=contributor,
            service=ContributorLink.SERVICE_WEBSITE,
            url="https://example.com/guest",
        )
        EpisodeContributor.objects.create(
            episode=episode,
            contributor=contributor,
            role=EpisodeContributor.ROLE_GUEST,
            link=link,
        )

        with pytest.raises(ProtectedError):
            link.delete()

    def test_episode_context_exposes_visible_contributors(self, rf, episode):
        contributor = Contributor.objects.create(display_name="Visible Guest", slug="visible-guest")
        EpisodeContributor.objects.create(
            episode=episode,
            contributor=contributor,
            role=EpisodeContributor.ROLE_GUEST,
            sort_order=0,
        )

        context = episode.get_context(rf.get("/"))

        assert [assignment.display_name for assignment in context["episode_contributors"]] == ["Visible Guest"]

    def test_get_context_owner_none(self, rf, post):
        """owner can be None when editing a draft."""
        request = rf.get("/")
        context = post.get_context(request)
        assert context["owner_username"] == post.owner.username

        post.owner = None
        context = post.get_context(request)
        assert context["owner_username"] == "unknown"

    @pytest.mark.parametrize(
        ("render_for_feed", "expected_page_url"),
        [
            (False, "/post-detail/"),
            (True, "http://testserver/post-detail/"),
        ],
    )
    def test_get_context_does_not_mutate_instance_and_keeps_context_compatibility(
        self, rf, post, render_for_feed, expected_page_url
    ):
        request = rf.get("/post-detail/")
        original_owner = post.owner
        assert not hasattr(post, "page_url")
        repository = SimpleNamespace(
            post_id=post.pk,
            template_base_dir="plain",
            blog=post.blog,
            comments_are_enabled=True,
            root_nav_links=[],
            has_audio=False,
            page_url="/post-detail/",
            absolute_page_url="http://testserver/post-detail/",
            owner_username="owner-from-repository",
            blog_url=f"/{post.blog.slug}/",
            cover_image_url="",
            cover_alt_text="",
            audio_by_id={},
        )

        context = post.get_context(request, repository=repository, render_for_feed=render_for_feed)

        assert post.owner == original_owner
        assert post.owner_id == original_owner.pk
        assert not hasattr(post, "page_url")
        assert context["owner_username"] == "owner-from-repository"
        assert context["page_url"] == "/post-detail/"
        assert context["page"] is not post
        assert context["self"] is context["page"]
        assert context["page"].owner.username == "owner-from-repository"
        assert context["page"].page_url == expected_page_url

    def test_serve_defaults_to_detail_rendering(self, rf, post, mocker):
        request = rf.get("/")
        captured_kwargs = {}

        def fake_page_serve(_page, _request, *args, **kwargs):
            captured_kwargs.update(kwargs)
            return "response"

        mocker.patch("cast.models.pages.Page.serve", fake_page_serve)

        response = post.serve(request)

        assert response == "response"
        assert captured_kwargs["render_detail"] is True

    def test_serve_keeps_explicit_render_detail_value(self, rf, post, mocker):
        request = rf.get("/")
        captured_kwargs = {}

        def fake_page_serve(_page, _request, *args, **kwargs):
            captured_kwargs.update(kwargs)
            return "response"

        mocker.patch("cast.models.pages.Page.serve", fake_page_serve)

        response = post.serve(request, render_detail=False)

        assert response == "response"
        assert captured_kwargs["render_detail"] is False

    def test_preview_context_defaults_to_detail_rendering(self, rf, post):
        context = post.get_preview_context(rf.get("/"), "")

        assert context["render_detail"] is True

    def test_has_selectable_themes(self, rf, post):
        """Theme selector should be enabled on post detail pages."""
        request = rf.get("/")
        context = post.get_context(request)
        assert context["has_selectable_themes"] is True

    def test_get_updated_timestamp(self):
        post = Post()
        post.last_published_at = timezone.now()
        assert post.get_updated_timestamp() == int(post.last_published_at.timestamp())

    def test_get_cover_image_context(self):
        post = Post(id=1)  #
        # no cover_image
        context = post.get_cover_image_context({}, None)
        assert context == {"cover_alt_text": "", "cover_image_url": ""}

        # test return early, because episode.cover_image was set
        context = post.get_cover_image_context({"cover_image_url": "https://example.org/cover.jpg"}, None)
        cover_image_url = context["cover_image_url"]
        assert cover_image_url == "https://example.org/cover.jpg"

    def test_get_social_cover_image_context_with_post_cover(self, rf, post, image, mocker):
        request = rf.get("/")
        post.cover_image = image
        mock_rendition = mocker.MagicMock(url="/media/social.jpg", width=1200, height=630)
        mocker.patch.object(image, "get_rendition", return_value=mock_rendition)

        context = post.get_social_cover_image_context(request=request, blog=None)

        assert context["social_cover_image_url"] == request.build_absolute_uri(mock_rendition.url)
        assert context["social_cover_image_width"] == mock_rendition.width
        assert context["social_cover_image_height"] == mock_rendition.height
        image.get_rendition.assert_called_once_with(SOCIAL_COVER_RENDITION_SPEC)

    def test_get_social_cover_image_context_with_blog_cover(self, rf, blog, image, mocker):
        request = rf.get("/")
        post = Post(id=1)
        blog.cover_image = image
        mock_rendition = mocker.MagicMock(url="/media/social.jpg", width=1200, height=630)
        mocker.patch.object(image, "get_rendition", return_value=mock_rendition)

        context = post.get_social_cover_image_context(request=request, blog=blog)

        assert context["social_cover_image_url"] == request.build_absolute_uri(mock_rendition.url)
        assert context["social_cover_image_width"] == mock_rendition.width
        assert context["social_cover_image_height"] == mock_rendition.height
        image.get_rendition.assert_called_once_with(SOCIAL_COVER_RENDITION_SPEC)

    def test_get_social_cover_image_context_without_cover(self, rf):
        request = rf.get("/")
        post = Post(id=1)

        context = post.get_social_cover_image_context(request=request, blog=None)

        assert context == {
            "social_cover_image_url": "",
            "social_cover_image_width": "",
            "social_cover_image_height": "",
        }

    def test_get_social_cover_image_context_without_absolute_url(self, image, mocker):
        class Request:
            pass

        post = Post(id=1)
        post.cover_image = image
        mock_rendition = mocker.MagicMock(url="/media/social.jpg", width=1200, height=630)
        mocker.patch.object(image, "get_rendition", return_value=mock_rendition)

        context = post.get_social_cover_image_context(request=Request(), blog=None)

        assert context["social_cover_image_url"] == mock_rendition.url
        assert context["social_cover_image_width"] == mock_rendition.width
        assert context["social_cover_image_height"] == mock_rendition.height

    def test_get_cover_image_poster_url_with_post_cover(self, rf, post, image, mocker):
        request = rf.get("/")
        post.cover_image = image
        mock_rendition = mocker.MagicMock(url="/media/podlove.jpg")
        mocker.patch.object(image, "get_rendition", return_value=mock_rendition)

        poster_url = post.get_cover_image_poster_url(request=request, blog=None)

        assert poster_url == request.build_absolute_uri(mock_rendition.url)
        image.get_rendition.assert_called_once_with(PODLOVE_POSTER_RENDITION_SPEC)

    def test_get_cover_image_poster_url_with_blog_cover(self, rf, blog, image, mocker):
        request = rf.get("/")
        post = Post(id=1)
        blog.cover_image = image
        mock_rendition = mocker.MagicMock(url="/media/podlove.jpg")
        mocker.patch.object(image, "get_rendition", return_value=mock_rendition)

        poster_url = post.get_cover_image_poster_url(request=request, blog=blog)

        assert poster_url == request.build_absolute_uri(mock_rendition.url)
        image.get_rendition.assert_called_once_with(PODLOVE_POSTER_RENDITION_SPEC)

    def test_get_cover_image_poster_url_without_cover(self, rf):
        request = rf.get("/")
        post = Post(id=1)

        poster_url = post.get_cover_image_poster_url(request=request, blog=None)

        assert poster_url == ""

    def test_get_cover_image_poster_url_without_absolute_url(self, image, mocker):
        class Request:
            pass

        post = Post(id=1)
        post.cover_image = image
        mock_rendition = mocker.MagicMock(url="/media/podlove.jpg")
        mocker.patch.object(image, "get_rendition", return_value=mock_rendition)

        poster_url = post.get_cover_image_poster_url(request=Request(), blog=None)

        assert poster_url == mock_rendition.url

    def test_podlove_poster_rendition_spec_is_valid_webp(self):
        from wagtail.images.models import Filter

        f = Filter(spec=PODLOVE_POSTER_RENDITION_SPEC)
        assert len(f.operations) == 2
        assert "format-webp" in PODLOVE_POSTER_RENDITION_SPEC

    def test_get_cached_media_lookup(self):
        post = Post(id=1)
        post._media_lookup = "foobar"
        assert post.media_lookup == post._media_lookup

    def test_ignore_value_error_in_serve_preview_during_sync_media_ids(self, rf, mocker, post):
        mocker.patch("cast.models.Post.sync_media_ids", side_effect=ValueError())
        request = rf.get("/")
        post.serve_preview(request, "")
        assert post.media_lookup == {"audio": {}, "image": {}, "video": {}, "gallery": {}}

    def test_images_all_raises_value_error_on_preview(self, mocker):
        post = Post(id=1)
        images_mock = mocker.patch("cast.models.Post.images")
        images_mock.all.side_effect = ValueError()
        with pytest.raises(ValueError):
            list(post.images.all())
        all_images = list(post.get_all_images())
        assert all_images == []


class TestEpisodeModel:
    pytestmark = pytest.mark.django_db

    def test_get_context_without_absolute_url(self, mocker):
        class Request:
            pass

        mocker.patch("cast.models.Post.get_context", return_value={})
        episode = Episode()
        context = episode.get_context(Request())
        assert "player_url" not in context

    def test_get_enclosure_size_podcast_is_none(self):
        episode = Episode()
        assert episode.get_enclosure_size("mp3") == 0

    @pytest.mark.parametrize(
        "local_template_name, expected_template",
        [
            (None, "cast/bootstrap4/episode.html"),
            ("foobar.html", "cast/bootstrap4/foobar.html"),
        ],
    )
    def test_get_template_for_episode(self, local_template_name, expected_template, mocker, simple_request):
        class TemplateBaseDirectory:
            name = "bootstrap4"

        mocker.patch("cast.models.pages.TemplateBaseDirectory.for_request", return_value=TemplateBaseDirectory())
        episode = Episode()
        episode._local_template_name = local_template_name

        assert episode.get_template(simple_request) == expected_template

    def test_page_type(self):
        episode = Episode()
        assert episode.page_type == "cast.Episode"

    def test_get_transcript_or_none_repository_none(self):
        episode = Episode(id=1)
        assert episode.get_transcript_or_none(None) is None

    def test_transcript_properties(self, episode):
        assert episode.transcript is None
        assert episode.has_transcript is False
        create_transcript(audio=episode.podcast_audio, podlove={"transcripts": [{"start": "00:00:00.000"}]})
        episode.refresh_from_db()
        assert episode.transcript is not None
        assert episode.has_transcript is True

    def test_get_transcript_url(self, episode):
        expected = reverse(
            "cast:episode-transcript",
            kwargs={"blog_slug": episode.blog.slug, "episode_slug": episode.slug},
        )
        assert episode.get_transcript_url() == expected

    def test_get_context_sets_transcript_url_without_absolute_uri(self, episode, mocker):
        class Request:
            pass

        create_transcript(audio=episode.podcast_audio, podlove={"transcripts": [{"start": "00:00:00.000"}]})
        episode.podcast_audio.refresh_from_db()
        repository = mocker.MagicMock()
        repository.blog.slug = episode.blog.slug
        mocker.patch(
            "cast.models.Post.get_context",
            return_value={"repository": repository, "render_for_feed": False},
        )
        context = episode.get_context(Request())
        expected = reverse(
            "cast:episode-transcript",
            kwargs={"blog_slug": episode.blog.slug, "episode_slug": episode.slug},
        )
        assert context["episode_transcript_url"] == expected

    def test_unpublished_episode_preview_omits_live_only_transcript_url(self, rf, client, episode):
        create_transcript(audio=episode.podcast_audio, podlove={"transcripts": [{"start": "00:00:00.000"}]})
        episode.unpublish()
        episode.refresh_from_db()

        context = episode.get_preview_context(rf.get("/"), "")

        assert context["render_detail"] is True
        assert "episode_transcript_url" not in context
        url = reverse(
            "cast:episode-transcript",
            kwargs={"blog_slug": episode.blog.slug, "episode_slug": episode.slug},
        )
        assert client.get(url).status_code == 404

    def test_get_vtt_transcript_url_no_transcript(self, rf, mocker):
        episode = Episode(id=1)
        request = rf.get("/")
        repository = mocker.MagicMock()
        repository.transcript.vtt = None
        assert episode.get_vtt_transcript_url(request, repository) is None

    def test_get_vtt_transcript_url_includes_episode_context(self, rf, episode):
        transcript = create_transcript(audio=episode.podcast_audio, vtt="WEBVTT\n\n")
        request = rf.get("/")

        url = episode.get_vtt_transcript_url(request, None)

        expected = reverse("cast:webvtt-transcript", kwargs={"pk": transcript.pk})
        assert url == request.build_absolute_uri(f"{expected}?episode_id={episode.pk}")

    def test_get_podcastindex_transcript_url_no_transcript(self, rf, mocker):
        episode = Episode(id=1)
        request = rf.get("/")
        repository = mocker.MagicMock()
        repository.transcript.dote = None
        assert episode.get_podcastindex_transcript_url(request, repository) is None

    def test_get_podcastindex_transcript_url_includes_episode_context(self, rf, episode):
        transcript = create_transcript(
            audio=episode.podcast_audio,
            dote={"lines": [{"startTime": "00:00:00,000", "endTime": "00:00:01,000", "text": "Hello"}]},
        )
        request = rf.get("/")

        url = episode.get_podcastindex_transcript_url(request, None)

        expected = reverse("cast:podcastindex-transcript-json", kwargs={"pk": transcript.pk})
        assert url == request.build_absolute_uri(f"{expected}?episode_id={episode.pk}")


@pytest.mark.django_db
def test_custom_episode_form():
    # arrange the custom episode form
    CustomEpisodeForm._meta.model = Episode
    CustomEpisodeForm._meta.fields = ("podcast_audio", "about_to_be_published")
    CustomEpisodeForm.formsets = {}

    # test the form with no data
    form = CustomEpisodeForm()
    assert not form.is_valid()

    assert "action-publish" not in form.fields

    # test the form with the "Save draft" button clicked (no audio file is ok)
    form = CustomEpisodeForm({"podcast_audio": None})
    assert form.is_valid()

    # test the form with the "Publish" button clicked (audio file is required)
    form = CustomEpisodeForm({"action-publish": "action-publish", "podcast_audio": None})
    form.fields["podcast_audio"] = forms.IntegerField(required=False)
    assert not form.is_valid()

    # tolerate duplicate publish values without rendering a hidden field that can shadow Wagtail's submit button
    form = CustomEpisodeForm(QueryDict("action-publish=action-publish&action-publish=&podcast_audio="))
    form.fields["podcast_audio"] = forms.IntegerField(required=False)
    assert not form.is_valid()


@pytest.mark.django_db
def test_episode_edit_view_publish_action_publishes_contributor_assignments(admin_client, episode):
    contributor = Contributor.objects.create(display_name="Published Guest", slug="published-guest")
    edit_url = reverse("wagtailadmin_pages:edit", args=(episode.pk,))
    post_data = {
        "action-publish": "action-publish",
        "title": episode.title,
        "slug": episode.slug,
        "visible_date": timezone.localtime(episode.visible_date).strftime("%Y-%m-%d %H:%M"),
        "podcast_audio": str(episode.podcast_audio_id),
        "body-count": "1",
        "body-0-deleted": "",
        "body-0-order": "0",
        "body-0-type": "overview",
        "body-0-value-count": "1",
        "body-0-value-0-deleted": "",
        "body-0-value-0-order": "0",
        "body-0-value-0-type": "heading",
        "body-0-value-0-value": "Published overview",
        "keywords": "",
        "explicit": "1",
        "cover_image": "",
        "cover_alt_text": "",
        "tags": "",
        "seo_title": "",
        "search_description": "",
        "go_live_at": "",
        "expire_at": "",
        "comments-TOTAL_FORMS": "0",
        "comments-INITIAL_FORMS": "0",
        "comments-MIN_NUM_FORMS": "0",
        "comments-MAX_NUM_FORMS": "1000",
        "contributor_assignments-TOTAL_FORMS": "1",
        "contributor_assignments-INITIAL_FORMS": "0",
        "contributor_assignments-MIN_NUM_FORMS": "0",
        "contributor_assignments-MAX_NUM_FORMS": "1000",
        "contributor_assignments-0-contributor": str(contributor.pk),
        "contributor_assignments-0-role": EpisodeContributor.ROLE_GUEST,
        "contributor_assignments-0-link": "",
        "contributor_assignments-0-ORDER": "0",
        "contributor_assignments-0-id": "",
    }

    response = admin_client.post(edit_url, post_data)

    assert response.status_code == 302
    episode.refresh_from_db()
    assert episode.live is True
    assert episode.contributor_assignments.get().contributor == contributor
    live_episode = episode.live_revision.as_object()
    assert [assignment.contributor for assignment in live_episode.contributor_assignments.all()] == [contributor]


@pytest.mark.django_db
def test_homepage_serve(episode, mocker):
    mocker.patch("cast.models.pages.Page.serve", return_value="foobar")
    homepage = HomePage()

    # without alias
    assert homepage.serve(None) == "foobar"

    # with alias
    homepage.alias_for_page = episode
    r = homepage.serve(None)
    assert r.status_code == 302


@pytest.mark.django_db
def test_video_create_poster_video_url_without_http(mocker, tmp_path):
    tmp_poster = tmp_path / "poster.jpg"

    def fake_mkstemp(prefix, suffix):
        assert prefix == "poster_"
        assert suffix == ".jpg"
        return os.open(tmp_poster, os.O_CREAT | os.O_RDWR), str(tmp_poster)

    mocker.patch("cast.models.video.tempfile.mkstemp", side_effect=fake_mkstemp)
    mocker.patch("cast.models.video.Video._get_video_dimensions", return_value=(1, 1))
    run = mocker.patch("cast.models.video.subprocess.run", side_effect=ValueError())

    class Original:
        url = "https://example.com/video.mp4"

    video = Video()
    mocker.patch.object(video, "original", Original())
    with pytest.raises(ValueError):
        video._create_poster()
    call_kwargs = run.call_args_list[0]
    command = call_kwargs.args[0]
    assert command[0] == "ffmpeg"
    assert "https://example.com/video.mp4" in command
    assert call_kwargs.kwargs.get("check") is True
    assert call_kwargs.kwargs.get("timeout") == 30


@pytest.mark.django_db
def test_video_create_poster_closes_mkstemp_fd_and_removes_temp_file(mocker, tmp_path):
    tmp_poster = tmp_path / "poster.jpg"
    created_fd: int | None = None

    def fake_mkstemp(prefix, suffix):
        nonlocal created_fd
        assert prefix == "poster_"
        assert suffix == ".jpg"
        created_fd = os.open(tmp_poster, os.O_CREAT | os.O_RDWR)
        return created_fd, str(tmp_poster)

    def fake_run(command, **kwargs):
        if command[0] == "ffmpeg":
            tmp_poster.write_bytes(b"poster-bytes")
        return None

    mocker.patch("cast.models.video.tempfile.mkstemp", side_effect=fake_mkstemp)
    mocker.patch("cast.models.video.Video._get_video_dimensions", return_value=(1, 1))
    mocker.patch("cast.models.video.subprocess.run", side_effect=fake_run)
    poster_save = mocker.patch("cast.models.video.Video.poster.field.attr_class.save")

    class Original:
        url = "https://example.com/video.mp4"

    video = Video()
    mocker.patch.object(video, "original", Original())
    video._create_poster()

    assert created_fd is not None
    with pytest.raises(OSError, match="Bad file descriptor"):
        os.fstat(created_fd)
    assert not tmp_poster.exists()
    assert poster_save.called


@pytest.mark.django_db
def test_video_create_poster_removes_temp_file_when_poster_save_fails(mocker, tmp_path):
    tmp_poster = tmp_path / "poster.jpg"
    created_fd, real_path = None, str(tmp_poster)

    def fake_mkstemp(prefix, suffix):
        nonlocal created_fd
        assert prefix == "poster_"
        assert suffix == ".jpg"
        created_fd = os.open(real_path, os.O_CREAT | os.O_RDWR)
        return created_fd, real_path

    def fake_run(command, **kwargs):
        if command[0] == "ffmpeg":
            tmp_poster.write_bytes(b"poster-bytes")
        return None

    mocker.patch("cast.models.video.tempfile.mkstemp", side_effect=fake_mkstemp)
    mocker.patch("cast.models.video.Video._get_video_dimensions", return_value=(1, 1))
    mocker.patch("cast.models.video.subprocess.run", side_effect=fake_run)
    mocker.patch("cast.models.video.Video.poster.field.attr_class.save", side_effect=RuntimeError("save failed"))

    class Original:
        url = "https://example.com/video.mp4"

    video = Video()
    mocker.patch.object(video, "original", Original())
    with pytest.raises(RuntimeError, match="save failed"):
        video._create_poster()

    assert created_fd is not None
    with pytest.raises(OSError, match="Bad file descriptor"):
        os.fstat(created_fd)
    assert not tmp_poster.exists()


@pytest.mark.django_db
def test_video_create_poster_handles_missing_temp_file_on_success(mocker, tmp_path):
    tmp_poster = tmp_path / "poster.jpg"
    created_fd: int | None = None

    def fake_mkstemp(prefix, suffix):
        nonlocal created_fd
        assert prefix == "poster_"
        assert suffix == ".jpg"
        created_fd = os.open(tmp_poster, os.O_CREAT | os.O_RDWR)
        return created_fd, str(tmp_poster)

    def fake_run(command, **kwargs):
        if command[0] == "ffmpeg" and tmp_poster.exists():
            tmp_poster.write_bytes(b"poster-bytes")
        return None

    def fake_save(_name, content, save=False):
        del save
        os.unlink(content.file.name)

    mocker.patch("cast.models.video.tempfile.mkstemp", side_effect=fake_mkstemp)
    mocker.patch("cast.models.video.Video._get_video_dimensions", return_value=(1, 1))
    mocker.patch("cast.models.video.subprocess.run", side_effect=fake_run)
    mocker.patch("cast.models.video.Video.poster.field.attr_class.save", side_effect=fake_save)

    class Original:
        url = "https://example.com/video.mp4"

    video = Video()
    mocker.patch.object(video, "original", Original())
    video._create_poster()

    assert created_fd is not None
    with pytest.raises(OSError, match="Bad file descriptor"):
        os.fstat(created_fd)
    assert not tmp_poster.exists()


@pytest.mark.django_db
@pytest.mark.parametrize("dimensions", [(None, None), (640, None), (None, 480)])
def test_video_create_poster_skips_ffmpeg_when_dimensions_missing(mocker, tmp_path, dimensions):
    tmp_poster = tmp_path / "poster.jpg"
    created_fd: int | None = None

    def fake_mkstemp(prefix, suffix):
        nonlocal created_fd
        assert prefix == "poster_"
        assert suffix == ".jpg"
        created_fd = os.open(tmp_poster, os.O_CREAT | os.O_RDWR)
        return created_fd, str(tmp_poster)

    mocker.patch("cast.models.video.tempfile.mkstemp", side_effect=fake_mkstemp)
    mocker.patch("cast.models.video.Video._get_video_dimensions", return_value=dimensions)
    run = mocker.patch("cast.models.video.subprocess.run")
    poster_save = mocker.patch("cast.models.video.Video.poster.field.attr_class.save")

    class Original:
        url = "https://example.com/video.mp4"

    video = Video()
    mocker.patch.object(video, "original", Original())

    video._create_poster()

    assert created_fd is not None
    with pytest.raises(OSError, match="Bad file descriptor"):
        os.fstat(created_fd)
    run.assert_not_called()
    poster_save.assert_not_called()
    assert not tmp_poster.exists()


@pytest.mark.django_db
def test_video_create_poster_handles_missing_dimensions_gracefully(mocker, tmp_path):
    tmp_poster = tmp_path / "poster.jpg"

    def fake_mkstemp(prefix, suffix):
        assert prefix == "poster_"
        assert suffix == ".jpg"
        return os.open(tmp_poster, os.O_CREAT | os.O_RDWR), str(tmp_poster)

    mocker.patch("cast.models.video.tempfile.mkstemp", side_effect=fake_mkstemp)
    mocker.patch("cast.models.video.Video._get_video_dimensions", return_value=(None, None))
    run = mocker.patch("cast.models.video.subprocess.run")
    poster_save = mocker.patch("cast.models.video.Video.poster.field.attr_class.save")

    class Original:
        url = "https://example.com/video.mp4"

    video = Video()
    mocker.patch.object(video, "original", Original())

    video.create_poster()

    run.assert_not_called()
    poster_save.assert_not_called()
    assert not tmp_poster.exists()
    assert not video.poster


@pytest.mark.django_db
def test_video_save_with_force_insert_does_not_attempt_second_insert(mocker, user, minimal_mp4):
    def fake_create_poster():
        video.poster.name = "cast_videos/poster/test.jpg"

    video = Video(user=user, title="force-insert video", original=minimal_mp4)
    create_poster = mocker.patch.object(video, "create_poster", side_effect=fake_create_poster)
    video.save(force_insert=True)

    assert video.pk is not None
    create_poster.assert_called_once()
    video.refresh_from_db()
    assert video.poster.name == "cast_videos/poster/test.jpg"


@pytest.mark.django_db
def test_video_save_propagates_using_on_poster_update(mocker, user):
    save_calls = []

    def fake_save(_self, *args, **kwargs):
        save_calls.append(kwargs.copy())
        return None

    mocker.patch("model_utils.models.TimeStampedModel.save", autospec=True, side_effect=fake_save)
    video = Video(user=user, title="poster update")

    def fake_create_poster():
        video.poster.name = "poster.jpg"

    mocker.patch.object(video, "create_poster", side_effect=fake_create_poster)

    video.save(using="default")

    assert save_calls[0]["using"] == "default"
    assert save_calls[1]["using"] == "default"
    assert save_calls[1]["update_fields"] == ["poster"]


@pytest.mark.django_db
def test_transcript_podlove_data_no_podlove_or_dote():
    transcript = Transcript()
    assert transcript.podlove_data == {}
    assert transcript.dote_data == {}
    assert transcript.podcastindex_data == {}


@pytest.mark.django_db
def test_transcript_get_all_paths_skips_empty_fields():
    transcript = Transcript()
    assert transcript.get_all_paths() == set()


@pytest.mark.django_db
def test_transcript_data_missing_files(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path
    transcript = Transcript()
    transcript.podlove.name = "cast_transcript/missing.json"
    transcript.dote.name = "cast_transcript/missing_dote.json"
    assert transcript.podlove_data == {}
    assert transcript.dote_data == {}


@pytest.fixture
def dote():
    return {
        "lines": [
            {
                "startTime": "00:00:00,000",
                "endTime": "00:00:01,000",
                "speakerDesignation": "speaker",
                "text": "text",
            }
        ]
    }


@pytest.mark.django_db
def test_transcript_dote_data(dote):
    transcript = create_transcript(dote=dote)
    assert transcript.dote_data == dote


@pytest.mark.django_db
def test_transcript_podcastindex_data(dote):
    transcript = create_transcript(dote=dote)
    assert transcript.podcastindex_data == {
        "version": "1.0",
        "segments": [
            {
                "startTime": 0.0,
                "endTime": 1.0,
                "speaker": "speaker",
                "body": "text",
            }
        ],
    }


def test_convert_dote_to_podcastindex_transcript(dote):
    podcastindex = convert_dote_to_podcastindex_transcript(dote)
    assert podcastindex == {
        "version": "1.0",
        "segments": [
            {
                "startTime": 0.0,
                "endTime": 1.0,
                "speaker": "speaker",
                "body": "text",
            }
        ],
    }


@pytest.mark.parametrize(
    "time_str, expected",
    [
        ("00:00:00,000", 0.0),
        ("00:00:01,000", 1.0),
        ("00:01:00,000", 60.0),
        ("01:00:00,000", 3600.0),
        ("01:00:00,500", 3600.5),
    ],
)
def test_time_to_seconds(time_str, expected):
    assert time_to_seconds(time_str) == expected


def test_time_to_seconds_invalid():
    with pytest.raises(ValueError):
        time_to_seconds("foobar")
