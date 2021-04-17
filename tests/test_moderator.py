import pytest

from django_comments import get_model as get_comments_model

from cast.moderation import Moderator


class TestModerator:
    pytestmark = pytest.mark.django_db

    def test_moderator(self):
        test_data = [
            # ((name, title, comment), is_spam)
            (("Eric Jones", "", "Hey there, I just found your site"), True),
            (("Jochen", "Moins", "Das ist ein normaler Kommentar."), False),
        ]

        Comment = get_comments_model()
        moderator = Moderator(Comment)
        for (name, title, comment_body), expected_is_spam in test_data:
            comment = Comment(name=name, title=title, comment=comment_body)
            moderated = moderator.moderate(comment, None, None)
            assert expected_is_spam == moderated
