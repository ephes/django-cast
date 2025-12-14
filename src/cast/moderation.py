from typing import Any

from django.http import HttpRequest

from .models import SpamFilter


class Moderator:
    def __init__(self, model, spamfilter=None):
        self.model = model
        # Allow spamfilter to be set for tests
        if spamfilter is not None:
            self.spamfilter = spamfilter
        else:
            self.spamfilter = SpamFilter.get_default()

    def allow(self, comment: Any, content_object: Any, request: HttpRequest) -> bool:
        """
        Allow all. Just mark moderated comments as 'is_removed' but
        keep them in the database. Even awful comments are useful as
        a bad training example :).
        """
        return True

    def moderate(self, comment: Any, content_object: Any, request: HttpRequest) -> bool:
        message = SpamFilter.comment_to_message(comment)
        if self.spamfilter is not None:
            predicted_label = self.spamfilter.model.predict_label(message)
        else:
            predicted_label = "unknown"
        if predicted_label == "spam":
            comment.is_removed, comment.is_public = True, False
            return True
        else:
            comment.is_removed, comment.is_public = False, True
            return False
