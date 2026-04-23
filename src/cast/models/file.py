from django.contrib.auth import get_user_model
from django.db import models
from model_utils.models import TimeStampedModel


class File(TimeStampedModel):
    """A generic uploaded file associated with a user.

    Used for documents and other file types that are not images, audio, or video.
    """

    user = models.ForeignKey(get_user_model(), on_delete=models.CASCADE)
    original = models.FileField(upload_to="cast_files/")

    def get_all_paths(self) -> set[str]:
        paths = set()
        if self.original.name:
            paths.add(self.original.name)
        return paths
