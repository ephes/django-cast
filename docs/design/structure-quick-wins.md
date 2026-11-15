# Structure quick wins

Date: 2026-11-15

Status: S1 implemented on the parked implementation branch; external review and integration remain pending.
S2–S8 remain planned. Owner overrides (2026-11-15): S1 uses soupsieve >=4.1 (requiring Python >=3.11.5),
manual-only workflows and local checks instead of paid Actions, and branch parking without Claude invocation or merge.
The measurements below describe the pre-implementation tree.

Original design status: Review of `develop` at commit `831a2929`; file and line references were re-checked
against `f5863de9` (three commits later, CI still red there), measurements were not repeated. The remaining slices are not implemented;
the slices under "Implementation plan" are the work. This note does not replace
[backlog/2026-09-15-architecture-review.md](../../backlog/2026-09-15-architecture-review.md): that review lists the
structural findings (D1–D12, V1–V12, X1–X10, T1–T12) and stays the reference for the larger seams. This note asks a
narrower question: which changes are **easy** and bring **a lot**, measured on today's tree.

Location: `BACKLOG.md:43` puts design documents that precede a larger change in `docs/design/`, linked from
`BACKLOG.md`; `AGENTS.md:72-73` still names only `backlog/` (S5 aligns it). Sphinx does not read `.md` files here,
so the docs build is unaffected.

## Goal and non-goals

Goal: a ranked list of improvements to django-cast that each fit in one 30–90 minute slice, with evidence and
acceptance criteria, biggest benefit first.

Non-goals:

- No new infrastructure dependency (no Redis, no service, no new CI provider). Every slice works with what the
  repo already uses: uv, just, pytest, tox, GitHub Actions.
- No new abstraction layers and no module moves that change import paths (see "Not worth doing").
- No behavior change for site visitors or editors. Four slices change what is shipped, each in a small way with a
  release-notes entry: S1 (a higher `soupsieve` floor in the package metadata), S4 (how `cast.__version__` is
  computed), S7 (removes one runtime dependency and one unused module) and S6 (one dev-only view reads a setting
  through the registry, same value; possibly a few lines rewritten by `django-upgrade`).
- No performance work: the measurements below show none is needed.

## Method

Read the whole tree (33.6k lines of Python under `src/cast` without migrations, 65.2k lines under `tests/`, 208 test
modules, 91 cast migrations, 105 templates), the two earlier architecture reviews, `BACKLOG.md`, the CI workflow and
its recent runs, and what the consumer sites and themes import. Measured on an Apple-silicon Mac with Python 3.15,
Django/Wagtail as resolved by `uv sync`, SQLite.

## Measurements

### Test suite

| Run | Result | Wall time |
| --- | --- | --- |
| `uv run pytest` (serial, as the CI `python-compatibility` jobs run it) | 5077 passed, 37 skipped | 150 s |
| `uv run coverage run -m pytest` (serial, what `just test` runs) | 5077 passed, 100 % | 140 s |
| `uv run --with pytest-xdist pytest -n 4` | 5077 passed, 37 skipped | 44 s |
| `uv run --with pytest-xdist pytest -n 4 --cov --cov-report=` then `coverage report` | 5077 passed, 100 % (17750 statements, 5430 branches) | 52 s |
| same as row 3, the two slowest tests deselected | 5075 passed | 42 s |

Rows 1, 2, 4 and 5 are single runs. The two serial numbers are within run-to-run noise of each other (the plain
run shared the machine with a short second job); the point is the factor of about three between serial and
parallel, not the 10 s between rows 1 and 2. Five parallel runs (three random orders, two fixed; 44–62 s, the
slower ones built their databases from scratch) all passed without a single change to the tree.
pytest-django gives every worker its own database file (`tests/test_database.sqlite3_gw0` …). Two things are
missing, both found by spike:

- The stale-schema protection in `tests/conftest.py:56-177` does not reach the worker databases.
  `pytest_configure` runs before pytest-django adds the worker suffix, so every worker checks the unsuffixed file,
  while `pytest_sessionfinish` writes a `…_gw0.fingerprint` that nothing reads. Spike: add a model field, run
  `-n 4` again on two modules: 18 failed, 3 errors (the reused worker databases lack the column). With three lines
  in `_reusable_test_db_path()` (append `_<PYTEST_XDIST_WORKER>` unless the name already ends with it) the same
  sequence passes: fresh, reused, field added, reused, field removed, 80 passed each time.
- `.gitignore:82` and `:89-91` match `tests/*.sqlite3` and the unsuffixed file with its journal and fingerprint,
  not the `_gw*` files, which therefore show up as untracked.

The two slowest tests take 19 s of the 150 s serial run
(`tests/benchmark_typeahead_script_test.py::test_command_line_seeds_a_fresh_database_and_refuses_a_foreign_one`
10.3 s, `tests/public_media_queries_test.py::test_over_one_thousand_audio_anchors_preserve_authorization_and_speaker_privacy`
9.0 s). Under four workers they cost one to two seconds of wall time, so marking or rewriting them is not worth it.

Other gates: `ruff check .` 0.06 s, `mypy` 1.5 s (warm cache). The test run is the whole feedback loop.

### Continuous integration

`develop` has been red for the last 10 CI runs (13 by `f5863de9`), since 2026-11-12 (last green run: 2026-11-12 10:49 UTC). Run
`43680039841` on `831a2929` fails for two independent reasons:

1. All six `dependency-compatibility` jobs stop at collection after about 10 seconds:
   `ModuleNotFoundError: No module named 'playwright'` from `tests/comment_browser_test.py:7`. The module was added on
   2026-11-14 (commit `a248d895`) and imports Playwright unconditionally; its only test is opt-in
   (`CAST_RUN_BROWSER=1`, line 13). `uv sync` installs Playwright from the `dev` group (`pyproject.toml:94`), so
   `just check` passes locally, but the tox environments install the seven packages hand-listed in `tox.ini:28-34`,
   which do not include it. `python-quality` still runs the suite on Wagtail 8.0.1 and 8.1 with the newest Django,
   but Django 5.2 and 6.0 and Wagtail 7.x have not been tested since that commit, and the full matrix (`uv run tox`, a release step in
   `docs/release.rst:68`, and `just tox`) fails the same way. It is the second time: commit `8bd243d0` (2026-11-09) fixed the same
   class of defect in `tests/scripts/playwright_utils_test.py` (there the import was indirect, through
   `scripts/playwright_utils.py`), five days before it came back in a new module. The failure is reproducible
   locally in 8.6 s: `pytest --collect-only -q` in an isolated environment without the dev-only packages reports
   `ERROR tests/comment_browser_test.py` and "5065 tests collected, 1 error".
2. `dependency-audit-advisory-floors` fails: `pip-audit` reports four advisories for `soupsieve==2.9.0`
   (one fixed in 2.10.0, two in 3.0.2, one only in 4.0.0), the floor declared in `pyproject.toml:58` and audited in
   `.github/workflows/workflow.yml:222`. `uv sync` already resolves `soupsieve 4.1.1`, so only the declared floor is
   stale.

Per job the full-suite jobs take 4.5–5.8 minutes (`python-quality` ×2, `python-compatibility` ×4); the workflow has
14 jobs that run the suite or a tox environment.

Why this matters more than its size: both consumer sites install django-cast straight from the `develop` branch
(`django-cast = { git = "https://github.com/ephes/django-cast", branch = "develop" }` in the `pyproject.toml` of
`homepage` and `python-podcast`). `develop` is the release channel, and ten merges (35 commits) landed on it while it
was red.

### Public pages: queries and render time

Test client, cache cleared before each request, content generated with `cast.devdata.generate_blog_with_media`
(image, gallery, video, audio per post). `n` is the number of posts and the page size.

| Page | Queries n=5 | Queries n=20 | Best of 5, n=5 | Best of 5, n=20 | SQL time |
| --- | --- | --- | --- | --- | --- |
| Blog index | 27 | 27 | 16 ms | 30 ms | 1.4 ms |
| Post detail | 31 | 31 | 7 ms | 8 ms | 0.5 ms |
| Blog RSS feed | 23 | 23 | 12 ms | 30 ms | 0.7 ms |
| Podcast index | 27 | 27 | 18 ms | 34 ms | 1.5 ms |
| Episode detail | 34 | 34 | 9 ms | 9 ms | 0.8 ms |
| Podcast RSS feed | 26 | 26 | 17 ms | 37 ms | 1.1 ms |

Query counts do not grow with the number of posts: there is no N+1 on any key page. With
`CAST_REPOSITORY = "django"` the index pages need 36 instead of 27 queries and the same time (17 ms / 31 ms), so the
serialize/deserialize round trip of the `"default"` repository (finding D5 of the September review) saves nine
sub-millisecond queries and no measurable time.

### Startup, wheel, frontend

- `django.setup()` 1.0–1.3 s plus 0.45 s to load the URLconf, 1910 modules. The time is Django, Wagtail, DRF and
  `ninja` (pulled in by `wagtail.admin.api.v3`); the largest cast modules cost 2–8 ms each.
  `cast.views.styleguide` and `cast.devdata` are imported in production (`urls.py:14`, `views/styleguide.py:33`,
  finding X6) and together cost about 7 ms.
- Wheel: 879 KiB, 493 files. Static files 213 KiB compressed, transcripts package 120 KiB (two 10k-line common-word
  lists), migrations 44 KiB.
- Shipped Vite bundles: 70 KiB in total (`customPlayer` 35.5 KiB JS + 14.9 KiB CSS, `main` 9.9 KiB, `podlovePlayer`
  10.0 KiB, a shared chunk and the manifest).
- A full `migrate` of all apps on an empty SQLite file: 7.5 s.

### Growth since the last tag

`0.2.67` was tagged and published to PyPI on 2026-10-12. Since then: 204 commits, `src/cast` Python from 26.7k to
33.6k lines (+26 %), tests from 47.7k to 65.2k lines (+37 %), `tests/conftest.py` from 1136 to 1199 lines. Pending
release notes are split over two files: `docs/releases/0.2.68.rst` (25 entries, titled "(unreleased)") and
`docs/releases/unreleased.rst` (115 entries, 582 lines), although the rule in `AGENTS.md:58` allows `unreleased.rst`
only when the current version is already tagged, and `0.2.68` is not. At least one entry exists in both files
(`0.2.68.rst:70-74` and `unreleased.rst:440-444`, the Voxhelm credential pair). The counts are top-level bullets;
two of them in `unreleased.rst` are groups with nested bullets ("Security hardening:" at line 113 with five
sub-bullets, the editor-API endpoints at line 445 with four). Neither file has section headings; the
operator-relevant "Upgrade action" paragraphs sit at `unreleased.rst:130` and `:143`, and five more entries say
"consumers must adopt …" somewhere in the middle of the list.

## Current state: findings with evidence

Ordered as in the ranking below.

**F1. The trunk is red and nobody is told.** See "Continuous integration". Root causes beyond the two one-line
defects: nothing in `just check` notices a test module that needs a dev-only package; test dependencies are
declared twice (`pyproject.toml:84-109` and `tox.ini:28-34`) and have drifted; and the
delivery rule in `AGENTS.md` ("do not consider a task done until `just check` passes") says nothing about the CI
result on `develop`, so a worker who merges never looks at it.

**F2. The feedback loop is 2.5 minutes and could be 50 seconds.** `just test` (`justfile:56-58`) and the CI jobs
(`workflow.yml:117`, `:288`) run serially. `pytest-cov` is already a dev dependency (`pyproject.toml:97`);
`pytest-xdist` is not. `just check` is the gate every change must pass, often several times per slice.

**F3. 140 unsorted release-note entries in two files.** See "Growth since the last tag". The reader who needs them
most (the owner deploying `homepage` or `python-podcast` from `develop`) has to read about 770 lines to find the two upgrade
actions and the migrations behind them (0090 refuses to run while `cast_file` has rows, 0088 drops an admin field
whose value must be moved to deployment configuration first).

**F4. Three places hold the version number.** `pyproject.toml:3`, `src/cast/__init__.py:5` and `docs/conf.py:12`;
`docs/release.rst` lists the three files twice (bump for release, bump after release).

**F5. `BACKLOG.md` opens with a done list.** The file says "Do not keep a separate done list" (`BACKLOG.md:46`), but
its first 81 lines hold 15 records of implemented work (scout rounds 81–99, audits, CI repairs: `BACKLOG.md:5-39` and
`:50-81`); the first open item is at line 85. Five of the records still say that review, integration or acceptance
is pending, although the merge commits for rounds 90, 91, 96, 97 and 99 are on `develop` (`8f74fed2`, `97a62a5f`, `617476e1`,
`ec06c0f8`, `831a2929`), so the file no longer tells open from done. Ten of the 65 notes in `backlog/` are scout-round handoff records. Repo-root leftovers are still
there: `docs_inventory.md` (describes `docs/howto/` and a `features.rst` that no longer exist, last touched
2025-07-12), `django-cast-example.ps1` (2020), `commands.py` (175 lines, bootstraps itself with `pip install`; used by
`Procfile:2` for JupyterLab and mentioned in `docs/operations/backup.rst:25`), `notebooks/` (about 50 debug notebooks, last touched 2025-07-05).

**F6. Tooling says one thing and does another.**

- The Vite manifest post-processing exists twice with different shell semantics: `justfile:150-157` and
  `workflow.yml:61-72` (finding T10, still open).
- `justfile:109`, `:116` and `workflow.yml:256` delete `docs/cast.api.rst` and four other apidoc files that nothing
  generates (`docs/conf.py:17` has `extensions = []`).
- `.pre-commit-config.yaml:18-22` runs `django-upgrade --target-version 4.2` while the package requires Django
  5.2.17 or newer; lines 34–65 are a commented-out mypy hook pinned to mypy 1.11.2.
- `AGENTS.md:25` says Ruff checks `E,W,F,I,B,UP,DJ`; `pyproject.toml:131` selects `E4, E7, E9, F, I`.
- The pre-commit hooks are not part of CI or of `just check`, and the tree has drifted from them:
  `pre-commit run --all-files` reindents eight templates (djhtml) and rewrites three Python files.
- `tests/test_heading_migration.py` is the one `test_*.py` module next to 208 `*_test.py` modules, and
  `python_files` is not pinned (finding T12, still open).

**F7. Test-only and dev-only pieces in the shipped package.**

- `src/cast/runner.py` is referenced only by `tests/settings.py:65` and excluded from coverage
  (`pyproject.toml:179`) (finding T12, still open).
- `python-dateutil` is a runtime dependency of every install (`pyproject.toml:54`) for one line in the dev-only
  styleguide (`views/styleguide.py:410`).

**F8. Some settings are read outside the registry.** `CAST_SETTING_REGISTRY` (`appsettings.py:73-144`) holds 55 settings and
`docs/reference/settings.rst` documents every `CAST_*` name used in `src/` (checked by script: no gaps). Still
outside: `CAST_ENABLE_DEV_TOOLS` and `CAST_ENABLE_STYLEGUIDE` (`dev_tools.py:33-44`), the `CAST_VOXHELM_*` family
(`setting_resolution.py:32`, `voxhelm/settings.py:68`, `models/transcript_generation.py:27`,
`models/transcript_glossary.py:46`) and one `getattr(settings, "POST_LIST_PAGINATION", 5)` in
`views/styleguide.py:609` (finding X7, still open). The first two groups have reasons to stay outside (see "Not worth doing");
only the styleguide lookup is a plain leftover, and S6 fixes it in passing.

**F9. The test tree is flat and partly named after work rounds.** 124 test modules sit directly in `tests/`
(84 more in eight subdirectories). Whole families are spread over the root without a package of their own: 11 comment modules
(`comment_*_test.py`, `comments_test.py`, `cast_comments_internals_test.py`), 8 feed modules, 12 `media_*` modules;
7 voice-reference/known-speaker modules sit in the root although `tests/transcripts/` exists. Eight modules are named after the scout round that produced them
(`tests/round92_glossary_test.py`, `round92_renditions_test.py`, `round92_video_test.py`,
`tests/voxhelm/round88_test.py`, `tests/content/scout87_identities_test.py`, `scout87_media_test.py`,
`scout87_nested_test.py`, `tests/transcripts/scout87_samples_test.py`), which says nothing about what they test. 27 module-level import statements pull helpers out of
other `*_test.py` modules (for example `tests/comment_browser_test.py:9`).

Already fixed since the September review and therefore not planned here: the 33 file-level Ruff blankets (T1; zero
left, `ruff check --select F401,F811 src tests` is clean), the copied fixtures (T2), the import-sorting rule (X9),
the TypeScript gate (T4), per-session media roots (T6), the docs tree test (T9).

## Options considered

**A. Do the remaining structural seams now** (media ingestion service, transport-neutral converter, read-model
decision D5, fields-only models D2). High long-term value, but each is days of work with design decisions, and the
measurements show no user-visible problem that forces them. Rejected for this plan; they stay in the September
review.

**B. Consolidate the scout-round hardening code** (shared bounded-read helper for the two hand-rolled loops in
`models/transcript.py:286-299` and `transcripts/parsing.py:30-35`, one home for the four separate 10 MiB transcript
limits in `appsettings.py:16`, `transcripts/parsing.py:16-17` and `voxhelm/client.py:37`). The duplication is real
but small, the code was reviewed line by line days ago, and its tests pin exact byte counts and messages. Touching
it trades a little tidiness for re-review of security-relevant code. Rejected as a quick win.

**C. Fix the process and tooling around the code** (chosen). The largest costs found are not in the code: a red
trunk nobody sees, a feedback loop three times slower than necessary, and release notes nobody can read. All three
are cheap, need no design decisions, and pay off on every later change. Then a short tail of drift removal.

Reasons for C: it follows the owner's preference for simple changes without new infrastructure; it has the best
benefit per hour by a wide margin (see ranking); and it lowers the cost of the A-type work when that is picked up.

## Ranked improvements

Benefit: how much recurring cost or risk it removes. Effort: one slice of the stated length.

| Rank | Improvement | Benefit | Effort | Slice |
| --- | --- | --- | --- | --- |
| 1 | Green trunk again; test dependencies declared once; a local guard; "CI green" becomes part of done | Very high: 6 of 14 CI jobs test nothing today, and `develop` is what production installs | 60 min | S1 |
| 2 | Parallel test run by default (`-n 4`) | Very high: 140 s → 52 s on every `just check`; the six uv-based CI suite jobs get faster, the tox jobs stay as they are | 75 min | S2 |
| 3 | One release-notes file with upgrade actions first | High: the 0.2.68 upgrade becomes readable; removes a duplicated entry and a rule violation | 90 min | S3 |
| 4 | Single version source | Medium: release has two fewer manual edits, twice | 40 min | S4 |
| 5 | `BACKLOG.md` holds open work only; stale root files gone | Medium: planning file is usable again, less noise for every agent that reads it | 45 min | S5 |
| 6 | Tooling drift removed (one frontend build script, dead recipes, pre-commit, AGENTS) | Medium: one place to change the build, docs match reality | 60 min | S6 |
| 7 | Shipped surface trimmed (`runner.py`, `python-dateutil`) | Low–medium: one runtime dependency fewer for every install | 45 min | S7 |
| 8 | Test tree: topic names instead of round names, families into packages | Low–medium: discoverability; pure moves | 60 min | S8 |

## Not worth doing (now)

- **Performance work on public pages.** 23–34 queries per page (up to 36 with `CAST_REPOSITORY = "django"`),
  constant in page size, about 1 ms of SQL per page and about 1 ms of rendering per listed post. No N+1 to fix.
- **Import-time work / lazy dev URLs (X6).** Startup is 1.5 s of Django and Wagtail; the dev modules cost 7 ms.
  Moving them is a boundary question, not a speed-up.
- **Wheel or bundle size.** 879 KiB wheel, 70 KiB of Vite bundles. Removing the 185 KiB Bootstrap source map would
  save about 50 KiB compressed.
- **Squashing migrations.** 91 migrations, 7.5 s for a full migrate of all apps; squashing risks the data
  migrations (0078, 0084, 0088–0090) for no measurable gain.
- **Regrouping the 55 top-level modules into packages** (`cast/media/`, …). Consumer sites import internals by
  path (`cast.media_derivation`, `cast.player`, `cast.follow_links`, `cast.image_metadata`,
  `cast.models.repository.serialization`, `cast.devdata`), tests patch by dotted path, and `docs/architecture.rst`
  has a checked module tree. High churn, no behavior gain.
- **Moving `cast.devdata` out of the package (T7).** `python-podcast` imports five builders from it.
- **Marking or rewriting the slow tests.** They parallelize; see measurements.
- **Consolidating the hardening helpers (option B)** and **the read-model decision (D5)**: real, but not quick.
  D5 now has a number attached (nine queries, no time) that supports "drop the round trip" when it is taken up.
- **Completing the settings registry (X7) or guarding it with a test.** The two groups still outside have reasons:
  `dev_tools.py:18-46` needs to know which of two names is present and accepts non-bool values, and the Voxhelm
  names are resolved in layers with a credential-pair rule (`voxhelm/settings.py:61-72`); a registry entry would
  add an accessor that skips those layers. A guard test that is precise enough to be useful (literal and
  attribute access, prefixed and unprefixed names, an allowlist with reasons) costs more than the one stray lookup
  it would have caught.
- **Deduplicating the `TYPE_CHECKING` block in `appsettings.py:151-206`.** mypy needs the static declarations.
- **Widening Ruff to `B`/`UP`/`DJ` or mypy to `tests/`.** Useful, but a large mechanical diff that conflicts with
  every open branch; do it in a quiet week, not as a quick win.
- **A second cache or rate-limit backend, a task queue, a CI service.** Out of scope by the no-new-infrastructure
  rule.

## Chosen design in detail

### S1: green trunk, one list of test dependencies

- `tests/comment_browser_test.py`: replace the top-level import with
  `pytest.importorskip("playwright.sync_api")` and take `expect` and `sync_playwright` from the returned module.
  The call goes below the last import of the module (line 9), otherwise Ruff reports E402. The test stays opt-in
  and runs unchanged where Playwright is installed.
- A guard so that it cannot come back a third time. It covers module-level imports of any dev-only package,
  direct or through another module, which is the shape of both incidents: a
  recipe `just check-collect` runs
  `uv run --isolated --no-default-groups --group test --extra markdown pytest --collect-only -q` (an ephemeral
  environment with the project and the `test` group only; the shared `.venv` is not touched), and `just check`
  calls it before `just test`. It costs under ten seconds. It cannot see an import inside a function (collection only imports modules); for
  those a tox environment run stays the real check. `AGENTS.md:20` and `:54`, `docs/development.rst:608-610` and `:762` and the
  recipe comment at `justfile:49` list what `just check` runs and get the fourth step, together with the one exception: if `check-collect` fails only
  because the isolated environment cannot be built (no uv cache, no network), the other local recipes plus the local
  tox environments count, and the worker says so in the handoff.
- `pyproject.toml`: add a dependency group `test` with what a test run needs (`pytest`, `pytest-django`,
  `pytest-mock`, `pytest-randomly`, `pytest-cov`, `pytz`, `factory_boy`, `feedparser`, and `django-stubs-ext`,
  which `tests/settings.py:5` imports and which today arrives only as a transitive dependency) and make `dev` include it
  (`{include-group = "test"}`). The eight packages that are in `dev` today (`pyproject.toml:88-89`, `:96-101`)
  move, with their version specifiers, and are deleted from `dev`, so each test package is named once. `tox.ini`: replace the seven hand-listed lines with `dependency_groups = test` in
  `[testenv]`; the Django/Wagtail factor lines stay. The CI pin `tox==4.61.2` with `tox-uv==1.36.0` supports
  `dependency_groups`. Sections derived from `[testenv]` inherit the key: `postgres` and `fast` should (they run tests);
  `[testenv:migrations-{oldest,latest}]` keeps it too (it runs only `manage.py migrate`, but that imports
  `tests.settings`); `[testenv:cleanup]` and `[testenv:pre-commit]` get an explicit empty `dependency_groups =`.
- Raise the `soupsieve` floor to `>=4.1` in `pyproject.toml` and audit exactly 4.1 via `scripts/advisory-floors.txt` locally and in the manual workflow, with
  boundary and audit-alignment tests in `tests/dependency_policy_test.py`. This supersedes the original 4.0.0
  proposal at the owner's request. Soup Sieve 4.1 requires Python >=3.11.5, so align `requires-python` too.
  Check that the oldest supported branch (`py311-django52-wagtail70`) still resolves and passes.
- `AGENTS.md`, under "Commit & Pull Request Guidelines": qualify changes locally before pushing. The owner
  prohibits waiting for or re-running paid Actions. Run `just check` and the relevant tox environments;
  explicitly hand off sandbox-blocked PostgreSQL/browser checks. S1 is parked for external cross-family review
  and integration; no Claude invocation or merge is part of this worker's scope.
- Release-notes entry for the raised floor in `docs/releases/0.2.68.rst`. Until S3 has removed `unreleased.rst`,
  every slice writes its entries to `0.2.68.rst`, the file the rule in `AGENTS.md:58` names for an untagged
  version.

### S2: parallel tests

- Add `pytest-xdist` to the `test` group.
- `justfile`: `test` becomes `uv run pytest -n 4 --cov --cov-report=` followed by `uv run coverage report`
  (which keeps enforcing `fail_under = 100`); add `test-serial` with today's commands for debugging order-dependent
  failures. `coverage` (HTML) uses the same parallel command. `test-fast`, `test-slow`, `test-one` stay serial.
- CI (hosted runners for public repositories have four cores). `workflow.yml:117` must not become
  `coverage run -m pytest -n 4`: that measures only the xdist controller process. The step becomes
  `uv run --no-sync pytest -n 4 --cov --cov-report=`, then `coverage report` and `coverage xml` as today (pytest-cov
  combines the worker data into `.coverage`). `workflow.yml:288` becomes `uv run pytest -n 4`. The tox environments
  stay serial: `just tox` already runs six environments at once.
- `tests/conftest.py`, `_reusable_test_db_path()`: when `PYTEST_XDIST_WORKER` is set and the name does not already
  end with `_<worker>`, append it. Each worker then drops and fingerprints its own database with the existing
  logic (see the spike under "Test suite"). The "already ends with" test matters: later in the session
  pytest-django has put the suffix into the settings itself, and a second suffix makes `ensure_wagtail_roots`
  skip its bootstrap.
- `.gitignore`: `tests/test_database.sqlite3_gw*`; the cleanup glob in `tox.ini:124` already covers the files.
- `docs/development.rst` (test section around lines 363–424) and `AGENTS.md`: document `-n 4`, the serial
  fallback and the per-worker database files with their own fingerprints. Two more places describe the serial
  setup and change with it: `docs/development.rst:510-517` (two sessions sharing `tests/test_database.sqlite3`;
  add that a parallel session uses the `_gw*` files and may drop a stale serial file) and `AGENTS.md:13` and `:32`
  (the commands behind `just test`).
- A fixed worker count, not `-n auto`: the machines that run several agents at once must not be oversubscribed.
- S2 does not wait for owner question 4. If the answer is "serial stays the default", the follow-up is a rename of
  two recipes (`test` serial, `test-parallel` with `-n 4`); CI keeps `-n 4` either way.

### S3: release notes

- Move every entry of `docs/releases/unreleased.rst` into `docs/releases/0.2.68.rst`, delete `unreleased.rst` and
  its line in `docs/releases/index.rst`, drop the duplicated entry.
- Nested bullets: a group stays together under its lead-in line and moves as one entry, with one exception. A
  sub-bullet that contains an upgrade action (today the removed `File` model with migration 0090,
  `unreleased.rst:126-134`) is lifted out and becomes its own entry under "Upgrade actions"; the group keeps the
  other sub-bullets.
- Give `0.2.68.rst` five sections in this order: "Upgrade actions" (everything an operator must do or check:
  every entry that names a migration together with something to do before or after it (today 0088, 0090 and the
  "apply migration 0087 and update …" entry), the Voxhelm credential pair, rebuilt player/comments bundles
  for custom themes, new limits that can reject existing content), "Features", "Security and hardening",
  "Fixes", "Internal". Entries keep their wording, with three kinds of difference that the commit message lists one by
  one: the duplicate is dropped, the upgrade sub-bullet is lifted out of its group (see above), and entries that
  a later entry supersedes are merged into one current statement (known case: the Voxhelm credential
  entry still says "changing the Wagtail API base requires re-entering its token", while `unreleased.rst:136-146`
  removes that admin field with migration 0088); nothing else is reworded and nothing is added.
- `BACKLOG.md:31` and `:37` point at `unreleased.rst`; S5 deletes those record bullets, so S3 leaves them alone
  and S5 runs after S3. The mention in `backlog/2026-11-14-scout-round96.md:42` is a dated record and stays as
  written.
- Add a small docs test next to `tests/docs_paths_test.py`: `unreleased.rst` must not exist while the notes file
  of the current version is titled "(unreleased)".
- The rule in `AGENTS.md:58` stays as it is; two sentences are added: check which of the two cases applies before
  writing; and a new entry goes under the matching section, with anything an operator must do under "Upgrade
  actions".
- `docs/release.rst:118-131` (creating the next notes file after a release): the new file starts with the five
  headings; at release time empty sections are deleted. The docs test does not check headings, so a notes file
  without them cannot turn the suite red. S3 lands before S4, which edits the same file.

### S4: one version

- `pyproject.toml` stays the source. `src/cast/__init__.py` reads `importlib.metadata.version("django-cast")`
  with a fallback of `"0+unknown"` for an uninstalled source tree. The fallback branch is covered by a test that
  patches `importlib.metadata.version` to raise `PackageNotFoundError`, reloads `cast` with `importlib.reload` and
  reloads it once more afterwards to restore the real value; no `pragma: no cover`. `docs/conf.py` reads `project.version` from
  `../pyproject.toml` with `tomllib` (Read the Docs installs only `docs/requirements.txt`, not the package).
- `docs/release.rst`: both "change the version in three files" lists become one file.
- Release-notes entry under "Internal" (`cast.__version__` now comes from the installed package metadata).

### S5: backlog and root hygiene

- Five of the 15 record bullets still carry pending wording: rounds 99, 97 and 96 say "external clerk review
  and integration are pending", round 90 says "external clerk review remains pending" and round 91 says
  "remaining external acceptance". All five rounds are merged into `develop` (`831a2929`, `ec06c0f8`, `617476e1`,
  `8f74fed2`, `97a62a5f`). First settle each one: whatever is really still open (for example an acceptance step
  outside this repository) becomes a `- [ ]` item under "Later"; the rest is finished.
- Then delete the 15 record bullets (`BACKLOG.md:5-39`, `:50-81`). The dated files in `backlog/` stay where they
  are; no new index of finished work is created, in line with `BACKLOG.md:46`. One sentence in the rules block of
  `BACKLOG.md` says so: records of finished work are the dated files in `backlog/` and are not listed here.
- `AGENTS.md:72-75`: notes for open work are linked from `BACKLOG.md`, design documents live in `docs/design/`
  (as `BACKLOG.md:43` already says); a validation or handoff record of finished work is a dated file in `backlog/`
  and needs no link.
- Delete `docs_inventory.md` and `django-cast-example.ps1`. `commands.py` and `notebooks/` only after the owner's
  answer (question 3); deleting `commands.py` also means removing the `jupyterlab` line from `Procfile:2` and
  rewriting `docs/operations/backup.rst:25`.

### S6: tooling drift

- `scripts/build_frontend.sh` holds the Vite part once: `npm run build` in `javascript/` followed by the manifest
  move, the trailing-newline fix and the copy into `src/cast/static/cast/vite/` (today the body of the recipe at
  `justfile:150-157` and, after `npm run build:all`, the rest of the CI step at `workflow.yml:61-72`). `just js-build-vite` calls the script and keeps its meaning; `just js-build-all` stays
  "Vite, then comments". The CI step, which today runs `npm run build:all` first, calls the script and then
  `npm run build:comments`, the same two steps in the same order as `js-build-all`.
- Remove the three apidoc `rm -f` lines.
- `.pre-commit-config.yaml`: `django-upgrade --target-version 5.2`; delete the commented mypy block (lines 34–65;
  line 33 is the live djhtml argument and stays). Run the hook once over all files: a higher target can rewrite
  code in `src/` or `tests/`. Review those rewrites and commit them in the same slice; if they are more than a handful
  of lines, keep the old target and leave the bump out.
- `views/styleguide.py:609`: replace `int(getattr(settings, "POST_LIST_PAGINATION", 5))` with
  `int(appsettings.POST_LIST_PAGINATION)`, the one registry setting that is still read around the registry.
- One release-notes entry under "Internal" for the slice.
- `AGENTS.md:25`: state the Ruff selection that `pyproject.toml:131` really has.
- Rename `tests/test_heading_migration.py` to `tests/heading_migration_test.py` and pin
  `python_files = ["*_test.py"]` in `[tool.pytest.ini_options]`.

### S7: shipped surface

- Delete `src/cast/runner.py`, `TEST_RUNNER` with its comment in `tests/settings.py:64-65`, the coverage omit entry
  (`pyproject.toml:179`) and the `runner.py` line of the module tree in `docs/architecture.rst:432` (the tree is
  checked by `tests/docs_paths_test.py`; the entry above it becomes the last one and takes the `└──` glyph).
- Replace `relativedelta` in `views/styleguide.py:410` and in its test
  (`tests/styleguide/context_comments_test.py:581`, used at `:602`) with standard-library date arithmetic; remove
  `python-dateutil` from `dependencies` and `types-python-dateutil` from `dev`. The helper promises "N calendar
  months before now" with distinct months, so the replacement steps back by year and month and clamps the day to
  the length of the target month (`calendar.monthrange`); a `replace(month=…)` alone raises on the 29th to 31st,
  and `timedelta(days=30 * n)` can skip or repeat a month. A new test calls `_styleguide_post_date(now, months_back)`
  directly with fixed datetimes (31 March and 31 December) and hand-written expected dates; the existing test,
  which goes through `_ensure_posts` and the real clock, keeps its shape but stops importing `dateutil`. `jupyter` in the `dev` group still
  pulls `python-dateutil` in, so a leftover import would pass `just check` locally and fail only in tox.
- Release-notes entry under "Internal" for both (a removed internal module and a removed dependency). The entry
  names the module as ``cast.runner``, not as a file path: `tests/docs_paths_test.py:41-56` checks that every
  `cast/….py` path literal in any `.rst` file, release notes included, exists.

### S8: test tree

- `git mv`, plus the import and path fixes that follow: the eight round-named modules get topic names inside the
  matching directory (`tests/transcripts/glossary_admission_test.py`, `tests/media_handling/rendition_repair_test.py`,
  `tests/media_handling/video_poster_test.py`, `tests/voxhelm/stale_write_test.py`, the four `scout87_*` modules likewise in place; final names by content), and the comment,
  feed and media families move into `tests/comments/`, `tests/feeds/`, `tests/media_handling/`; the seven
  voice-reference/known-speaker modules move into the existing `tests/transcripts/`. Shared helpers that other
  modules import out of a `*_test.py` file move into a plain `helpers.py` of the package (like the existing
  `tests/repository/helpers.py`); `conftest.py` stays for fixtures only. An import
  inside a function would not be exercised by collection, only by the full test run, so the slice ends with
  `just check`, not with `--collect-only` alone.
- The media package cannot be called `tests/media/`: that path is the default `MEDIA_ROOT` of the test settings
  (`tests/settings.py:90`) and is ignored by `.gitignore:80`.
- `tests/content/` has no `__init__.py` and its `blocks_test.py` shares a basename with `tests/blocks_test.py`;
  every new directory gets an `__init__.py`, like the seven existing test packages, so equal basenames cannot
  collide.
- Paths named outside `tests/` move with the files: the `[testenv:postgres]` commands in `tox.ini:74-78` name
  `tests/audio_models_test.py`, `tests/voxhelm/round88_test.py` and other modules by path (a stale path there turns
  both `postgres-locks` CI jobs red), and `docs/development.rst`, `AGENTS.md`, `CONTRIBUTING.rst:97` and a comment in
  `src/cast/transcripts/corrections.py:176` name test modules.
  `git grep -n "tests/[a-z0-9_/]*_test\.py" -- . ':!tests' ':!backlog' ':!docs/releases' ':!docs/design'` lists
  every live place. Dated notes in `backlog/` and published release notes keep the old paths: they describe the
  tree as it was.
- Run when no other branch has open test changes; this is the one slice that conflicts with parallel work.

## Risks and failure modes

- **S1, `dependency_groups` in tox.** If the pinned tox/tox-uv pair resolves the group differently from the old
  list (for example pulls `pytest-cov` into environments that did not have it), an environment could fail for a new
  reason, and derived sections inherit the key (see S1). Mitigation: run two matrix environments locally
  (`py311-django52-wagtail70`, `py314-django61-wagtail81`) before pushing, plus `just check-postgres` where a local PostgreSQL service is available; report any blocker.
- **S1, the collect guard needs to build an environment.** `uv run --isolated` needs a warm uv cache or network
  access, like `uv sync`. In a sandbox with neither, `just check` would fail for a reason unrelated to the code;
  there the other local recipes are run one by one and the local tox
  environments are the guard. `AGENTS.md`, the comment above the recipe in the `justfile` and the paragraph in
  `docs/development.rst` say so; the recipe itself does not try to tell the two kinds of failure apart.
- **S1, local qualification cannot attest hosted CI.** The owner prohibits relying on paid Actions.
  Run the CI-equivalent checks locally, report any environment blockers, and park S1 for external review.
- **S1, soupsieve 4.1 on the oldest branch.** `beautifulsoup4` has no upper bound on soupsieve. The oldest
  tox run checks Wagtail 7.0 compatibility; keep the requested >=4.1 floor and report any incompatibility.
- **S2, stale worker databases.** Without the conftest change a model or migration edit leaves the reused worker
  databases on the old schema and the next parallel run fails with missing columns. The change is part of the
  slice and has its own acceptance check.
- **S2, the controller still handles the serial database.** In a parallel run the controller process has no
  worker id, so it fingerprints the unsuffixed `tests/test_database.sqlite3` and drops it when it is stale. That
  is the same thing the next serial run would do, so nothing is lost, but a parallel run can delete the serial
  database file.
- **S2, hidden order or sharing dependencies.** Five parallel runs passed, but a test that shares a fixed path or
  port can still collide rarely. Mitigation: `just test-serial` stays; the acceptance run is repeated three times;
  the PostgreSQL environments are not parallelized.
- **S2, coverage under xdist.** Subprocess-driven tests are measured through the parent process today and stayed at
  100 % in the parallel run; if a later test relies on in-process state across tests, coverage could dip. The gate
  itself (`coverage report`, `fail_under = 100`) is unchanged and will say so.
- **S2, shared machines.** `-n 4` per agent on a machine with several agents multiplies load. The count is fixed,
  not `auto`; whether four is the right default there is owner question 4.
- **S3, lost or altered entries.** A merge of 140 entries by hand can drop one. Mitigation: acceptance compares the
  set of entry first lines before and after and requires every difference to be named.
- **S4, source tree without metadata.** `cast.__version__` returns `"0+unknown"` when the package is imported from
  a path without being installed. Every supported workflow (`uv sync`, tox wheel install, pip) installs it.
- **S6, `django-upgrade` rewrites.** Raising the target version can change source files on the first run; see S6
  for the bound.
- **S7, someone uses `cast.runner`.** It is not part of the public API and appears only in the module tree of
  `docs/architecture.rst`; neither consumer site nor theme references it. Noted in the release notes.
- **S7, a consumer relies on `python-dateutil` arriving through django-cast.** Checked on 2026-11-15: no `.py` or
  `.toml` file in `homepage`, `python-podcast`, `cast-bootstrap5` or `cast-vue` mentions `dateutil`. The slice
  repeats the check, and the release-notes entry says that projects importing `dateutil` must declare it
  themselves.
- **S8, merge conflicts.** Pure moves conflict with any branch that edits the moved files. Schedule it alone.
- **All slices:** `CHANGELOG`-style files are shared with parallel workers; rebase before every push and keep both
  sides.

## Test and qualification plan

Owner override (2026-11-15), implemented by S1: all workflows use only
`on: workflow_dispatch`. Historical CI-green requirements in later slices are
superseded by local qualification. `just check` includes JavaScript checks,
asset build comparison, docs and security audits; `just check-compatibility`
runs the six former dependency jobs, `just check-python` the additional Python
versions, and `just check-postgres` both database environments. No Actions waits.
S1 is parked, without merge, for external review.

Every slice: `just check` passes (lint, mypy, isolated collection, tests at 100 % coverage). Run the relevant
CI-equivalent checks locally before pushing and explicitly report sandbox-blocked checks; do not wait for or
re-run paid Actions. S1 is parked for external review and integration.

Additional checks per slice:

- S1: `uvx --from tox==4.61.2 --with tox-uv==1.36.0 tox -e py311-django52-wagtail70,py314-django61-wagtail81`
  locally, plus `tox -e postgres` where a local PostgreSQL is available (otherwise hand off both PostgreSQL environments as blocked); `just check-collect` fails on the tree before the import fix and passes after it; run the six `dependency-compatibility` environments and the advisory-floor audit locally.
  `CAST_RUN_BROWSER=1 uv run pytest tests/comment_browser_test.py` still runs the browser journey where Playwright
  and Chromium are installed.
- S2: three consecutive `just test` runs pass with 100 % coverage and each finishes in under 75 s on the
  development Mac; with a throwaway field added to a cast model, `uv run pytest -n 4 --deselect
  tests/post_body_blocks_test.py::test_makemigrations_check_has_no_churn_with_non_empty_custom_block_setting`
  passes twice in a row (that one test rightly fails on a model change without a migration) and the content of
  `tests/test_database.sqlite3_gw0.fingerprint` differs from before; it passes again after the field is removed
  (nothing of this is committed). The "dropped the reused database" report header is not part of the check: under
  xdist only the controller prints it, and the controller looks at the serial database; `just test-serial` passes once; `git status` is clean afterwards (no `_gw*` files shown); CI
  `python-quality` job time is lower than the 4.5–5.8 min measured here.
- S3: a throwaway script lists the first lines of all top-level and nested bullets before and after; every difference (the duplicate, the lifted
  sub-bullet and merged superseded entries) is named in the commit message and nothing else differs; the
  "Upgrade actions" section contains no two statements that contradict each other (read once, top to bottom);
  `just docs` builds without new warnings; the new docs test fails when `unreleased.rst` is restored.
- S4: `git grep -n '"0\.2\.68"' -- '*.py' '*.toml'` matches only `pyproject.toml:3`;
  `uv run python -c "import cast; print(cast.__version__)"` prints that version; the built
  docs show it; `uv build` produces a wheel whose metadata version matches.
- S5: for each of the five records with pending wording, the commit message says "finished" or names the new open
  item; every link in `BACKLOG.md` resolves (script over relative links); `tests/docs_paths_test.py`
  passes.
- S6: `just js-build-all` leaves `git status` clean on an unchanged tree; the CI `javascript` job's
  `git diff --exit-code` step passes; `pre-commit run django-upgrade --all-files` passes a second time without changing a file (not all hooks: on
  today's tree `pre-commit run --all-files` reindents eight templates with djhtml and touches three Python files,
  drift that is not this slice's to absorb); `pytest --collect-only -q` collects
  the same number of tests before and after the rename, on the same tree.
- S7: the direct test of `_styleguide_post_date` passes for 31 March and 31 December against hand-written
  expected dates; `git grep -n dateutil -- src tests` is empty; `git -C ../<repo> grep -l dateutil -- '*.py' pyproject.toml`
  is empty for the two consumer sites and the two theme repos (lockfiles are not searched: they list the package
  as a transitive dependency until the next re-lock); the wheel metadata no longer requires `python-dateutil`;
  one tox environment (`py312-django60-wagtail7latest`), which does not install the `dev` group, passes.
- S8: `pytest --collect-only -q` collects the same number of tests before and after; `git diff --stat -M` shows
  renames plus import lines and the path updates in `tox.ini` and the live docs; every `tests/…_test.py` path named
  outside `tests/`, `backlog/`, `docs/releases/` and `docs/design/` exists (script over the `git grep` above); `git ls-files -ci --exclude-standard` prints nothing (no tracked
  file sits under an ignore rule such as `tests/media/`); `git grep -n "tests/[a-z0-9_/]*_test\.py" -- tests` (run commands in docstrings, for example
  `tests/comment_browser_test.py:1`) names only existing files; both `postgres-locks` CI jobs are green.

## Implementation plan

Eight slices, in this order. S1 first because every later slice needs a CI result it can trust; S2 second because
it shortens all the others.

| Slice | Content | Time | Files touched | Acceptance criteria |
| --- | --- | --- | --- | --- |
| S1 | Local gates, one test dependency list, collect guard, manual workflows | 60 min | `tests/comment_browser_test.py`, `pyproject.toml`, `tox.ini`, `justfile`, `docs/development.rst`, `.github/workflows/workflow.yml`, `tests/dependency_policy_test.py`, `AGENTS.md`, release notes | Local quality/audit checks and compatibility tox environments pass; sandbox blockers are handed off; `tox.ini` has no hand-listed test packages and `dev` names none of the `test` packages; `just check-collect` fails when the unconditional import is restored |
| S2 | Parallel tests by default | 75 min | `pyproject.toml`, `justfile`, `tests/conftest.py`, `.github/workflows/workflow.yml`, `.gitignore`, `docs/development.rst`, `AGENTS.md` | `just test` three times green at 100 % in under 75 s each; green across a throwaway schema change and back (migration-churn test deselected); `just test-serial` green; no untracked database files; CI green |
| S3 | One release-notes file, upgrade actions first | 90 min | `docs/releases/0.2.68.rst`, `docs/releases/unreleased.rst` (deleted), `docs/releases/index.rst`, `tests/docs_paths_test.py` or a sibling, `AGENTS.md`, `docs/release.rst` | No entry lost (script); five sections; `AGENTS.md` and `docs/release.rst` name the sections; guard test for a stray `unreleased.rst`; docs build |
| S4 | Single version source | 40 min | `src/cast/__init__.py`, `docs/conf.py`, `docs/release.rst`, one test, release notes | Release-notes entry present; version literal in no `.py` file and in `pyproject.toml` only once; wheel, `cast.__version__` and docs agree |
| S5 | Backlog and root hygiene | 45 min | `BACKLOG.md`, `AGENTS.md`, `docs_inventory.md` and `django-cast-example.ps1` (deleted) | The first bullet after the rules block of `BACKLOG.md` is a `- [ ]` item and no bullet records finished work; pending parts of the five records are open items or settled; all links resolve |
| S6 | Tooling drift | 60 min | `scripts/build_frontend.sh` (new), `justfile`, `.github/workflows/workflow.yml`, `.pre-commit-config.yaml`, `AGENTS.md`, `pyproject.toml`, `tests/test_heading_migration.py` (renamed), `docs/development.rst`, `src/cast/views/styleguide.py`, release notes, possibly a few lines rewritten by `django-upgrade` | One implementation of the frontend build; CI asset guard green; same collected test count |
| S7 | Shipped surface: `runner.py`, `python-dateutil` | 45 min | `src/cast/runner.py` (deleted), `tests/settings.py`, `pyproject.toml`, `src/cast/views/styleguide.py`, `tests/styleguide/context_comments_test.py`, `docs/architecture.rst`, release notes | Dependency gone from the wheel metadata; 100 % coverage without the omit entry |
| S8 | Test tree: topic names and family packages | 60 min | `tests/` moves, new `tests/comments/`, `tests/feeds/`, `tests/media_handling/`, path updates in `tox.ini`, `docs/development.rst`, `AGENTS.md`, `CONTRIBUTING.rst`, `src/cast/transcripts/corrections.py` (comment) | Same collected test count; no stale test path in `tox.ini`, live docs or source comments (dated backlog notes and release notes excluded); `postgres-locks` green |

S3 and S5 change no shipped code (S3 adds one docs test); S3 can run in parallel with S2, and S5 follows S3 (it deletes backlog lines that
point at the file S3 removes). S1, S4, S6 and S7 change what is shipped and
each need a release-notes entry. S8 waits for a moment without other open test branches.

## Open owner questions

1. Soll `0.2.68` jetzt als Release geschnitten werden, sobald S1 bis S3 gelandet sind? Seit `0.2.67` sind 204
   Commits und 140 Release-Notes-Einträge aufgelaufen, und `homepage` und `python-podcast` installieren ohnehin
   direkt von `develop`.
2. Sollen die beiden Sites weiter direkt vom Branch `develop` installieren, oder künftig von einem Tag bzw. von
   PyPI? Solange es `develop` bleibt, ist ein roter CI-Lauf dort ein Produktionsrisiko.
3. Dürfen `notebooks/` (rund 50 alte Debug-Notebooks) und `commands.py` aus dem Repository gelöscht werden? Für
   `commands.py` müssten die JupyterLab-Zeile im `Procfile` entfernt und der Abschnitt `production-db-to-local` in
   `docs/operations/backup.rst` angepasst werden.
4. Ist `-n 4` als fester Standard für `just test` in Ordnung, auch wenn mehrere Agenten gleichzeitig auf derselben
   Maschine testen, oder soll der Standard seriell bleiben und parallel nur ein eigenes Rezept sein?
