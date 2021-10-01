from fluent_comments.moderation import FluentCommentsModerator


class Moderator(FluentCommentsModerator):
    def __init__(self, model, spamfilter=None):
        super().__init__(model)
        # Allow spamfilter to be set for tests
        self.spamfilter = spamfilter

    def allow(self, comment, content_object, request):
        """
        Allow all. Just mark moderated comments as 'is_removed' but
        keep them in the database. Even awful comments are useful as
        a bad training example :).
        """
        return True

    def moderate(self, comment, content_object, request):
        message = f"{comment.name} {comment.title} {comment.comment}"
        predicted_label = self.spamfilter.predict(message)
        if predicted_label == "spam":
            comment.is_removed, comment.is_public = True, False
            return True
        else:
            comment.is_removed, comment.is_public = False, True
            return False
