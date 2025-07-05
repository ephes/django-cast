from django.contrib.auth import get_user_model
from django.db import models
from model_utils.models import TimeStampedModel


class File(TimeStampedModel):
    user = models.ForeignKey(get_user_model(), on_delete=models.CASCADE)
    original = models.FileField(upload_to="cast_files/")

    def get_all_paths(self) -> set[str]:
        paths = set()
        paths.add(self.original.name)
        return paths
