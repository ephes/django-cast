from django.db import models
from wagtail.snippets.models import register_snippet


@register_snippet
class PostCategory(models.Model):
    """Post category snippet for grouping posts."""

    name = models.CharField(max_length=255, unique=True, help_text="The name for this category")
    slug = models.SlugField(verbose_name="slug", unique=True, help_text="A slug to identify posts by this category")

    class Meta:
        verbose_name = "Post Category"
        verbose_name_plural = "Post Categories"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name
