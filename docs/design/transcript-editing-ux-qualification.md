# Transcript editing: qualification and clerk handoff

Scope: slices 1, 2, 3, 4 and 7 of `transcript-editing-ux.md`, based on
`develop` at `f5863de9`. Park all slices on
`codex-q/cast-transcript-editing-a`; do not merge. Slices 5, 6, 8, 9 and 10
remain deferred. No schema change, public theme change, new infrastructure or
GitHub Actions run is required. Cross-family review is pending outside the
Codex sandbox; no Claude command was run here.

The episode panel deliberately uses the current materialized mapping rows for
voice counts. File saves/import synchronize them. It opens **zero** transcript
artifacts, so the file-read budget cannot be exhausted by opening the episode
editor. Preview and unnamed-passage counts belong to deferred slice 6.

## Local checks

Run from the repository root:

```sh
just check
uv run tox -p 2 -e py311-django52-wagtail70,py315-django61-wagtail81
npm --prefix javascript ci
npm --prefix javascript test
npm --prefix javascript run typecheck
msgfmt --check src/cast/locale/de/LC_MESSAGES/django.po -o /tmp/cast-transcript-de.mo
```

Final local result: `just check` passed (Ruff, mypy, **5,144 passed,
38 skipped**, **100% branch coverage**). JavaScript: **226 passed**, TypeScript
passed. Both full tox environments, Wagtail 7.0 / Django 5.2 / Python 3.11
and Wagtail 8.1 / Django 6.1 / Python 3.15, passed (including the 8.1
experimental-settings follow-up). Catalogue validation passed with pre-existing placeholder-header warnings.
The opt-in browser and PostgreSQL qualifications remain blocked as described below.

The segment regression uses 1,200 passages, asserts HTML below 300 kB, at most
50 decision fields, a POST below 100 fields, and preservation of decisions from
page 1 when saving page 2. A counting-storage regression proves that opening the
episode editor does not open transcript files. The list query regression compares
one and twenty transcripts. The browser's Voxhelm stub also runs through the
real submission/completion/import path in an ordinary pytest regression.
The polling tests execute the shipped inline script with fake time: completion,
failure, request error, hidden tab, in-flight response and 30-minute timeout.

## Checks the clerk must run outside the sandbox

The opt-in Chromium journey fails at browser launch in the sandbox:
`TargetClosedError`, process SIGABRT and `kill EPERM`. No browser interaction or
new before/after screenshot was qualified here. On the same Mac, run:

```sh
CAST_RUN_BROWSER=1 \
CAST_BROWSER_EXECUTABLE='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' \
uv run python -m pytest tests/transcript_admin_browser_test.py -q
```

On another machine set `CAST_BROWSER_EXECUTABLE` to its Chromium executable, or
omit it after installing Playwright Chromium. The journey covers the episode
panel, upload audio preselection, title/back navigation, save staying on the
editor, 1,200-passage pagination/save, mapping a host, confirmation, real stubbed
regeneration, an empty stale choice and preserving that choice on save. It fails
on JavaScript page errors and browser console errors. Capture the changed episode
panel for the review note; the original screenshot is
`transcript-editing-ux/01-episode-edit-draft.png`.

PostgreSQL qualification could not connect to `127.0.0.1:5432` (Connection
refused). With a running disposable test database and the usual
`CAST_TEST_DB`, `CAST_TEST_DB_USER`, `CAST_TEST_DB_PASSWORD`,
`CAST_TEST_DB_HOST`, `CAST_TEST_DB_PORT` environment values, run:

```sh
uv run tox -e postgres-wagtail81
```

For just the transcript concurrency checks, the exact focused command is:

```sh
CAST_TEST_DB_ENGINE=django.db.backends.postgresql \
uv run --with 'psycopg[binary]>=3.3,<4' python -m pytest \
  -p tests.postgres_check --create-db -x -q \
  tests/transcripts/editor_concurrency_test.py \
  tests/transcripts/glossary_concurrency_test.py
```

After the blocked checks and external review, the coordinator decides integration.
Do not rely on GitHub Actions and do not merge automatically from this handoff.
