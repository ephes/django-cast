from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from wagtail.models import Site

from .audio import Audio


class TranscriptGeneration(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", _("Queued")
        RUNNING = "running", _("Running")
        SUCCEEDED = "succeeded", _("Succeeded")
        FAILED = "failed", _("Failed")

    ACTIVE_STATUSES = {Status.QUEUED, Status.RUNNING}

    audio = models.OneToOneField(Audio, on_delete=models.CASCADE, related_name="transcript_generation")
    site = models.ForeignKey(Site, on_delete=models.SET_NULL, null=True, blank=True)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    task_ref = models.CharField(max_length=255)
    voxhelm_job_id = models.CharField(max_length=255, blank=True)
    task_result_id = models.CharField(max_length=255, blank=True)
    source_url = models.URLField(max_length=1000, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-updated_at",)

    def queue_submission(
        self,
        *,
        task_ref: str,
        voxhelm_job_id: str,
        source_url: str,
        task_result_id: str,
        site: Site | None,
        requested_by: Any | None,
    ) -> None:
        self.task_ref = task_ref
        self.voxhelm_job_id = voxhelm_job_id
        self.task_result_id = task_result_id
        self.source_url = source_url
        self.site = site
        self.requested_by = requested_by
        self.status = self.Status.QUEUED
        self.error_message = ""
        self.started_at = None
        self.completed_at = None
        self.save(
            update_fields=[
                "task_ref",
                "voxhelm_job_id",
                "task_result_id",
                "source_url",
                "site",
                "requested_by",
                "status",
                "error_message",
                "started_at",
                "completed_at",
                "updated_at",
            ]
        )

    def mark_running(self) -> None:
        self.status = self.Status.RUNNING
        self.error_message = ""
        self.started_at = timezone.now()
        self.completed_at = None
        self.save(update_fields=["status", "error_message", "started_at", "completed_at", "updated_at"])

    def mark_succeeded(self) -> None:
        self.status = self.Status.SUCCEEDED
        self.error_message = ""
        self.completed_at = timezone.now()
        self.save(update_fields=["status", "error_message", "completed_at", "updated_at"])

    def mark_failed(self, message: str) -> None:
        self.status = self.Status.FAILED
        self.error_message = message
        self.completed_at = timezone.now()
        self.save(update_fields=["status", "error_message", "completed_at", "updated_at"])

    @property
    def is_active(self) -> bool:
        return self.status in self.ACTIVE_STATUSES
