import pytest

from cast.forms import PostForm


class TestPostForm:
    @pytest.mark.django_db
    def test_post_form_has_chaptermarks_field_false(self, post):
        form = PostForm(instance=post)
        assert "chaptermarks" not in form.fields

    @pytest.mark.django_db
    def test_post_form_has_chaptermarks_field_true(self, post, audio):
        post.podcast_audio = audio
        form = PostForm(instance=post)
        assert "chaptermarks" in form.fields

    @pytest.mark.django_db
    def test_post_form_clean_chaptermarks_valid(self, post, chaptermarks):
        # prepare post
        chaptermark = chaptermarks[0]
        audio = chaptermark.audio
        post.podcast_audio = audio

        # create text for chaptermarks area
        lines = []
        for chaptermark in chaptermarks:
            lines.append(chaptermark.original_line)
        chaptermarks_text = "\n".join(lines)

        # create form + test
        form = PostForm(instance=post)
        form._clean_chaptermarks({"chaptermarks": chaptermarks_text})
        assert len(form.errors) == 0

    @pytest.mark.django_db
    def test_post_form_clean_chaptermarks_invalid(self, post, audio):
        # prepare post
        post.podcast_audio = audio

        # create text for chaptermarks area
        chaptermarks_text = "foooooooooooooooooooooooooooo bar baz blub"

        # create form + test
        form = PostForm(instance=post)
        cleaned_data = {"chaptermarks": chaptermarks_text}
        form.cleaned_data = cleaned_data
        form._clean_chaptermarks(cleaned_data)
        assert "chaptermarks" in form.errors
