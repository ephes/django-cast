Unreleased
==========

- Resolve Voxhelm API base and token as a pair from one configuration level.
  Incomplete pairs no longer inherit deployment credentials. Move mixed-level
  credentials to one level before upgrading; changing the Wagtail API base
  requires re-entering its token. Saving with both credential fields blank
  removes the site pair so deployment credentials can be used.

- Rename generic ``Speaker N:`` cue prefixes as well as voice tags through
  ``Transcript.rewrite_speaker_labels``. Renamed prefixes become voice tags
  for subsequent renames and public speaker sanitization.
