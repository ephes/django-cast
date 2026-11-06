"""Compatibility imports for transcript transforms and speaker visibility policy.

Pure transforms live in ``cast.transcripts`` format modules; episode policy lives
in ``cast.transcripts.visibility``. Existing imports keep the same callables.
"""

from .transcripts.dote import (
    apply_speaker_mapping_to_dote_data as apply_speaker_mapping_to_dote_data,
    sanitize_dote_data as sanitize_dote_data,
)
from .transcripts.parsing import (
    clean_speaker_label as clean_speaker_label,
)
from .transcripts.podlove import (
    PODLOVE_SPEAKER_FIELDS as PODLOVE_SPEAKER_FIELDS,
    apply_speaker_mapping_to_podlove_data as apply_speaker_mapping_to_podlove_data,
    podlove_contributors_from_data as podlove_contributors_from_data,
    sanitize_podlove_data as sanitize_podlove_data,
)
from .transcripts.visibility import (
    EDITOR_SPEAKER_PREVIEW_ATTR as EDITOR_SPEAKER_PREVIEW_ATTR,
    _current_mapping_rows as _current_mapping_rows,
    _current_raw_speaker_labels as _current_raw_speaker_labels,
    _episode_is_publicly_visible as _episode_is_publicly_visible,
    _episode_shows_speaker_labels as _episode_shows_speaker_labels,
    _public_contributor_ids as _public_contributor_ids,
    _public_episode_contexts_for_transcript as _public_episode_contexts_for_transcript,
    apply_public_speaker_mapping_to_dote_data as apply_public_speaker_mapping_to_dote_data,
    apply_public_speaker_mapping_to_podlove_data as apply_public_speaker_mapping_to_podlove_data,
    apply_public_speaker_mapping_to_webvtt_content as apply_public_speaker_mapping_to_webvtt_content,
    audio_transcript_diarization_disabled as audio_transcript_diarization_disabled,
    editor_speaker_preview_episode as editor_speaker_preview_episode,
    public_episode_from_request as public_episode_from_request,
    public_one_off_speaker_labels_for_transcript as public_one_off_speaker_labels_for_transcript,
    public_speaker_labels_for_audio as public_speaker_labels_for_audio,
    public_speaker_labels_for_episode as public_speaker_labels_for_episode,
    public_speaker_labels_for_transcript as public_speaker_labels_for_transcript,
    public_speaker_mapping_for_transcript as public_speaker_mapping_for_transcript,
    strict_public_speaker_labels_for_audio as strict_public_speaker_labels_for_audio,
    strict_public_speaker_labels_for_transcript as strict_public_speaker_labels_for_transcript,
)
from .transcripts.webvtt import (
    _sanitize_webvtt_payload_line as _sanitize_webvtt_payload_line,
    apply_speaker_mapping_to_webvtt_content as apply_speaker_mapping_to_webvtt_content,
    sanitize_webvtt_content as sanitize_webvtt_content,
)
