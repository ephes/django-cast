from typing import Any

from django.template import Context
from django.utils.functional import cached_property
from wagtail.admin.panels import Panel

from cast.transcripts.generation_status import get_transcript_generation_status_context


class EpisodeTranscriptStatusPanel(Panel):
    """Display transcript generation status in the episode edit form."""

    class BoundPanel(Panel.BoundPanel):
        template_name = "cast/wagtail/episode_transcript_status_panel.html"

        @cached_property
        def transcript_generation_context(self) -> dict[str, str | bool]:
            audio = getattr(self.instance, "podcast_audio", None)
            if audio is None:
                return {
                    "transcript_generation_active": False,
                    "transcript_generation_status": "",
                    "transcript_generation_message": "",
                    "transcript_generation_error": "",
                    "transcript_generation_transcript_url": "",
                }

            return get_transcript_generation_status_context(audio=audio)

        def is_shown(self) -> bool:
            return bool(self.transcript_generation_context["transcript_generation_status"])

        def get_context_data(self, parent_context: Context | dict[str, Any] | None = None) -> dict[str, Any]:
            context = super().get_context_data(parent_context)
            context.update(self.transcript_generation_context)
            return context
