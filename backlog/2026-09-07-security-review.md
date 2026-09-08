# Security review: 2026-09-07

Status: Confirmed findings fixed and validated on 2026-09-08. Independent review
closed at diminishing returns with an advisory verdict. Separate hardening
observations remain follow-ups.

Reviewed commit: `04220c4d0a42165413df43e82c9d9c4ca6700190` (`develop`).

The review used `gpt-daybreak-blue-latest` subagents for public surfaces,
media/Voxhelm, and independent editor API verification. The lead reviewer
checked the relevant implementation and documentation and ran the repository
quality gate and dependency audits. The original analysis made no application
fixes; the implementation follow-up below records the subsequent repairs.

## Confirmed findings

### SEC-2026-018 — Transcript forms bypass Audio collection permissions

Severity: Medium. Status: Fixed. Evidence: local reproduction and regression tests passed.

References:

- `src/cast/forms.py:281-298`: `TranscriptForm` exposes `audio` without filtering
  its queryset by the requesting user's Audio permissions.
- `src/cast/views/media.py:115-125`: the add path checks Transcript add permission
  and saves the submitted relationship.
- `src/cast/views/transcript.py:449-453`: edit access is checked against the
  Transcript's collection.
- `src/cast/views/transcript.py:257-278,492`: the edit context includes the linked
  Audio's file URLs.
- `src/cast/models/pages.py:880-889`: an episode resolves its transcript through
  `podcast_audio.transcript`.

A Wagtail user with Transcript add/change permissions in collection A, but no
Audio permission in collection B, can select B's Audio in the transcript form.
Submitting that Audio ID with collection A creates a relationship that passes
Transcript authorization and exposes the audio title and media URL. Creating a
new relationship requires an Audio without an existing one-to-one Transcript.

The isolated reproduction created two sibling collections and an Audio owned
by another user. It verified that the limited user's audio queryset included
the forbidden object, the submitted form validated and saved, and
`get_transcript_audio_sources()` returned its media URL. One test passed.

The public episode lookup also means this relationship can attach attacker
supplied transcript content to an episode outside the user's media collection.
That integrity consequence is supported by the lookup code; an end-to-end
public rendering reproduction was not run. The actual ability to download a
disclosed URL depends on the storage backend's access policy.

Fix direction:

- Filter and validate the Audio relationship using the requesting user's Audio
  chooser policy on add, chooser upload, and edit.
- Define how existing cross-collection relationships may be retained or changed;
  do not assume Transcript permissions grant Audio access.
- Test forbidden direct POST IDs as well as form choices, relationship changes,
  and legitimate collection permissions.

This is a remaining gap in the collection boundary addressed by SEC-2026-002,
not evidence that every earlier media permission fix failed.

Implementation follow-up (2026-09-08):

- Shared Audio and Transcript permission policies filter transcript form Audio
  choices and all Transcript admin instance lookups by Audio choose access.
- Existing forbidden relationships are hidden from lists/choosers and return
  404 on direct admin URLs, including transcript edit actions.
- No-user programmatic forms remain trusted callers. Cross-collection
  relationships remain supported when the actor holds both required permissions.
- Regression tests in the implementation cover allowed/forbidden form
  submissions, existing relationships, inherited permissions, and edit actions.

### SEC-2026-019 — Retained comment tokens survive page access revocation

Severity: Medium. Status: Fixed. Evidence: local reproductions and regression tests passed.

References:

- `src/cast/comments/views.py:42-60`: AJAX target resolution checks whether
  comments are enabled but does not check current page visibility.
- `src/cast/comments/views.py:322-341`: the stock POST wrapper has the same gap.
- `src/cast/comments/utils.py:31-37`: `comments_are_open()` checks comment flags,
  not publication state or request-aware page restrictions.

An anonymous visitor can retain valid signed comment form fields obtained while
a post is public. If the post is subsequently unpublished or restricted while
comments remain enabled, both POST endpoints still accept those fields and save
a new comment. This requires a still-valid target-specific form signature and
the normal CSRF requirements; the review did not find signature forgery or a
CSRF bypass. The impact is unauthorized comment creation, not demonstrated
disclosure of the restricted page body.

Four isolated SQLite tests covered both stock and AJAX endpoints after each of
`post.unpublish()` and adding a login restriction. Each test first verified that
anonymous page GET was inaccessible (404 or redirect), then submitted the
previously issued form fields and verified that a comment was saved. All four
passed. These application-level tests were not a browser CSRF exercise.

Fix direction:

- Before preview or creation, recheck live state and inherited/direct view
  restrictions against the current request for Wagtail Page targets.
- Apply the same predicate to both endpoints and preserve deliberately supported
  generic comment targets through an explicit policy.
- Cover revoked access, inherited restrictions, and authorized restricted users.

Cross-site generic-comment behavior was not established as a separate defect.
The earlier closed-comment fix remains present; this finding concerns page
access being revoked without changing the comment-enabled flag.

Implementation follow-up (2026-09-08):

- Both creation endpoints check Wagtail page live state and current direct and
  inherited restrictions before form preview or creation, returning 403 when
  access is unavailable. Unpublished pages receive no editor/superuser bypass.
- Generic non-page targets retain their previous comment policy.
- Regression tests cover retained public form signatures, every built-in
  restriction type, inherited restrictions, permitted restricted visitors,
  previews, and generic targets on both endpoints.

## Hardening observations requiring separate triage

These are source-confirmed missing safeguards, not reproduced resource-exhaustion
attacks or additional demonstrated authorization bypasses.

- **Manual transcript upload size limits:** `TranscriptForm._load_json()` at
  `src/cast/forms.py:350-360` fully loads uploaded JSON, and Podlove/DOTe/VTT
  validators have no application byte cap. A permitted transcript uploader can
  submit large files, subject to deployment request limits. Add a configurable
  cap before parsing and storage, including the VTT path. No large payload or
  memory-exhaustion test was performed.
- **Admin media probe and concurrency limits:** generic admin add/edit/chooser
  saves in `src/cast/views/media.py` do not use the editor API's per-user lock or
  cumulative probe budget. Audio/video probes retain individual 30-second
  timeouts; multiple derivation steps can consume more than the editor API's
  default ten-second budget. Reuse bounded probing and concurrency protection
  across upload entry points. No claim of unbounded subprocess runtime is made,
  and no worker-exhaustion test was performed.
- **Publication approval binding:** `src/cast/api/editor/views.py:360-379`
  publishes the latest revision without a revision precondition. This is
  explicitly documented in `docs/reference/api.rst:818-824`; publish scope and
  Wagtail publish permission are still required. A co-editor can replace a
  previously reviewed draft before an authorized publication. Consider a
  required revision token for workflows where publishing means approval of
  specific reviewed content. This is not a direct write-scope-to-publish bypass.
- **Author self-edit/delete after page access revocation:** the opt-in author
  action endpoints check session ownership and comment eligibility, but not the
  target page's current visibility (`src/cast/comments/views.py`,
  `_author_action_guard()` / `_load_locked_actionable()`). This pre-existing
  behavior is separate from the confirmed comment creation/preview defect.
  Specify whether authors should retain control over their own eligible
  comments after losing page access, then add explicit regressions for that
  policy. The current repair does not change this ownership contract.

## Existing risk and negative results

- Historical unsafe rich text remains a separate, already tracked audit task in
  [the sanitization design record](2026-09-07-editor-richtext-sanitization.md).
  New-write sanitization does not establish that old rows or revisions are safe.
  This review found no new sanitizer bypass in the inspected standard block paths.
- Inspected public page/feed restrictions, request-local feed state, transcript
  cache headers, Twitter player access, signed gallery IDs, comment parent
  isolation, and escaped frontend comment rendering retained their fixes.
- Voxhelm artifact downloads retain same-origin checks, disabled redirects, and
  response caps. Private voice/speaker storage safeguards remain present.
- Editor API authentication, scopes, page permissions, and built-in media chooser
  checks did not yield a new exploitable issue in the independent verification.

## Original analysis validation and limits

- `just check` passed: Ruff, mypy, and the full Python suite; 2,536 tests collected,
  with total Python statement/branch coverage reported as 100%.
- `npm --prefix javascript audit --json`: zero reported vulnerabilities.
- Exported locked runtime dependencies, including extras, and audited them with
  `pip-audit==2.10.1 --no-deps --disable-pip --strict`: no known vulnerabilities
  reported for the active platform/Python marker selection.
- Five focused reproduction cases passed in temporary files/databases; the
  reviewers removed those artifacts. They are not committed regression tests.
- No live-site penetration testing, browser fuzzing, load testing, deployment
  configuration assessment, or audit of arbitrary host authentication backends,
  custom block implementations, or storage implementations was performed.
  Dependency audit results are a point-in-time advisory check, not proof that
  dependencies are vulnerability-free.
- The original analysis added only this review record and its backlog index.
  The subsequent fixes update the comments and transcript documentation and
  the current release notes in `docs/releases/0.2.65.rst`.

## Implementation validation and independent review (2026-09-08)

- Two implementation subagents repaired the confirmed issues; the driver
  independently ran `just check`: 2,614 passed, one PostgreSQL-only row-lock
  test skipped under SQLite, and 100% Python statement/branch coverage.
- The Sphinx HTML documentation build passed without warnings.
- Claude Code `claude-opus-5`, effort `xhigh`, first review: one Warning
  (backlog still listing implemented work) and three Suggestions. No bundle
  omissions, truncations, redactions, or forbidden tool use were reported.
- Accepted repairs: narrow the backlog to the deferred hardening observations;
  exercise the transcript permission filter through admin search with an allowed
  result; identify comment endpoints by URL name in regression assertions.
- The author-action suggestion was checked against the existing source and
  recorded above as a separate policy decision; it did not invalidate the
  creation/preview fix. No application code changed in this repair round.
- Those repairs were applied and revalidated: the focused admin-media suite
  passed 34 tests and the comment page-access suite passed 56. A fresh
  `just check` passed with 2,616 tests passed, one PostgreSQL-only skip, and 100%
  Python statement/branch coverage.
- Opus 5 focused re-review: zero Critical/Warning findings and two Suggestions.
  The original backlog Warning was resolved. The reviewer requested a permitted
  nonmatching search result to distinguish searched from unsearched listings,
  and recording the post-repair validation above. Both suggestions were applied.
  This review also had no omissions, truncations, redactions, or forbidden
  tool use.
- The loop stopped after two valid reviews at diminishing returns: all accepted
  required findings were repaired and independently re-reviewed. The last delta
  adds only a search-test control and completes this evidence record; no
  application code changed after the first review. Another model pass would
  mostly recheck a small assertion and bookkeeping. This is an adjudicated
  advisory closure, not a `CLEAN` verdict. The separate author-action policy
  observation remains explicitly tracked above.
- Final validation after the search-test refinement: `just check` passed
  (2,616 passed, one PostgreSQL-only skip, 100% Python statement/branch
  coverage; Ruff and mypy passed). No application fixes or review findings
  remain outstanding within the confirmed two-issue scope.
