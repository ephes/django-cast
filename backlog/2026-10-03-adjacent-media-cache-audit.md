# Adjacent media response-cache audit

Date: 2026-10-03

Status: Proven raw transcript/chapter cache-admission findings implemented and
independently reviewed within the scope below. Integration, deployment and
owner acceptance remain pending.

Base: `fed4b4d55d0207f39134cb5c61aa22cee80c9c51`, the completed
[Podlove player response audit](2026-10-03-security-audit.md). Its application
change and regression cases remain unchanged.

## Scope and threat model

Only adjacent raw Podlove JSON, PodcastIndex JSON, WebVTT, chapters, and HTML
transcript views (bare ID, explicit post, canonical slug, and episode-ID redirect)
were inspected. Synthetic local fixtures use a unique transcript/chapter text
marker, actual Django full-site cache middleware, session authentication, and
Wagtail direct/inherited group or login restrictions. No live services or real
personal data were accessed.

Threats considered: a formerly permitted reader reusing the same session after
access revocation; anonymous reuse of another reader's response; a previously
public page becoming restricted; and a restricted page becoming public.

## Proven findings and pre-fix evidence

Medium: the raw Podlove JSON, PodcastIndex JSON, WebVTT, and chapters views
admit request-specific private output to the host's full-site cache. A group
member receives a 200 containing the synthetic marker, then loses the permitted
group. Repeating the same URL/session returns cached 200 and the private marker.
Clearing the cache makes that identical session receive 404. Both direct and
inherited group restrictions reproduce for all four views. Anonymous requests
from a separate client receive 404 before revocation; this is a demonstrated
same-session revocation bypass, not cross-user disclosure.

Before repair, on the unchanged base application source:

```text
uv run pytest tests/adjacent_media_cache_security_test.py -q
8 failed, 6 passed in 0.97s
```

At that stage the file contained only the direct/inherited group-revocation
matrix. Each of the eight raw-view failures was cached 200 versus fresh 404,
after asserting the original successful response contained the marker and that
an anonymous client was denied. Header assertions followed the boundary checks.
After adding transition/negative controls, select the same reproduction with:

```text
uv run pytest tests/adjacent_media_cache_security_test.py -k group_revocation -q
```

The six HTML cases passed access revocation on the base implementation. An
initial overly broad assertion about private headers made those cases fail for
missing headers; they were not cache exploits. The implementation was narrowed
before delivery to the eight proved raw-view cases.

## Repair

The raw views retain the page returned by their existing authorization helpers.
A small shared response helper adds `Cache-Control: private, no-store` and
`Vary: Cookie, Authorization` when that granting page is draft or restricted.
It leaves unrestricted public output unchanged. The PodcastIndex empty-object
success path uses the same helper. HTML application code, URL contracts,
authorization decisions, response bodies, dependency resolution, and completed
Podlove player cases remain unchanged.

Purge pre-upgrade cache entries on deployment: headers cannot evict already
stored responses. Previously unrestricted public output also retains its normal
cache lifetime when restrictions are added or a page is unpublished. Immediate
removal requires purging affected media URLs. This slice does not implement
cache invalidation or promise immediate revocation of previously public output.

## Negative evidence and limits

- Anonymous/authenticated separation held for every tested endpoint with direct
  and inherited group restrictions in this locked Django 6.1.1 environment.
- Public raw media requests hit the full-site cache: an authorization spy is
  called once across two requests. Adding a login restriction after priming
  preserves cached public 200; purging causes 404. This is the retained public
  cache lifetime behavior, not newly admitted private content.
- Restricted raw responses are not stored after repair, and removing a login
  restriction allows an anonymous public 200 with the marker.
- Standard HTML transcript templates set CSRF cookies. Django 6.1.1's cache
  middleware skips cookie-setting responses varying on Cookie; authorization
  therefore runs again for repeated HTML requests. Group revocation gives 404
  for bare IDs, explicit post anchors, canonical slugs, and the episode redirect
  followed to its HTML destination. Public HTML requests also reauthorize;
  newly restricted pages return 404 without purging. No HTML response policy
  change was justified by these observations.
- These HTML results are specific to the tested built-in template/settings and
  locked version. Custom theme templates, alternate middleware/authentication,
  and other supported Django versions were not audited. Password changes or
  changes to Wagtail's passed-password session policy were not modeled; no new
  claims about those semantics are made.
- No load tests, browser fuzzing, deployment actions, shared proxy testing,
  storage backend audits, or dependency audits were performed. Direct media
  storage URLs and public transcript artifacts retain their documented storage
  semantics. This bounded audit is not a comprehensive clean verdict.

## Validation

- Final adjacent suite: `uv run pytest tests/adjacent_media_cache_security_test.py -q`:
  29 passed in 1.53 seconds.
- Focused compatibility suite:
  `uv run pytest tests/adjacent_media_cache_security_test.py tests/endpoint_authorization_test.py tests/chapters_view_test.py tests/transcripts/json_views_test.py tests/transcripts/podcastindex_webvtt_test.py tests/transcripts/html_views_test.py -q`:
  116 passed in 3.42 seconds.
- `just check` passed: Ruff and mypy (163 source files), full Python suite
  (3,101 passed; five existing skips: one inactive Wagtail v3 experiment and
  four PostgreSQL-only row-lock cases under SQLite), and 100% statement/branch
  coverage (13,609 statements, 3,982 branches, zero missed/partial branches).
- `uv run sphinx-build -W -b html docs /tmp/cast-adjacent-media-audit-docs`:
  succeeded without warnings.
- `uv run pre-commit run --files` for all changed/new files: all applicable
  hooks passed; YAML/TOML/HTML hooks skipped when there were no matching files.
- `git diff --check`: passed. The worktree's existing isolated virtualenv and
  ignored copied lock were used; no dependency resolution or original checkout
  changes were made.

## Independent verification and review

The coordinator independently ran the corrected revocation matrix in a temporary
checkout of committed `fed4b4d5`: eight raw-view failures were cached 200 versus
fresh 404; six HTML negative cases passed (15 other cases deselected). No
header-only failure was counted as a reproduced disclosure. The patched tree's
independent `UV_FROZEN=1 just check` passed Ruff, mypy, 3,101 tests with the five
documented skips and 100% statement/branch coverage. Applicable pre-commit hooks
passed for all nine changed/new files.

The installed supervised `codex-review-loop` completed with zero findings and
`CLEAN (scoped)` using OpenAI `gpt-6.1-sol` at **high** effort. Its session-record
audit proved the model/effort, no forbidden tools were reported, and the review
copy was removed. Same-family independent review was explicitly authorized. No
Anthropic or fallback reviewer was used.

There were no file omissions or truncations. Three synthetic test-password
values were redacted in the starting bundle; the repository copy excluded no
files. Those values do not affect the exercised cache/session behavior. The
result is clean within this authored slice, not a whole-project or cross-version
security claim. No material finding remains in the gate; another round would
add little demonstrated risk reduction, so review stops after this valid round.

For integration, apply the earlier `fed4b4d5` Podlove commit first, then this
adjacent commit, preserving both audit records and current release notes. Run
the required gate against the final combined checkout. Before deploying, purge
existing application/downstream entries for the affected Podlove player, raw
transcript JSON/WebVTT and chapter URLs. Restricting previously public content
also requires purging those URLs when immediate removal is needed. No merge,
publish or deployment was performed by this slice.
