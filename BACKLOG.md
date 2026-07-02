# Backlog

This is the canonical planning backlog for django-cast. Keep it small and actionable.

- Use this file as the index for planned and future work.
- Put larger feature notes in `backlog/*.md` and link them from here.
- Keep README and docs backlog references as links to this file instead of maintaining separate planned-work lists.
- When docs mention future behavior, add or update the matching entry here.
- Do not keep a separate done list. Completed user-facing work belongs in the current release notes under
  `docs/releases/`; implementation history belongs in git.
- Use `Depends on` for blocking relationships and `Related to` for non-blocking cross-links.
- GitHub issues are optional for public coordination, but local planning starts here.

## Next

- [ ] Choose next implementation slice
  - Scope: pick a small, concrete item from Research / Shaping or Later based on current project needs.
  - Done when: the chosen item has a clear first slice, expected files/tests, and any sibling-repo checks identified.

## Research / Shaping

- [ ] Architecture review follow-ups
  - Notes: [backlog/2026-07-02-architecture-review.md](backlog/2026-07-02-architecture-review.md)
  - Status: the direct-fix pass landed on 2026-07-02 (bugs B1/B2 with tests, dead tooling/config cleanup, seed
    unpin plus the two test-isolation bugs it surfaced, explicit API permissions, safe metadata subset).
  - Scope: triage the remaining findings — split the larger structural themes (model-layer god classes and `save()`
    side effects, triplicated media admin views, settings consolidation, Voxhelm isolation, legacy API migration)
    into their own backlog items or explicitly accept them.
  - Related to: Consider stricter mypy annotation checks (feeds.py typing), Documentation polish pass (undocumented
    settings), Revisit onboarding and authoring workflows (quickstart template drift).
  - Done when: each remaining high/medium finding is either a concrete backlog item or explicitly accepted in the
    review doc.

- [ ] Typeahead search
  - Scope: research whether current full-text search is fast enough for typeahead, what API/frontend surface is
    needed, and how to keep it optional for themes.
  - Done when: there is a short implementation note with benchmark expectations, proposed endpoints or context
    contracts, accessibility constraints, and a first implementation slice.

- [ ] Revisit onboarding and authoring workflows
  - Scope: review the existing `django-cast-quickstart`, `example/scripts/bootstrap_example_data.py`, and
    `ensure_reference_site` workflows and decide what onboarding should mean for django-cast users: new project
    setup, local development setup, editor onboarding, or assisted content authoring.
  - Notes: include "try django-cast with your own podcast feed" as one possible getting-started path, built on
    top of the podcast feed import workflow.
  - Done when: the current workflows are documented in one place, gaps are listed, and follow-up items are split
    into concrete implementation tasks.

- [ ] Local authoring and sync workflow
  - Scope: research whether django-cast should support a local-first editing workflow where content can be pulled
    from a production site, edited locally, previewed, and synced back safely.
  - Notes: compare API-based sync, database snapshot/restore, Wagtail revisions, management commands, and a
    desktop/app wrapper. Avoid direct production database mutation as the default path.
  - Done when: tradeoffs are documented for data ownership, conflict resolution, media files, revision history,
    authentication, rollback, and production safety, with a recommended first slice.

- [ ] Example desktop authoring application
  - Depends on: programmatic content editing API and local authoring/sync workflow shaping.
  - Scope: evaluate whether an example desktop app would make django-cast easier to use for local content authoring
    and sync.
  - Notes: candidates include Electron, Tauri, or a local web app/PWA wrapper. The app should be treated as an
    example client for the content editing API, not as a replacement for Wagtail admin.
  - Done when: there is a small prototype or design note showing how the app would authenticate, list content,
    edit drafts, preview posts, sync changes, and handle conflicts.

- [ ] Anonymous comment author edit hard limits
  - PRD: [backlog/2026-06-21-anonymous-comment-self-editing.md](backlog/2026-06-21-anonymous-comment-self-editing.md)
  - Status: implemented and tested (reviewed clean) — backend, browser frontend (templates + AJAX JS), and user
    docs/release notes all landed.
  - Scope: decide whether to add the deferred persistent edit-count cap, configurable hard time-window, both, or
    neither for the already shipped session-bound author edit/delete feature.
  - Done when: the decision is recorded and any accepted limit has settings, validation/checks, tests, docs, and
    release notes.

## Later

- [ ] Model-layer decoupling (architecture review H1/H2/M1/M8)
  - Notes: [backlog/2026-07-02-architecture-review.md](backlog/2026-07-02-architecture-review.md), plan
    [docs/superpowers/plans/2026-07-02-model-layer-decoupling-phase1.md](docs/superpowers/plans/2026-07-02-model-layer-decoupling-phase1.md)
  - Status: phase 1 landed on 2026-07-02 — `HtmxHttpRequest` lives in `cast/http_types.py` (models no longer import
    from views), `get_description` is side-effect free, `Video.save` is transactional, and `Post.save` has
    `sync_media`/`create_renditions` opt-outs.
  - Scope: phase 2 — extract description rendering and media derivation into presenter/service modules (and decide
    on async), invert the remaining model→blocks/filters imports, fix the mixed blog-index snapshot N+1 with a
    query-count test (M8).
  - Done when: save-side effects are explicit service calls, description rendering lives outside the model, and the
    mixed-queryset render path has a zero-/low-query assertion.

- [ ] Transcript domain extraction (architecture review H3/M9)
  - Notes: [backlog/2026-07-02-architecture-review.md](backlog/2026-07-02-architecture-review.md)
  - Scope: extract the WebVTT/Podlove/DOTe read-rewrite logic from the 1575-line `Transcript` model into per-format
    handler modules, move speaker-mapping/known-speaker orchestration into a service, and replace the 150-line
    `transcript.edit` POST action dispatcher with an action→handler map that calls that service.
  - Done when: `Transcript` is fields plus thin delegation, each format's quirks live in one module with focused
    tests, and the edit view dispatches declaratively.

- [ ] Deduplicate media admin views (architecture review H4)
  - Notes: [backlog/2026-07-02-architecture-review.md](backlog/2026-07-02-architecture-review.md)
  - Scope: extract a generic media viewset/factory parametrized by model, form, and template for the near-identical
    audio/video/transcript index/add/edit/delete/chooser views; align the drifted chooser pagination (`per_page=10`
    vs `CHOOSER_PAGINATION`).
  - Done when: one shared implementation serves all three media types, the pagination drift is resolved, and the
    chooser modal workflows keep passing their existing tests.

- [ ] Consolidate CAST_* settings resolution (architecture review M2, M12)
  - Related to: Documentation polish pass.
  - Scope: converge the five-plus settings mechanisms on the `appsettings.__getattr__` pattern (fold in the Voxhelm
    helper chain and the ~51 inline `getattr(settings, ...)` defaults; drop the app-ready global-settings mutation),
    and document the twelve undocumented `CAST_*` settings in `docs/reference/settings.rst`.
  - Done when: one accessor owns defaults, `check_cast_setting_types` derives from it instead of a parallel table,
    and every user-facing setting is documented.

- [ ] Voxhelm optional subpackage (architecture review M3)
  - Notes: [backlog/2026-07-02-architecture-review.md](backlog/2026-07-02-architecture-review.md)
  - Scope: split `voxhelm.py` into a `voxhelm/` subpackage (client, service, task refs, settings), break the
    models↔voxhelm circular imports, and evaluate a `[transcripts]`-style optional extra so `django-tasks` and the
    Voxhelm admin wiring activate only when configured.
  - Done when: the cycle is gone (no function-body imports papering it over), the subpackage boundaries match the
    three concerns, and the optional-extra decision is recorded.

- [ ] Legacy API consolidation (architecture review M4 remainder, M5)
  - Related to: Consider stricter mypy annotation checks (feeds.py is the shared offender).
  - Scope: freeze and document `api/views.py` as legacy, migrate still-used endpoints to the editor API conventions
    (structured errors, explicit scopes/permissions, JSON responses from `VideoCreateView`), and dedupe `feeds.py`
    (shared `item_description`/`item_link`/`write()`, typed XML handlers, `item_pubdate`/`item_guid` for the blog
    feed).
  - Done when: no endpoint relies on ad-hoc error shapes or bare-text responses, and `feeds.py` has one copy of the
    shared logic with mypy-clean signatures.

- [ ] Packaging and test-suite hygiene (architecture review M6/M7/M10/M11 remainder)
  - Notes: [backlog/2026-07-02-architecture-review.md](backlog/2026-07-02-architecture-review.md)
  - Scope: move the test settings module (committed SECRET_KEY, `tests.urls` ROOT_URLCONF) out of the shipped
    package and rename `dev_settings.py` to match its feature-flag role (M6); add an explicit type discriminator to
    the repository cache serialization instead of key-sniffing in three places (M7); split the largest test modules
    and the 906-line conftest into per-directory packages (M10); audit theme-/dev-only runtime dependencies and
    factor the duplicated tox env deps into a base env (M11 remainder).
  - Done when: `pip install django-cast` ships no test-only settings, cache deserialization branches on a stored
    type field, and no test module exceeds ~1000 lines without a local conftest.

- [ ] Editor API remote media import safety design
  - PRD:
    [backlog/2026-06-19-programmatic-content-editing-api.md](backlog/2026-06-19-programmatic-content-editing-api.md)
    (see Open Questions)
  - Status: deferred for now.
  - Scope: design how editor clients could import images/media from remote URLs with explicit server-side validation
    (SSRF protection, allowed schemes/hosts, size/content-type limits, the existing editor probe budget) so it is useful
    for agents but safe for production sites.
  - Done when: the safety constraints, request/response contract, and reuse of existing media validation/probing are
    documented, with a recommended first implementation slice or an explicit deferral.

- [ ] Editor API media replacement workflows
  - PRD:
    [backlog/2026-06-19-programmatic-content-editing-api.md](backlog/2026-06-19-programmatic-content-editing-api.md)
    (see Open Questions)
  - Related to: the `media_replace` management command and media durability work.
  - Scope: decide whether editor media endpoints should support replacing an existing media object's file (versus only
    creating new objects), and how that interacts with references from published pages and stored renditions.
  - Done when: the decision and, if accepted, a safe replacement contract (permissions, reference safety, cleanup) are
    documented or the option is explicitly deferred.

- [ ] Editor API Markdown convenience input
  - PRD:
    [backlog/2026-06-19-programmatic-content-editing-api.md](backlog/2026-06-19-programmatic-content-editing-api.md)
    (see Body Serialization, Tier 2)
  - Scope: add an optional `overview_markdown`/`detail_markdown` convenience input converted server-side into the
    canonical block list, behind an optional dependency so the Markdown parser is not forced onto all installs.
  - Done when: the optional-dependency boundary and conversion policy are documented, the structured block list stays
    canonical, and tests cover the conversion plus the dependency-absent path.

- [ ] Editor API embed body block support
  - PRD:
    [backlog/2026-06-19-programmatic-content-editing-api.md](backlog/2026-06-19-programmatic-content-editing-api.md)
    (see Body Serialization)
  - Scope: add `embed` as an author-facing body block in the editor converter, specifying URL validation and provider
    behavior. Stored `embed` blocks are currently preserved only as unsupported placeholders.
  - Done when: the `embed` value/validation contract is specified, the converter accepts and round-trips it, and tests
    cover valid/invalid embed URLs and provider behavior.

- [ ] Default theme design improvements
  - Scope: improve the built-in theme design while keeping theme contracts stable for existing sites.
  - Done when: the default theme feels more polished, remains accessible, and existing theme overrides keep working.

- [ ] Add view transitions to existing themes
  - Scope: add progressive-enhancement page/view transitions for the built-in themes.
  - Done when: navigation feels smoother where supported, unsupported browsers keep the current behavior, and motion
    can respect reduced-motion preferences.

- [ ] Paged feeds
  - Scope: add paginated feed support so large podcasts and blogs can expose older posts or episodes without huge
    feed responses.
  - Done when: feed pagination behavior is documented, feed URLs are stable, and tests cover large archives and
    existing feed compatibility.

- [ ] Chapter marks in podcast feeds
  - Related to: Paged feeds, Podcast feed import, and the custom audio player.
  - Scope: expose existing `ChapterMark` data in the podcast RSS/Atom feeds using both Podlove Simple Chapters
    (`<psc:chapters>` with inline `<psc:chapter start=… title=…/>` elements, `xmlns:psc="http://podlove.org/simple-chapters"`)
    and Podcasting 2.0 chapters (`<podcast:chapters>` referencing an external `application/json+chapters` document in the
    existing `xmlns:podcast` namespace).
  - Notes: chapter data already exists per episode (`ChapterMark`, parsed from audio files and shown in the player) but is
    not written to the feed yet; feed namespaces/elements live in `src/cast/feeds.py` (`ITunesElements`,
    `PodcastIndexElements`). Open question for the PC2.0 form: where to serve the chapters JSON file from (new view/URL,
    similar to the existing transcript URLs) versus only emitting inline Podlove chapters. Keep emission conditional so
    episodes without chapter marks produce no extra elements.
  - Done when: feeds emit Podlove Simple Chapters inline and a `podcast:chapters` reference (with the JSON document served
    from a stable URL), namespaces are declared, behavior is documented, and tests cover episodes with and without chapter
    marks plus existing-feed compatibility.

- [ ] Podcast feed import
  - Notes: [backlog/2026-05-18-podcast-feed-import.md](backlog/2026-05-18-podcast-feed-import.md)
  - Status: deferred for now.
  - Related to: Revisit onboarding and authoring workflows.
  - Scope: design and implement a safe way to import an existing public podcast RSS feed into django-cast.
  - Done when: there is a documented import workflow, clear field-mapping rules, duplicate detection based on stable
    feed item identifiers, tests with representative podcast feeds, and guidance for unsupported metadata.

- [ ] Tags/categories and faceted navigation completion
  - Scope: decide whether tags, categories, or both should remain public organization primitives and finish the beta
    faceted navigation behavior.
  - Done when: the intended model is documented, stale beta wording is removed, and filters/navigation have focused
    tests.

- [ ] Promote soft-required theme templates to strict requirements
  - Scope: make currently soft-required theme templates strictly required after the deprecation period.
  - Done when: theme discovery enforces the final required template set and the theme docs/release notes explain the
    migration path.

- [ ] Persistent player generic rollout decision
  - Notes: [backlog/2026-06-08-persistent-player-staging.md](backlog/2026-06-08-persistent-player-staging.md)
  - Related to: [backlog/2026-06-02-custom-audio-player.md](backlog/2026-06-02-custom-audio-player.md)
  - Scope: decide whether the python-podcast staging proof should become a reusable django-cast/cast-bootstrap5 API,
    remain python-podcast-specific, or be closed as a staging-only experiment.
  - Done when: the generic theme contract/API work is split into concrete implementation items or explicitly deferred.

- [ ] Podcast contributor follow-up options
  - Notes: [backlog/2026-05-12-podcast-episode-contributors.md](backlog/2026-05-12-podcast-episode-contributors.md)
  - Scope: consider default contributors, public contributor detail pages, assignment notes, broader role taxonomy,
    and API fields for external themes.
  - Done when: follow-up options are either split into concrete ready items or explicitly deferred.

- [ ] Consider stricter mypy annotation checks
  - Scope: evaluate enabling `disallow_incomplete_defs = true` and/or `disallow_untyped_defs = true` incrementally,
    likely per module first instead of project-wide.
  - Notes: a quick probe showed `disallow_incomplete_defs` currently reports 123 errors in 30 files, while
    `disallow_untyped_defs` reports 219 errors in 48 files; `src/cast/feeds.py` alone reports 21 and 24 errors
    respectively.
  - Done when: the preferred strictness level and rollout strategy are documented, and at least one initial
    module is either cleaned up or explicitly excluded/deferred.

- [ ] Documentation polish pass
  - Notes: [backlog/2025-07-11-documentation-polish.md](backlog/2025-07-11-documentation-polish.md)
  - Scope: retire the stale documentation task list by checking remaining docs structure, links, and warnings.
  - Done when: docs build cleanly and remaining docs TODOs are either implemented or intentionally removed.
