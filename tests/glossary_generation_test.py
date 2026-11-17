"""Import one coherent opened generation, including intentional symlinks."""

import os
import time
from contextlib import contextmanager

import pytest
from django.core.management import CommandError

from cast.management.commands import import_transcript_glossary as command
from cast.models import TranscriptGlossaryTerm
from tests.import_transcript_glossary_command_helpers import run


@pytest.mark.django_db
@pytest.mark.parametrize("dry_run", [False, True])
@pytest.mark.parametrize("change", ["rewrite", "restored_mtime", "truncate", "short_read", "replace", "symlink"])
def test_import_admits_only_coherent_opened_generation(podcast, tmp_path, monkeypatch, dry_run, change):
    path = tmp_path / "input.json"
    old = b'[{"term":"Alpha","notes":"old"}]'
    new = b'[{"term":"Bravo","notes":"new"}]'
    path.write_bytes(old)
    # Keep the in-place rewrite detectable regardless of timestamp granularity:
    # the opened generation carries an explicit past modification time.
    os.utime(path, ns=(1_000_000_000, 1_000_000_000))
    source_path = path
    if change == "symlink":
        source_path = tmp_path / "link.json"
        source_path.symlink_to(path)
    fdopen = os.fdopen

    @contextmanager
    def controlled_open(fd, *args, **kwargs):
        with fdopen(fd, *args, buffering=0, **kwargs) as source:

            class Reader:
                def read(self, size):
                    prefix = source.read(17)
                    if change in {"rewrite", "restored_mtime"}:
                        before = path.stat()
                        if change == "restored_mtime":
                            # Only the change time reveals this rewrite; step past
                            # coarse filesystem clocks (1-10 ms) so it can tick.
                            time.sleep(0.05)
                        with path.open("r+b") as writer:
                            writer.write(new)
                        if change == "restored_mtime":
                            os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
                    elif change == "truncate":
                        path.write_bytes(b"[]")
                    elif change == "replace":
                        replacement = tmp_path / "replacement.json"
                        replacement.write_bytes(new)
                        replacement.replace(path)
                    if change == "short_read":
                        return b"[]"  # Valid JSON but fewer bytes than the admitted descriptor.
                    return prefix + source.read(size - len(prefix))

            yield Reader()

    monkeypatch.setattr(command.os, "fdopen", controlled_open)
    if change in {"rewrite", "restored_mtime", "truncate", "short_read"}:
        with pytest.raises(CommandError, match="changed while reading"):
            run(podcast.slug, str(source_path), dry_run=dry_run)
        assert not TranscriptGlossaryTerm.objects.exists()
    else:
        stdout, _ = run(podcast.slug, str(source_path), dry_run=dry_run)
        assert "created=1" in stdout
        assert list(TranscriptGlossaryTerm.objects.values_list("term", "notes")) == (
            [] if dry_run else [("Alpha", "old")]
        )
