# Editor API rich-text sanitization

Status: implemented in 0.2.65 (unreleased); review cycle complete with advisory suggestions only.

## Root cause and independent analysis

`RichTextBlock.clean()` runs field validation, not the Draftail widget's
ContentState-to-HTML conversion. The editor API called only the former and
therefore stored scripts, event handlers, and unsafe link schemes unchanged.
Normal rich-text rendering trusts that stored HTML. Authenticated callers with
Wagtail admin access and content permissions could inject scripts into drafts
and published pages. Previews can expose drafts before publication.

Claude Code `claude-opus-5` independently confirmed this on 2026-09-07 against
the API source and installed Wagtail 7.3.2. Its consultation identified the
missing conversion step, nested custom rich-text ingress, malformed HTML
conversion errors, feature configuration, misleading documentation, and the
separate risk from historical revisions. A local malicious-input regression
fails before the fix.

## Plan and decisions

1. Use Wagtail's maintained `ContentstateConverter` to rebuild accepted HTML
   from supported rich-text features, then run normal block validation.
   Resolve explicit block features, editor options, and registry defaults in
   that order, including an explicitly empty feature list.
2. Instantiate converters per operation: their HTML parser is mutable and must
   not be shared across concurrent requests. Do not cache parser instances.
3. Retain supplied ContentState block keys so Wagtail rich-text comment anchors
   survive a round trip. Remove only generated keys before export: this avoids
   random keys on repeated equivalent writes without bypassing HTML escaping
   or URL filtering.
4. Apply conversion recursively to RichTextBlock leaves in configured
   StructBlock, ListBlock, and StreamBlock values. Preserve list/stream IDs.
   Reject RawHTMLBlock input at the top level or inside those containers.
   Other custom containers must sanitize their own HTML. Site-defined rendering and custom converters
   remain trusted application code, not something generic sanitization can
   make safe.
5. Reject inline embed markup and exclude image/oEmbed features from API rich text. Clients use the
   existing structured media blocks with permission/probe checks. Conversion
   must not introduce unchecked media lookup or remote provider fetches.
   Preserve supported page/document links and ordinary prose formatting.
6. Map expected malformed-input conversion failures to field-specific 400
   errors with a generic message and an operator-visible log. Configuration
   and infrastructure failures propagate. Keep accumulating errors across
   blocks. Never fall back to storing the original HTML.
7. Cover malicious and benign HTML, features, nested blocks, validation,
   create/update for posts and episodes, saved revisions, previews, and public
   rendering. Run `just check` and relevant supported-Wagtail checks, then
   fresh Opus 5 reviews until further rounds add no material value.
8. Correct API docs, release notes, and the earlier editing API planning
   record. Existing rows, omitted PATCH sections, unsupported placeholders,
   historical revisions, and non-API writes are not automatically rewritten.

## Follow-up

Provide read-only audit tooling for existing content and revisions separately.
Normalization differences alone are not proof of malicious content. Operators
must account for published bodies, drafts, and restorable revisions before
re-enabling an API that was blocked as a mitigation.

## Verification

- `just check`: passes, including 2,434 tests (2 expected skips) and 100%
  statement/branch coverage.
- Full tox suites: Python 3.11 / Django 5.2 / Wagtail 7.0 and Python 3.14 /
  Django 6.0 / Wagtail 8.0 pass.
- Sphinx HTML build and `git diff --check` pass.
- A stale, ignored local `uv.lock` initially pinned django-stubs 5.2.2 and
  mypy 1.17.0, producing the same 28 errors on clean HEAD and the patch.
  Refreshing those development tools (django-stubs 6.1.0, mypy 2.3.1) fixed
  the environment; runtime dependency versions and tracked requirements did
  not change.
- Bootstrap5 rendering and homepage/python-podcast feature/custom-block
  usage were inspected; no sibling change is needed. `../cast-vue` is absent.

## Implementation review dispositions

Opus 5 round 1 returned four Warnings and two Suggestions, with no skipped or
redacted evidence. All four Warnings were accepted:

- Narrow the raw-HTML rejection guarantee to standard containers and explicitly
  assign other custom containers to site validation. A hypothetical future
  change to the library-owned paragraph schema is not a currently reachable
  input path; built-in names cannot be overridden by the custom-block setting.
- Narrow conversion exception handling, resolve configuration outside the
  input-error guard, log expected failures, and let infrastructure errors
  propagate. Regression tests distinguish these cases.
- Accumulate sanitizer errors with preceding and subsequent section errors.
- Reject inline embeds on submission so GET-to-PATCH cannot silently delete
  admin-authored media. Test rejected writes and preservation of omitted
  sections and revision counts.

The formatting/comment-anchor Suggestion was accepted: document feature loss
and preserve supplied comment keys while still dropping generated keys.
The performance Suggestion was partially accepted by constructing the paragraph
block once per section. Per-operation converter caching is deferred: there is
no measured bottleneck, and threading a mutable feature-keyed cache through
recursive values would add complexity to the security boundary. Each converter
remains local to one rich-text conversion.

Round 2 reviews these repairs and directly coupled risks, rather than reopening
unrelated API behavior.

Opus 5 round 2 returned one Warning and two Suggestions, with no skipped or
redacted evidence:

- Accepted the missing-target-link test gap. New post/episode create, PATCH,
  and preview tests use deleted page/document targets. Wagtail already handles
  these misses and preserves the reference IDs, so no broader exception catch
  was needed.
- Accepted a distinct `inline_embed` validation code for client handling;
  documented it and updated the regressions.
- Declined the hypothetical change to EditorValidationError inheritance: its
  current APIException base is not one of the mapped input exceptions, and
  exact-message/code tests already guard inline-embed rejection. Adding a
  speculative exception clause would not improve present behavior.
- A local check found that the custom-block conversion envelope could still
  catch a configuration TypeError from sanitizer initialization. Initialization
  now raises ImproperlyConfigured with the original cause, which cannot be
  mistaken for author input by that envelope. Tests exercise both the direct
  helper and the actual custom-block conversion path.

Round 3 verifies the deleted-reference tests, initialization error propagation,
and dedicated inline-embed code, with the prior repair baseline retained.

Opus 5 round 3 returned only three Suggestions (zero Critical/Warning findings):

- Record unsupported placeholders for existing inline-media paragraphs as a
  separate read/preservation enhancement. The current explicit rejection is
  safe and documented; a preservation path needs its own anti-forgery contract.
- Record aggregation of multiple nested sanitizer errors within one custom
  container as follow-up. Current field-specific rejection is safe; this would
  reduce client repair round trips rather than close a remaining XSS path.
- Add an assertion through `author_blocks_to_section` under actual editor
  OPTIONS, proving the built-in paragraph respects configured blockquote/code
  features. Accepted and added to the existing feature-resolution regression.

The two deferred authoring enhancements are tracked in `BACKLOG.md`. Stop the
review loop at diminishing returns: all accepted Critical/Warning findings
from the consultation and implementation reviews are resolved; the remaining
items are optional authoring improvements. This is an advisory outcome, not a
`CLEAN` verdict. The final test-only assertion is checked locally without an
additional broad review round.
