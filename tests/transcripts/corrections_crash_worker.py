"""Subprocess half of the real-storage correction crash oracle."""

import signal
import sys

import django


def main() -> None:
    django.setup()
    from cast.file_replacement import StagedFileReplacementGroup
    from cast.models import Transcript
    from cast.transcripts import corrections

    def pause(*args, **kwargs):
        print("READY", flush=True)
        signal.pause()
        raise AssertionError("The parent must kill this process")

    boundary, pk = sys.argv[1:]
    if boundary == "before_commit":
        original_save = corrections._save_derived_artifacts

        def save_then_pause(*args, **kwargs):
            original_save(*args, **kwargs)
            pause()

        corrections._save_derived_artifacts = save_then_pause
    else:
        StagedFileReplacementGroup.delete_old_files = pause
    corrections.refresh_transcript_corrections(Transcript.objects.get(pk=pk))


if __name__ == "__main__":
    main()
