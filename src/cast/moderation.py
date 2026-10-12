from typing import Any

from django.http import HttpRequest

from .models import SpamFilter


class Moderator:
    def __init__(self, model: type[Any] | None, spamfilter: SpamFilter | None = None) -> None:
        self.model = model
        # An injected spam filter (used by tests) is kept for the moderator's lifetime.
        # Without one, the default filter is looked up for every moderated comment:
        # the default moderator lives for the whole process, so a cached row would
        # ignore a filter installed, retrained, replaced or removed after startup.
        self._spamfilter = spamfilter

    @property
    def spamfilter(self) -> SpamFilter | None:
        if self._spamfilter is not None:
            return self._spamfilter
        return SpamFilter.get_default()

    @spamfilter.setter
    def spamfilter(self, spamfilter: SpamFilter | None) -> None:
        self._spamfilter = spamfilter

    def allow(self, comment: Any, content_object: Any, request: HttpRequest) -> bool:
        """
        Allow all. Just mark moderated comments as 'is_removed' but
        keep them in the database. Even awful comments are useful as
        a bad training example :).
        """
        return True

    def moderate(self, comment: Any, content_object: Any, request: HttpRequest) -> bool:
        message = SpamFilter.comment_to_message(comment)
        spamfilter = self.spamfilter
        if spamfilter is not None:
            predicted_label = spamfilter.model.predict_label(message)
        else:
            predicted_label = "unknown"
        if predicted_label == "spam":
            comment.is_removed, comment.is_public = True, False
            return True
        else:
            comment.is_removed, comment.is_public = False, True
            return False
