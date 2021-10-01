from django.db import models

from model_utils.models import TimeStampedModel


class SpamFilter(TimeStampedModel):
    name = models.CharField(unique=True, max_length=128)
    model = models.JSONField(verbose_name="Spamfilter Model", default=dict)

    @classmethod
    @property
    def default(cls):
        return cls.objects.first()
