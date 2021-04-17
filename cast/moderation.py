from fluent_comments.moderation import FluentCommentsModerator

from .naive_bayes import get_pretrained_model, predict_label


model = get_pretrained_model()


class Moderator(FluentCommentsModerator):
    def allow(self, comment, content_object, request):
        return True

    def moderate(self, comment, content_object, request):
        message = f"{comment.name} {comment.title} {comment.comment}"
        predicted_label = predict_label(message, **model)
        return predicted_label == "spam"
