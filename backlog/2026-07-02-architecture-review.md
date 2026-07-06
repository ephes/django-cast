# Architecture and Codebase Review

Date: 2026-07-02

Status: Findings list from a read-only architecture review of `develop`. The direct-fix pass on 2026-07-02
resolved B1, B2, H5, H6, the M4 permission slice, the safe M11 metadata subset, and several low items (each marked
"Fixed" below). Remaining findings should be split into concrete backlog items or explicitly accepted. Security was explicitly out of scope — see
[2026-06-23-security-review.md](2026-06-23-security-review.md), whose findings are all fixed.

Method: four parallel review passes (data layer; views/API/feeds; cross-cutting coupling; tests/tooling/frontend),
findings cross-checked against existing backlog notes so already-planned or already-landed work
(e.g. [2026-04-18-repository-readmodels.md](2026-04-18-repository-readmodels.md)) is not re-reported. The two
concrete bugs and the highest-severity claims were verified against the source before inclusion.

## Top themes (prioritized)

1. **Two concrete bugs** worth fixing immediately (feed `lastBuildDate` crash on empty blogs, dead guard in
   `PodcastFeed.categories`).
2. **The model layer does too much**: `Post`/`Episode` and `Transcript` are god classes that render HTML, select
   templates, and parse transcript file formats; `save()` overrides shell out to ffmpeg/ffprobe and generate
   renditions as side effects; models import from views/filters/blocks (inverted layering).
3. **Triplicated admin media views**: audio/video/transcript index/add/edit/delete/chooser views are near-identical
   copies that have already started drifting.
4. **Two API generations side by side**: the old DRF API mixes four view styles and ad-hoc error shapes; the new
   editor API is the clear template. Some old API views rely on an implicit AllowAny default.
5. **Settings resolution is fragmented** across five or six mechanisms for 54 `CAST_*` settings; a dozen settings are
   undocumented.
6. **Voxhelm is welded into the core** instead of being an optional integration; `django-tasks` is a hard dependency
   only Voxhelm uses.
7. **Dev/test code ships in the installed package**: test settings with a committed `SECRET_KEY`, dev fixture
   factories, and a stale custom test runner live under `src/cast/`.
8. **Tooling/config debt**: five dead config files describing tooling that no longer exists, a pinned
   `pytest-randomly` seed that defeats order randomization, and mypy/packaging metadata mismatches.

## Bugs (fix directly)

### B1. `Blog.last_build_date` raises `IndexError` on a blog with zero published posts — Fixed (2026-07-02)

`src/cast/models/index_pages.py:186` ends in `.order_by("-visible_date")[0].visible_date`. A blog or podcast with no
live public posts crashes when feed metadata asks for `lastBuildDate`. Use `.first()` with a fallback such as
`first_published_at` or `timezone.now()`, and add a test for the empty-blog feed.

### B2. `PodcastFeed.categories` guards on `categories` but reads `keywords` — Fixed (2026-07-02)

`src/cast/feeds.py:430-434`: `if hasattr(blog, "categories")` followed by `return (blog.keywords.split(",")[0],)`.
The guard never matches its body, so the branch is effectively meaningless. Decide which field feeds the RSS
`<category>` element, make the guard match, and add a test.

## High severity

### H1. `Post`/`Episode` god class renders HTML and owns presentation logic

`src/cast/models/pages.py` (1031 lines) mixes persistence with template selection (`get_template`,
`get_template_base_dir`, pages.py:286-302), request-aware URL building, cover/social-card rendition rendering
(pages.py:593-625), comment fetching (pages.py:537-567), and HTML rendering from inside the model: `get_description`
sets `self._local_template_name` and calls `self.serve(...).rendered_content` (pages.py:627-652). None of this is
unit-testable without a request/template stack, and mutating `_local_template_name` mid-render is a shared-state
footgun. Direction: move template-name resolution and description rendering into the view/feed layer or a presenter;
keep the model to fields, persistence, and pure derivations.

Fix note (partial, 2026-07-02): `get_description` is now side-effect free — the body template travels as a `serve`
kwarg and the `_local_template_name` machinery is gone (it was a real bug: instances rendered after a description
kept the feed partial). Full presenter extraction remains open (phase 2 of the model-layer decoupling backlog
item).

### H2. `save()` overrides do expensive, surprising work on every write

- `Post.save` runs `sync_media_ids()` and `create_missing_renditions_for_posts([self])` on every save
  (pages.py:691-695) — file I/O as a side effect of saving a row.
- `Audio.save` shells out to `ffprobe` (audio.py:347-378); `Video.save` shells out to `ffmpeg` for a poster and saves
  twice (video.py:183-202).

Bulk operations, data migrations, fixtures, and tests all pay this cost or silently skip it, and a rendition failure
can abort an editorial save. `Audio.save` wraps enrichment in `transaction.atomic` (good); Video and Post do not.
Direction: move media derivation to signals/async tasks or explicit services; make probe/render steps opt-in.

Fix note (partial, 2026-07-02): `Video.save` now wraps poster generation in `transaction.atomic` like `Audio.save`,
and `Post.save` gained `sync_media`/`create_renditions` opt-out kwargs (defaults unchanged). Moving the derivation
work to services/async remains open (phase 2).

### H3. `Transcript` is a 1575-line model containing file-format parsers — Fixed (2026-07-02)

`src/cast/models/transcript.py` mixes the ORM model with WebVTT/Podlove/DOTe read-rewrite logic, speaker-sample
selection, known-speaker suggestion application, and fingerprinting (transcript.py:390-1474). Three formats' quirks
live as private methods on a Django model, and none of it runs without a `Transcript` row. Direction: extract
per-format handlers and a speaker-mapping service; leave `Transcript` as fields plus thin delegation. Its
`save()` → `sync_speaker_mappings()` (transcript.py:218-222) shares the H2 concern.

Fix note: new `cast.transcripts` domain package. Django-free format/parsing modules (`parsing`, `webvtt`,
`podlove`, `dote`, `known_speakers`, `speaker_samples`, `voice_references`) hold each format's quirks and run
without a `Transcript` row; `transcripts/services.py` holds the speaker-mapping/known-speaker orchestration
(no runtime `cast.models` import, so the model→services dependency stays acyclic). `Transcript` keeps its
fields, file-IO primitives, and one-line delegates with unchanged public signatures; public module names
(`time_to_seconds`, `convert_dote_to_podcastindex_transcript`, `KNOWN_SPEAKER_*`, the dataclasses) remain
importable from `cast.models.transcript`. The `save()`→`sync_speaker_mappings()` coupling itself is unchanged
(H2 territory). Plan: `docs/superpowers/plans/2026-07-02-transcript-domain-extraction.md`.

### H4. Triplicated admin media views for audio/video/transcript — Fixed (2026-07-02)

`src/cast/views/audio.py`, `views/video.py`, and `views/transcript.py` copy `index`/`add`/`edit`/`delete`/`chooser`/
`chosen`/`chooser_upload` nearly verbatim (e.g. audio.py:28-80 vs video.py:27-79; the `render_modal_workflow` blob at
audio.py:248-253, video.py:238-243, transcript.py:677-682; the reindex loop ~10 times). Drift has started:
`video.chooser_upload` paginates with `per_page=10` (video.py:307) while audio uses `CHOOSER_PAGINATION`. Every
chooser/Wagtail-compat fix currently needs three edits. Direction: extract a generic media viewset/factory
parametrized by model, form, and template; at minimum factor out `reindex(obj)`, the chooser response, and the shared
search/paginate helpers.

Fix note: `cast.views.media` now holds a `MediaAdminConfig` dataclass plus `MediaAdminViews` implementing all
seven views once (including the `reindex(obj)` helper); `audio.py`/`video.py`/`transcript.py` shrink to configs,
thin URL-kwarg wrappers, and their genuinely type-specific parts (audio's multi-format old-file deletion and
voxhelm edit context, transcript's action-dispatcher `edit` and public transcript views stay local). The
`per_page=10` drift is fixed — video's chooser upload honors `CHOOSER_PAGINATION`, with a regression test.
URL names/kwargs, templates, context keys, message msgids, and modal-workflow JSON are unchanged. Plan:
`docs/superpowers/plans/2026-07-02-media-views-dedup.md`.

### H5. Stale tooling documentation and dead config files — Fixed (2026-07-02)

- `bootstrap.md` documents a `piptools`/`requirements/*.in` workflow; the `requirements/` directory no longer exists
  (the project uses `uv`). A contributor following it cannot succeed.
- `.travis.yml` describes a `flit`/`codecov` pipeline replaced by GitHub Actions.
- `setup.cfg` holds flake8/isort config for tools that are no longer dependencies, with a line length (88) that
  contradicts Ruff (119).
- `runtests.py` is a dead second test entry point that coverage still references
  (`command_line = "runtests.py tests"`, pyproject.toml:160) while CI, justfile, and tox all run pytest.
- `javascript/jest.config.js` is a leftover from the Jest→Vitest migration.

Direction: delete all five (fold anything useful from `bootstrap.md` into `docs/development.rst`), set
`[tool.coverage.run] command_line = "-m pytest"`, and also remove `command_lines.txt`.

Fix note: all six files deleted; `commands.py`'s `test`/`mypy` subcommands (the one remaining live reference to
`runtests.py`) were switched to pytest and plain mypy, implementing their own FIXME.

### H6. `pytest-randomly` is pinned to a fixed seed, so test order never randomizes — Fixed (2026-07-02)

`pyproject.toml:137` sets `--randomly-seed=1234` in `addopts`; every run locally and in CI uses identical order,
which defeats the plugin's purpose — order-dependency and state-leak bugs never surface. Direction: drop the fixed
seed from `addopts`; keep a `just` recipe that passes an explicit seed for reproducing failures.

Fix note: unpinning immediately surfaced two real isolation bugs, both fixed — the module-scoped `api_client`
fixture leaked session cookies between tests (now function-scoped), and a `USE_THREADEDCOMMENTS` monkeypatch could
bake the wrong comment-form base class if it triggered the first import of `cast/comments/forms.py` (test now
imports before patching). Residual hazard: the import-time base-class selection in `comments/forms.py:30` remains —
a future test repeating that pattern would reintroduce the bug.

## Medium severity

### M1. Models depend on the presentation layer (inverted import direction) — Partially fixed (2026-07-02)

Module-level imports pull views/blocks/presentation into models: `from ..views import HtmxHttpRequest`
(pages.py:49, index_pages.py:28), `from cast.blocks/player/follow_links import ...` (pages.py:39-45),
`from cast.filters import PostFilterset` (index_pages.py:25). This forces circular-import workarounds via
function-local imports scattered through `models/` and `models/repository/` (141 function-body imports repo-wide,
clustered in `repository/serialization.py` and the models↔voxhelm cycle). Direction: move `HtmxHttpRequest` to a
neutral module; let presentation import models, not the reverse.

Fix note (2026-07-02): `HtmxHttpRequest` moved to `cast/http_types.py` (re-exported from `cast.views` for
compatibility); no `views` imports remain in `src/cast/models/`. The blocks/filters import inversion remains open.

### M2. Settings resolution fragmented across five or six mechanisms

54 `CAST_*` settings with no single accessor: `appsettings.py` module `__getattr__` defaults, `appsettings.py`
mutation of `django.conf.settings` at app-ready (`set_default_if_not_set`), a second `__getattr__` module in
`comments/appsettings.py`, a Voxhelm-only precedence chain (`voxhelm.py:124`, site setting → Django setting → env
var), `dev_settings.py` (46 lines to resolve one boolean), and 51 scattered `getattr(settings, "CAST_...", default)`
calls each with their own inline default. `check_cast_setting_types` (checks.py:19) hand-maintains a parallel type
table because defaults are not centralized. Direction: consolidate on the `appsettings.__getattr__` pattern, fold in
Voxhelm helpers and inline defaults, and drop the global-settings mutation in favor of read-time defaults.

Fix note (2026-07-03, mostly fixed): `cast.appsettings.CAST_SETTING_REGISTRY` now owns every static `CAST_*`
default; the inline `getattr(settings, "CAST_...", default)` call sites read through the accessor at call time
(coercions stay local, so `override_settings` and string env values behave as before), and
`check_cast_setting_types` derives from registry metadata with a test pinning the enforcement scope to the
previous eleven settings. Deliberately kept: the app-ready `set_default_if_not_set` mutation (it defaults
third-party settings — `SITE_ID`, `WAGTAIL_SITE_NAME`, `CRISPY_*` — that third-party code reads directly, so
read-time defaults cannot replace it), `comments/appsettings.py` as the comments accessor (legacy `FLUENT_*`
fallbacks and strict coercions; its defaults now source from the central registry), and
`dev_settings.dev_tools_enabled` (deprecation precedence). The Voxhelm site→setting→env chain was folded into
`cast/voxhelm/settings.py` with the M3 subpackage extraction (2026-07-03) — it stays a deliberate third
mechanism (site setting beats Django setting beats env var) but now lives in one named settings module.

### M3. Voxhelm integration is welded into the core

`voxhelm.py` (859 lines) is internally clean but not isolatable: its models are exported unconditionally from
`models/__init__.py`, a models↔voxhelm circular dependency is papered over with function-body imports
(voxhelm.py:112, voxhelm.py:392, wagtail_panels.py:23), `wagtail_hooks.py` unconditionally registers the Voxhelm
admin URLs and action menu item, and `django-tasks` is a hard dependency (pyproject.toml:47) used only for Voxhelm
completion. The file also mixes three concerns (settings layer, HTTP client, domain orchestration/task refs).
Direction: split into a `voxhelm/` subpackage (`client.py`, `service.py`, `task_refs.py`, `settings.py`), break the
model cycle, and consider an optional extra so `django-tasks` and the admin wiring activate only when configured.

Fix note (2026-07-03, fixed): `cast.voxhelm` is now a subpackage (`exceptions`, `settings` — the site→setting→env
chain, `client`, `task_refs`, `service`), split byte-faithfully with the full public surface re-exported from the
package `__init__`. The models↔voxhelm cycle is gone: the status helpers (`get_transcript_generation`,
`get_transcript_generation_status_context`, `transcript_complete`) moved to
`cast/transcripts/generation_status.py`, which imports only model leaf submodules, so `wagtail_panels.py` imports
it at module level — no function-body imports; a static AST test (`tests/import_cycle_test.py`) pins that nothing
imported during `cast.models` initialisation depends on `cast.voxhelm`, including inside function bodies.
Optional-extra decision (recorded in `docs/superpowers/plans/2026-07-03-voxhelm-subpackage.md`): no `[voxhelm]`
packaging extra — `django-tasks` stays a hard dependency (lightweight; an extra would trade clean degradation for
ImportError crashes), models/migrations stay unconditional (Django model discovery cannot be optional), and the
`cast_transcripts` TASKS backend is only required at first enqueue because `voxhelm_tasks` is deliberately
imported lazily (`@task(backend=...)` resolves the backend at import time — verified empirically; the lazy import
in `enqueue_audio_transcript_generation` is the load-bearing optionality seam, not cycle paper-over). The admin
wiring half landed as a visibility gate: the "Generate transcript" action/button renders only when
`voxhelm_configured()` resolves the API base and key for the request's site; status display and the POST paths'
friendly misconfiguration errors are unchanged.

### M4. Two inconsistent API generations side by side; implicit AllowAny on writes

`api/views.py` (old) mixes four styles: a function view, a Django `CreateView` returning bare-text
`HttpResponse("{pk}", 201)` (viewmixins.py:14-17), DRF generics, and raw `APIView`, with ad-hoc error shapes and no
scopes. The editor API (`api/editor/`) has a clean base view, structured errors, per-method `required_scopes`,
fail-closed permissions, and `If-Match` revision-conflict handling — it is the template the rest should follow.
Concretely, `UpdateThemeView`/`ThemeListView` (api/views.py:271-309) declare no `permission_classes` and rely on the
DRF default. Anonymous access is intended here — theme selection is a per-session cosmetic preference
(`set_template_base_dir` writes only `request.session`, views/theme.py:10-12), like the non-API `select_theme`
view — so the risk is the inverse: a host project that sets a restrictive `DEFAULT_PERMISSION_CLASSES` silently
breaks the theme switcher for anonymous visitors. Direction: set `permission_classes` explicitly on every API view
(`(AllowAny,)` where anonymous access is intended, as here), freeze and document the old API as legacy, and migrate
still-used endpoints to editor conventions.

Fix note (partial, 2026-07-02): the six permission-less DRF views now declare `permission_classes = (AllowAny,)`
explicitly.

Fix note (2026-07-03, resolved as freeze): `cast.api.views` is now documented as a legacy surface with a module
docstring and a "Legacy API" section in `docs/reference/api.rst`; new clients are pointed at `cast.api.editor.*`.
The "migrate still-used endpoints to editor conventions" direction is deliberately superseded: the 2026-06-25
media-detail plan already committed to keeping `POST /api/upload_video/`'s bare-text `"<pk>"` 201 response for
existing clients, and the podlove/player-config/facet-counts/theme response shapes are consumed by cast-vue via
page-supplied URLs, so migrating their contracts would be a breaking change with no caller demand. The endpoints
stay frozen-as-legacy rather than rewritten; no open work remains for M4.

### M5. `feeds.py` god module with duplicated feed logic and weak typing

`src/cast/feeds.py` (514 lines): `LatestEntriesFeed.item_description`/`item_link` (187-200) duplicate
`PodcastFeed`'s (442-455); `write()` is duplicated verbatim (142-149, 369-376); the
`PodcastIndexElements`/`ITunesElements`/`Atom1Feed` mixin stack relies on cooperative `super()` plus a defensive
`try/except AttributeError` (321-324); seven `# type: ignore` comments and untyped XML handler params. This is the
same module the mypy-strictness backlog item identifies as the worst offender — the two items should be tackled
together. Also: `LatestEntriesFeed` omits `item_pubdate`/`item_guid`, so non-podcast RSS/Atom items lack guids and
pubdates. Related to: "Consider stricter mypy annotation checks" in `BACKLOG.md`.

Fix note (2026-07-03, fixed): `feeds.py` now has one copy of the shared feed logic. `item_description`,
`item_link`, `item_pubdate`, and `item_updateddate` live on `RepositoryMixin` (deleted from both feed classes),
and the Atom stylesheet `write()`/`add_stylesheets()` are shared via `AtomStylesheetsMixin`. The
`PodcastIndexElements`/`ITunesElements` mixins now subclass `SyndicationFeed` so cooperative `super()` resolves
statically; the runtime MROs and per-method owners of `AtomITunesFeedGenerator`/`RssITunesFeedGenerator` are
unchanged (verified), so podcast XML output is byte-identical. The defensive `try/except AttributeError` and all
seven `# type: ignore` comments are gone (feeds.py has zero). The two additive changes are on the blog feeds only:
`LatestEntriesFeed` gains pubdate/updateddate and an explicit `<guid isPermaLink="false">`/Atom `<id>` of the
post uuid (`serialize_post` now carries `last_published_at` so the cached path can render Atom `<updated>`).

### M6. Test-only settings and dev fixtures ship inside the installed package

`src/cast/settings.py` is a test settings module — committed `SECRET_KEY`, `ROOT_URLCONF = "tests.urls"`, MD5
password hasher — that a `pip install`'d user receives in site-packages. Confusingly, the adjacent
`dev_settings.py` is a runtime feature-flag resolver, not a settings file. `devdata.py` (306 lines of
`# pragma: no cover` fixture factories with embedded binary blobs) also ships and is imported by both the test suite
and `views/styleguide.py`. Direction: move test settings into `tests/`, rename `dev_settings.py` to reflect its
role, and split the genuinely runtime part of `devdata.py` from pytest fixtures.

Fix note (2026-07-03, fixed): `src/cast/settings.py` is gone — its content moved into `tests/settings.py`
(now self-contained: no `from cast.settings import *`, `INSTALLED_APPS` composed as the base Django apps plus
`list(cast.apps.CAST_APPS)`), so `pip install django-cast` ships no test settings (verified against the built
wheel). `dev_settings.py` was renamed to `dev_tools.py` to match its feature-flag-resolver role (content
identical; importers in `views/dev.py`/`views/styleguide.py` and the test module repointed). `django-environ`,
used only by the old test settings, is dropped from the dependencies. django-stubs imports its
`django_settings_module` (now `tests.settings`) at runtime, so `just typecheck` and the CI mypy step put the
repo root on `PYTHONPATH`. The `devdata.py` fixture/runtime split is deliberately deferred (the BACKLOG item
scoped M6 to the settings move only).

### M7. Cache-boundary serialization relies on key-sniffing in three places

`repository/serialization.py` hand-maintains per-model field lists (`serialize_post` vs `serialize_episode`
duplicate seven fields, serialization.py:238-282) and reconstruction guesses the concrete type by key presence in
three spots that must stay consistent: `deserialize_blog` (serialization.py:227-231), `FeedContext`
(contexts.py:271-277), and `BlogIndexContext` (`"podcast_audio" in post_data`, contexts.py:442). Adding a field to
Episode/Podcast requires updating the serializer, both deserializers, and the right key-sniff list, or the wrong
class is deserialized silently. Direction: store an explicit `type` discriminator and branch on it; centralize field
lists per model. Follows on from [2026-04-18-repository-readmodels.md](2026-04-18-repository-readmodels.md).

Fix note (2026-07-03, fixed): each serializer now writes an explicit `type` discriminator
(`serialize_blog` → `"podcast"`/`"blog"`, `serialize_post` → `"post"`, `serialize_episode` → `"episode"`), and
the three reconstruction sites (`deserialize_blog`, `FeedContext`, `BlogIndexContext`) branch on it. Each keeps
the old key-sniff as an explicit fallback for cache entries written before this change (commented "removable
after one release"); the deserializers strip `type` before constructing the model. Both the discriminator and
fallback branches are covered by new round-trip and legacy-entry tests. The per-model field-list centralization
the finding also suggests is deliberately deferred — a larger refactor with no correctness pressure now that the
discriminator removes the silent-misclassification risk; noted as a residual.

### M8. N+1 risk on the mixed blog-index snapshot path — Fixed (2026-07-02)

`PostQuerySnapshot.create_from_post_queryset` only select-relates `podcast_audio__transcript` when the queryset
model is an `Episode` subclass (snapshot.py:108-110), but the blog index feeds a base `Post` queryset
(index_pages.py:207-217). For each episode row, `post.has_audio` → `self.specific.podcast_audio` (pages.py:355-357)
can issue per-row queries. Zero-query invariants are asserted for the podcast feed path but not the mixed index
path. Direction: prefetch for the episode subset of mixed querysets, or compute `has_audio` from prefetched data;
add a query-count assertion for the mixed path.

### M9. `transcript.edit` is a 150-line POST dispatcher with inline business logic — Fixed (2026-07-02)

`views/transcript.py:467-616` branches on `request.POST.get("action")` across five modes, re-instantiating forms and
duplicating the messages+redirect tail; voice-reference/known-speaker orchestration lives in the view module.
`_episode_from_latest_revision` is duplicated identically in views/transcript.py:226 and views/voxhelm.py:86-87.
Direction: dispatch via an action→handler map and move orchestration behind the model/service layer (pairs with H3).

Fix note: `edit` now dispatches through an `EDIT_ACTION_HANDLERS` map (unknown/missing actions fall through to
the plain transcript-form save handler, as before); each old branch became a handler with identical messages,
redirects, and form state. Editor orchestration (speaker-mapping context, voice-reference lookup/creation,
`episode_from_latest_revision`) moved to `cast/transcripts/editing.py`; the duplicate
`_episode_from_latest_revision` in `views/voxhelm.py` was deleted in favor of the single shared function.

### M10. Very large test modules and a monolithic conftest

Largest test modules: `api_editor_test.py` (3353 lines), `transcript_views_test.py` (2337), `repository_test.py`
(1975), `voxhelm_test.py` (1967), `models_test.py` (1831); `tests/conftest.py` is 906 lines defining 72 fixtures
loaded for every session. Direction: split the biggest modules into packages with local `conftest.py` files; move
domain fixtures into per-directory conftests. Also add `tests/*.sqlite3` to `.gitignore` and consider a
`tests/support/` package for the helper modules mixed into `tests/` root.

Fix note (2026-07-03, fixed): the seven largest flat modules were split into per-directory packages —
`tests/api/`, `tests/transcripts/`, `tests/repository/`, `tests/voxhelm/`, `tests/models/`,
`tests/styleguide/` — each an `__init__.py` package with a local `conftest.py`. No module exceeds ~940 lines
now. Directory-exclusive fixtures (`mp3_audio`/`create_minimal_mp3`, `video_with_poster`, `post_in_podcast`)
moved from the root conftest (912 → 876 lines) into the owning directory's conftest, each verified used only
under that directory. The reorganisation is behavior-preserving: the collected set of test node-ID suffixes is
identical before and after (2148 tests, verified by an independent suffix-multiset diff against the pre-split
commit, empty), and every moved test body is unchanged. The `tests/support/` helper-package idea is deferred.

### M11. Packaging and type-check metadata inconsistencies

- Conflicting license classifiers in `pyproject.toml` (BSD at :24, MIT at :28; `LICENSE` says BSD) and
  `Environment :: Web Environment` listed twice.
- mypy `python_version = "3.14"` (pyproject.toml:141) while `requires-python = ">=3.11"` and Ruff targets `py311` —
  type checks run at a newer level than the support floor. `django_settings_module` is declared twice (modern
  `[tool.django-stubs]` and legacy `[mypy.plugins.django-stubs]`).
- `crispy-bootstrap4`/`django-crispy-forms` are hard dependencies for one theme; `django-environ` is a runtime
  dependency with the comment "needed by pluggy and pytest".
- `tox.ini` duplicates the full dependency list between `[testenv]` and `[testenv:fast]`, and `fast` hardcodes
  `Django>=6.0` while the matrix parameterizes it.

Direction: keep BSD only, set mypy to 3.11, delete the legacy mypy plugin block, audit which runtime dependencies
are really theme- or dev-only, and factor tox deps into a base env.

Fix note (partial, 2026-07-02): classifiers deduplicated (BSD only), mypy pinned to 3.11, legacy django-stubs
plugin table removed. Still open: the runtime-dependency audit and the tox base-env refactor.

Fix note (2026-07-03, fixed): `[testenv:fast]` now inherits the shared tool deps and `setenv` from `[testenv]`
via `{[testenv]deps}`/`{[testenv]setenv}` (keeping only its own Django/wagtail pins), so the duplicated
dependency and env-var lists are gone. The runtime-dependency audit found every `[project]` dependency except
`setuptools` has a direct `src/cast` reference; `setuptools` has none but is documented as required by
`django-model-utils` on Python ≥ 3.12, so it was left in place (a scratch-venv removal proof is the residual).
`django-environ` was already removed in the M6 slice.

### M12. Undocumented settings and quickstart template drift — Partially fixed (2026-07-03)

Twelve of the ~51 user-facing `CAST_*` settings are missing from `docs/reference/settings.rst` (including
`CAST_AUDIO_PLAYER`, `CAST_EDITOR_SCOPES`, `CAST_POST_BODY_BLOCKS`, `CAST_SLUG`, four `CAST_COMMENTS_*`, and the
`CAST_STYLEGUIDE_*` tunables). Separately, `quickstart.py` embeds ~250 lines of settings/urls/wsgi as f-strings —
a second "recommended settings story" that drifts silently and is coverage-excluded; it also auto-creates a
`user`/`password` superuser. Direction: document the missing settings; generate quickstart projects from packaged
template files and add a smoke test that the generated project boots. Related to: "Revisit onboarding and authoring
workflows" and "Documentation polish pass" in `BACKLOG.md`.

Fix note (2026-07-03): the settings half is done — every user-facing setting is documented in
`docs/reference/settings.rst`, with defaults verified against the central registry. `CAST_SLUG` turned out not
to exist in the codebase (stale name in this finding). The quickstart template-drift half remains open and
belongs to the "Revisit onboarding and authoring workflows" backlog item.

Fix note (2026-07-06): the quickstart template-drift half is fixed — `django-cast-quickstart` now renders generated
project files from packaged templates under `cast/quickstart_templates`, and a focused test generates a project and
verifies it passes Django's system check. The broader onboarding workflow review remains open in `BACKLOG.md`.

## Low severity (batch when touching the area)

- Rendering relies on runtime attribute injection onto model instances (`post._media_lookup`, `post.page_url`,
  `blog._last_build_date`, `getattr(self, "_repository", None)` in pages.py:365-368) — invisible temporal coupling;
  prefer carrying render state on the repository/context object.
- `ContributorVoiceReference`/`EpisodeContributor`/`ContributorLink` call `clean()` inside `save()`
  (contributors.py:241-243, 379-381, 285-287), so programmatic writes can raise `ValidationError` unexpectedly and
  admin saves validate twice.
- `get_template_base_dir_choices()` scans template directories at import time and bakes results into class bodies
  and migrations (theme.py:151-180, :231; index_pages.py:109); use a callable for `choices=`.
- FIXME-marked smells in pages.py:385, :199, :842. (Fixed 2026-07-02: the stray `print` in
  `Evaluation.calc_performance` (models/moderation.py) and the dead `Post.get_url` passthrough override; the
  `tests/*.sqlite3` gitignore entry from M10 also landed.)
- Media handling is scattered across four unrelated top-level modules (`media_probe.py`, `media_validation.py`,
  `file_replacement.py`, `transcript_sanitization.py`) with ffprobe/ffmpeg calls embedded in models; there is no
  system check for the ffprobe/ffmpeg binaries although `checks.py` covers everything else.
- No throttling on the public transcript JSON/VTT function views (views/transcript.py:763-820);
  `modal_facet_counts.get_modal_facet_counts` issues many small unbatched queries per group (bounded but uncached).
- `RemoveNullBytesMixin` mutates `request.GET` (api/views.py:312-331) — self-described stopgap.
- Repo-root clutter: ~50 tracked debug notebooks (~4 MB) in `notebooks/`, plus `commands.py`,
  `django-cast-example.ps1`, `docs_inventory.md` at root; confirm the sdist does not ship them.
- The Vite manifest move/newline dance is hand-rolled identically in `justfile:133-141` and CI; move it into one
  script under `scripts/`.
- `docs/conf.py` has `extensions = []` (no autodoc), yet the justfile and CI docs job pre-delete apidoc output that
  is never generated.
- The `slow` pytest marker is used by only two modules, so `just test-fast`/`test-slow` tiering gives little benefit.

## What is genuinely good (keep doing this)

- The repository read-model layer: disciplined split across builders/contexts/snapshot/serialization/types with an
  explicit zero-query render goal and typed cache boundaries.
- Access control: `audio_access.py` (fail-closed, non-disclosing 404s, threat-model docstrings) and the editor API
  scope enforcement (`api/editor/scopes.py`) are exemplary; the editor API overall is the pattern to standardize on.
- `file_replacement.py` staged replacement with ordered rollback and `transaction.on_commit` cleanup; layered upload
  validation in `media_validation.py`; the `ContextVar` probe budget in `media_probe.py`.
- CI discipline: 100% branch coverage enforced, built frontend assets guarded against staleness via
  `git diff --exit-code`, and a broad matrix (ruff, mypy, docs, Python 3.11–3.14, Vitest).
- The spam filter keeps its algorithm as pure functions with a thin model around it; comment posting handles
  concurrency with `select_for_update` and post-commit signals.

## Suggested first slices (historical — all completed by 2026-07-03)

1. Fix B1 and B2 with tests (small, isolated, immediate value). — Done 2026-07-02.
2. Delete the five dead config/doc files and unpin the pytest-randomly seed (H5, H6) — pure cleanup, no behavior
   risk beyond newly surfaced test-order bugs, which are the point. — Done 2026-07-02.
3. Pick one structural theme to shape into its own backlog item: the save-side-effects extraction (H2) or the
   media-views deduplication (H4) are the most self-contained. — Done: H2 phase 1 and H4 landed 2026-07-02,
   H3/M9 and M2/M12 followed 2026-07-02/03. Remaining themes (M3, M4/M5, M6/M7/M10/M11, model-layer phase 2)
   live as items in `BACKLOG.md`.
