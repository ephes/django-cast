from typing import Any
from urllib.parse import urlencode

from django.template import Context
from django.urls import reverse
from django.utils.functional import cached_property
from wagtail.admin.panels import Panel

from cast.transcripts.generation_status import get_transcript_generation_status_context, transcript_voice_counts


class EpisodeTranscriptStatusPanel(Panel):
    """Display transcript generation status in the episode edit form."""

    class BoundPanel(Panel.BoundPanel):
        template_name = "cast/wagtail/episode_transcript_status_panel.html"

        @cached_property
        def transcript_generation_context(self) -> dict[str, Any]:
            # Read the saved revision, not unsubmitted form values.
            from cast.transcripts.editing import episode_from_latest_revision
            from cast.views.voxhelm import generation_available, get_generation_readiness

            episode = episode_from_latest_revision(self.instance) if self.instance.pk else self.instance
            audio = getattr(episode, "podcast_audio", None)
            context: dict[str, Any] = {"transcript_audio": audio}
            if audio is None:
                return context
            context.update(get_transcript_generation_status_context(audio=audio))
            context["upload_transcript_url"] = reverse("cast-transcript:add") + "?" + urlencode({"audio": audio.pk})
            context["generate_transcript_url"] = reverse("cast-voxhelm:generate_episode", args=(episode.pk,))
            context["can_generate_transcript"] = generation_available(request=self.request, audio=audio)
            context["transcript_status_url"] = reverse("cast-voxhelm:status_audio", args=(audio.pk,))
            if context["can_generate_transcript"]:
                context.update(get_generation_readiness(request=self.request, audio=audio, episode=episode))
            if hasattr(audio, "transcript"):
                context["transcript"] = audio.transcript
                context["transcript_voices"] = transcript_voice_counts(audio.transcript)
            return context

        def is_shown(self) -> bool:
            return bool(self.instance.pk)

        def get_context_data(self, parent_context: Context | dict[str, Any] | None = None) -> dict[str, Any]:
            context = super().get_context_data(parent_context)
            context.update(self.transcript_generation_context)
            return context
