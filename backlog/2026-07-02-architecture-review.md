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

### H3. `Transcript` is a 1575-line model containing file-format parsers

`src/cast/models/transcript.py` mixes the ORM model with WebVTT/Podlove/DOTe read-rewrite logic, speaker-sample
selection, known-speaker suggestion application, and fingerprinting (transcript.py:390-1474). Three formats' quirks
live as private methods on a Django model, and none of it runs without a `Transcript` row. Direction: extract
per-format handlers and a speaker-mapping service; leave `Transcript` as fields plus thin delegation. Its
`save()` → `sync_speaker_mappings()` (transcript.py:218-222) shares the H2 concern.

### H4. Triplicated admin media views for audio/video/transcript

`src/cast/views/audio.py`, `views/video.py`, and `views/transcript.py` copy `index`/`add`/`edit`/`delete`/`chooser`/
`chosen`/`chooser_upload` nearly verbatim (e.g. audio.py:28-80 vs video.py:27-79; the `render_modal_workflow` blob at
audio.py:248-253, video.py:238-243, transcript.py:677-682; the reindex loop ~10 times). Drift has started:
`video.chooser_upload` paginates with `per_page=10` (video.py:307) while audio uses `CHOOSER_PAGINATION`. Every
chooser/Wagtail-compat fix currently needs three edits. Direction: extract a generic media viewset/factory
parametrized by model, form, and template; at minimum factor out `reindex(obj)`, the chooser response, and the shared
search/paginate helpers.

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

### M3. Voxhelm integration is welded into the core

`voxhelm.py` (859 lines) is internally clean but not isolatable: its models are exported unconditionally from
`models/__init__.py`, a models↔voxhelm circular dependency is papered over with function-body imports
(voxhelm.py:112, voxhelm.py:392, wagtail_panels.py:23), `wagtail_hooks.py` unconditionally registers the Voxhelm
admin URLs and action menu item, and `django-tasks` is a hard dependency (pyproject.toml:47) used only for Voxhelm
completion. The file also mixes three concerns (settings layer, HTTP client, domain orchestration/task refs).
Direction: split into a `voxhelm/` subpackage (`client.py`, `service.py`, `task_refs.py`, `settings.py`), break the
model cycle, and consider an optional extra so `django-tasks` and the admin wiring activate only when configured.

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
explicitly. The larger legacy-API consolidation remains open.

### M5. `feeds.py` god module with duplicated feed logic and weak typing

`src/cast/feeds.py` (514 lines): `LatestEntriesFeed.item_description`/`item_link` (187-200) duplicate
`PodcastFeed`'s (442-455); `write()` is duplicated verbatim (142-149, 369-376); the
`PodcastIndexElements`/`ITunesElements`/`Atom1Feed` mixin stack relies on cooperative `super()` plus a defensive
`try/except AttributeError` (321-324); seven `# type: ignore` comments and untyped XML handler params. This is the
same module the mypy-strictness backlog item identifies as the worst offender — the two items should be tackled
together. Also: `LatestEntriesFeed` omits `item_pubdate`/`item_guid`, so non-podcast RSS/Atom items lack guids and
pubdates. Related to: "Consider stricter mypy annotation checks" in `BACKLOG.md`.

### M6. Test-only settings and dev fixtures ship inside the installed package

`src/cast/settings.py` is a test settings module — committed `SECRET_KEY`, `ROOT_URLCONF = "tests.urls"`, MD5
password hasher — that a `pip install`'d user receives in site-packages. Confusingly, the adjacent
`dev_settings.py` is a runtime feature-flag resolver, not a settings file. `devdata.py` (306 lines of
`# pragma: no cover` fixture factories with embedded binary blobs) also ships and is imported by both the test suite
and `views/styleguide.py`. Direction: move test settings into `tests/`, rename `dev_settings.py` to reflect its
role, and split the genuinely runtime part of `devdata.py` from pytest fixtures.

### M7. Cache-boundary serialization relies on key-sniffing in three places

`repository/serialization.py` hand-maintains per-model field lists (`serialize_post` vs `serialize_episode`
duplicate seven fields, serialization.py:238-282) and reconstruction guesses the concrete type by key presence in
three spots that must stay consistent: `deserialize_blog` (serialization.py:227-231), `FeedContext`
(contexts.py:271-277), and `BlogIndexContext` (`"podcast_audio" in post_data`, contexts.py:442). Adding a field to
Episode/Podcast requires updating the serializer, both deserializers, and the right key-sniff list, or the wrong
class is deserialized silently. Direction: store an explicit `type` discriminator and branch on it; centralize field
lists per model. Follows on from [2026-04-18-repository-readmodels.md](2026-04-18-repository-readmodels.md).

### M8. N+1 risk on the mixed blog-index snapshot path

`PostQuerySnapshot.create_from_post_queryset` only select-relates `podcast_audio__transcript` when the queryset
model is an `Episode` subclass (snapshot.py:108-110), but the blog index feeds a base `Post` queryset
(index_pages.py:207-217). For each episode row, `post.has_audio` → `self.specific.podcast_audio` (pages.py:355-357)
can issue per-row queries. Zero-query invariants are asserted for the podcast feed path but not the mixed index
path. Direction: prefetch for the episode subset of mixed querysets, or compute `has_audio` from prefetched data;
add a query-count assertion for the mixed path.

### M9. `transcript.edit` is a 150-line POST dispatcher with inline business logic

`views/transcript.py:467-616` branches on `request.POST.get("action")` across five modes, re-instantiating forms and
duplicating the messages+redirect tail; voice-reference/known-speaker orchestration lives in the view module.
`_episode_from_latest_revision` is duplicated identically in views/transcript.py:226 and views/voxhelm.py:86-87.
Direction: dispatch via an action→handler map and move orchestration behind the model/service layer (pairs with H3).

### M10. Very large test modules and a monolithic conftest

Largest test modules: `api_editor_test.py` (3353 lines), `transcript_views_test.py` (2337), `repository_test.py`
(1975), `voxhelm_test.py` (1967), `models_test.py` (1831); `tests/conftest.py` is 906 lines defining 72 fixtures
loaded for every session. Direction: split the biggest modules into packages with local `conftest.py` files; move
domain fixtures into per-directory conftests. Also add `tests/*.sqlite3` to `.gitignore` and consider a
`tests/support/` package for the helper modules mixed into `tests/` root.

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

### M12. Undocumented settings and quickstart template drift

Twelve of the ~51 user-facing `CAST_*` settings are missing from `docs/reference/settings.rst` (including
`CAST_AUDIO_PLAYER`, `CAST_EDITOR_SCOPES`, `CAST_POST_BODY_BLOCKS`, `CAST_SLUG`, four `CAST_COMMENTS_*`, and the
`CAST_STYLEGUIDE_*` tunables). Separately, `quickstart.py` embeds ~250 lines of settings/urls/wsgi as f-strings —
a second "recommended settings story" that drifts silently and is coverage-excluded; it also auto-creates a
`user`/`password` superuser. Direction: document the missing settings; generate quickstart projects from packaged
template files and add a smoke test that the generated project boots. Related to: "Revisit onboarding and authoring
workflows" and "Documentation polish pass" in `BACKLOG.md`.

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

## Suggested first slices

1. Fix B1 and B2 with tests (small, isolated, immediate value).
2. Delete the five dead config/doc files and unpin the pytest-randomly seed (H5, H6) — pure cleanup, no behavior
   risk beyond newly surfaced test-order bugs, which are the point.
3. Pick one structural theme to shape into its own backlog item: the save-side-effects extraction (H2) or the
   media-views deduplication (H4) are the most self-contained.
