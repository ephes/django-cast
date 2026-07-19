# ruff: noqa: F401,F811,I001
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
from cast.models import Audio, Blog, Contributor, ContributorLink, EpisodeContributor, File, Podcast, Season
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
from cast.models.transcript import Transcript
from cast.transcripts.dote import convert_dote_to_podcastindex_transcript, time_to_seconds
from cast.models.video import Video
from tests.factories import EpisodeFactory, PodcastFactory


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

    def test_post_save_media_derivation_is_explicit_opt_in(self, monkeypatch, post):
        """Post.save is pure by default but retains explicit compatibility kwargs."""
        import cast.post_media as post_media_module
        from cast.models import image_renditions

        sync_calls, rendition_calls = [], []
        monkeypatch.setattr(
            post_media_module, "synchronize_post_media", lambda candidate: sync_calls.append(candidate.pk)
        )
        monkeypatch.setattr(
            image_renditions, "create_missing_renditions_for_posts", lambda posts: rendition_calls.append(1)
        )

        post.save()
        assert sync_calls == [] and rendition_calls == []

        post.save(sync_media=True, create_renditions=True)
        assert sync_calls == [post.pk] and rendition_calls == [1]

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

    def test_media_ids_from_body_is_int(self, audio):
        class AudioBlock:
            block_type = "audio"
            value = audio.id

        class ContentBlock:
            value = [AudioBlock()]

        block = ContentBlock()
        post = Post()
        assert post._media_ids_from_body([block]) == {"audio": {audio.id}}

    def test_media_ids_from_body_skips_missing_int(self):
        class AudioBlock:
            block_type = "audio"
            value = 999_992

        class ContentBlock:
            value = [AudioBlock()]

        block = ContentBlock()
        post = Post()
        assert post._media_ids_from_body([block]) == {}

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

    def test_get_description_delegates_to_presenter(self, mocker, simple_request, post):
        expected_html = "<h1>foo</h1>"
        repository = mocker.sentinel.repository
        render = mocker.patch("cast.models.pages.render_post_description", return_value=expected_html)

        description = post.get_description(
            request=simple_request,
            render_detail=True,
            render_for_feed=False,
            escape_html=False,
            remove_newlines=False,
            repository=repository,
        )

        assert description == expected_html
        render.assert_called_once_with(
            post,
            request=simple_request,
            render_detail=True,
            render_for_feed=False,
            escape_html=False,
            remove_newlines=False,
            repository=repository,
        )

    def test_overview_html(self, mocker):
        expected_html = "<h1>foo</h1>"
        mock = mocker.patch("cast.models.pages.render_post_description", return_value=expected_html)
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
        mock = mocker.patch("cast.models.pages.render_post_description", return_value=expected_html)
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
        mock = mocker.patch("cast.models.pages.render_post_description", return_value=expected_html)
        html_field = HtmlField(source="*", render_detail=True)
        html_field._context = {"request": rf.get("/?render_for_feed=false")}
        detail = html_field.to_representation(Post())
        assert detail == expected_html
        assert mock.call_args[1]["render_for_feed"] is False

    def test_detail_html_without_request_uses_default_render_for_feed(self, mocker):
        expected_html = "<h1>foo</h1><p>bar</p>"
        mock = mocker.patch("cast.models.pages.render_post_description", return_value=expected_html)
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
        kwargs = {} if local_template_name is None else {"local_template_name": local_template_name}

        assert post.get_template(simple_request, **kwargs) == expected_template

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
        mocker.patch("cast.post_media.synchronize_post_media", side_effect=ValueError())
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
