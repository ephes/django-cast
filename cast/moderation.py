from fluent_comments.moderation import FluentCommentsModerator


class Moderator(FluentCommentsModerator):
    spamfilter = None

    def allow(self, comment, content_object, request):
        """
        Allow all. Just mark moderated comments as 'is_removed' but
        keep them in the database. Even awful comments are useful as
        a bad training example :).
        """
        print("allow was called..")
        return True

    def moderate(self, comment, content_object, request):
        # message = f"{comment.name} {comment.title} {comment.comment}"
        # predicted_label = self.spamfilter.predict(message)
        print("moderate was called..")
        # return predicted_label == "spam"
        return True
