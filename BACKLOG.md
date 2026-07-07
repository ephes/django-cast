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

- [ ] **High priority — standalone `heading` block renders as plain text; reconcile with rich-text headings**
  - Scope: the standalone `heading` block is a template-less, single-level `CharBlock`,
    so `{% include_block %}` emits only its escaped string — it renders as body text with
    no heading tag. Rich text (`paragraph`) already supports multi-level `<h2>/<h3>/<h4>`
    headings that render correctly. Decide whether to deprecate the `heading` block in
    favour of rich-text headings, give it an author-selectable level, or render it at a
    fixed level — and give it a template so it stops rendering flat.
  - Note: heading level is the author's choice (content has an h2/h3/h4 outline); no
    fixed level fits all headings. daybook can get correct headings today by authoring
    them as rich text instead of `heading` blocks.
  - Related to: post-body block rendering. Cross-repo: a leveled `heading` block would
    change the daybook overview heading contract (`value` string → `{text, level}`).
  - Done when: headings render as real, correctly-levelled elements in the `plain` and
    `bootstrap4` themes; the heading-block-vs-rich-text roles are documented and tested;
    release notes are updated.
  - Detail: [backlog/2026-07-07-overview-heading-block-rendering.md](backlog/2026-07-07-overview-heading-block-rendering.md)

- [ ] Choose next implementation slice
  - Scope: pick the next small, concrete item from Research / Shaping or Later based on current project needs.
  - Status: the 2026-07-06 slice addressed quickstart template drift under "Revisit onboarding and authoring
    workflows"; choose a fresh slice when this backlog is next revisited.
  - Done when: the chosen item has a clear first slice, expected files/tests, and any sibling-repo checks identified.

## Research / Shaping

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
    top of the podcast feed import workflow. The quickstart template-drift implementation slice landed on
    2026-07-06: generated project files now come from packaged templates and a smoke test verifies the generated
    project boots through Django's system check.
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
  - Notes: [backlog/2026-07-02-architecture-review.md](backlog/2026-07-02-architecture-review.md)
  - Status: phase 1 landed on 2026-07-02 — `HtmxHttpRequest` lives in `cast/http_types.py` (models no longer import
    from views), `get_description` is side-effect free, `Video.save` is transactional, and `Post.save` has
    `sync_media`/`create_renditions` opt-outs.
  - Scope: phase 2 — extract description rendering and media derivation into presenter/service modules (and decide
    on async), and invert the remaining model→blocks/filters imports. (The mixed blog-index snapshot N+1 (M8) was
    fixed on 2026-07-02 with a flat-query-count guard test.)
  - Done when: save-side effects are explicit service calls and description rendering lives outside the model.

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

- [x] Chapter marks in podcast feeds
  - Related to: Paged feeds, Podcast feed import, and the custom audio player.
  - Scope: expose existing `ChapterMark` data in the podcast RSS/Atom feeds using both Podlove Simple Chapters
    (`<psc:chapters>` with inline `<psc:chapter start=… title=…/>` elements, `xmlns:psc="http://podlove.org/simple-chapters"`)
    and Podcasting 2.0 chapters (`<podcast:chapters>` referencing an external `application/json+chapters` document in the
    existing `xmlns:podcast` namespace).
  - Notes: implemented 2026-07-07 with N+1-safe feed snapshot chapter data, inline Podlove Simple Chapters, and
    Podcasting 2.0 `application/json+chapters` endpoint references at stable audio-scoped URLs.
  - Done when: feeds emit Podlove Simple Chapters inline and a `podcast:chapters` reference (with the JSON document served
    from a stable URL), namespaces are declared, behavior is documented, and tests cover episodes with and without chapter
    marks plus existing-feed compatibility. Completed in 0.2.62.

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
  - Design: [backlog/2026-06-09-play-button-and-player-view-transition-design.md](backlog/2026-06-09-play-button-and-player-view-transition-design.md)
    (play-affordance and inline→persistent player view-transition morph; includes open questions)
  - Related to: [backlog/2026-06-02-custom-audio-player.md](backlog/2026-06-02-custom-audio-player.md)
  - Scope: decide whether the python-podcast staging proof should become a reusable django-cast/cast-bootstrap5 API,
    remain python-podcast-specific, or be closed as a staging-only experiment.
  - Done when: the generic theme contract/API work is split into concrete implementation items or explicitly deferred.

- [ ] Podcast contributor follow-up options
  - Notes: [backlog/2026-05-12-podcast-episode-contributors.md](backlog/2026-05-12-podcast-episode-contributors.md)
  - Scope: consider default contributors, public contributor detail pages, assignment notes, broader role taxonomy,
    and API fields for external themes.
  - Done when: follow-up options are either split into concrete ready items or explicitly deferred.

- [x] Consider stricter mypy annotation checks
  - Scope: evaluate enabling `disallow_incomplete_defs = true` and/or `disallow_untyped_defs = true` incrementally,
    likely per module first instead of project-wide.
  - Notes: implemented on 2026-07-06. The initial re-probe showed `disallow_incomplete_defs` at 130 errors in 33
    files and `disallow_untyped_defs` at 239 errors in 55 files, so the rollout started with per-module overrides.
    The first focused `src/cast/feeds.py` probe reported 9 errors for `disallow_incomplete_defs` and 10 errors for
    `disallow_untyped_defs`; that cleanup landed with both flags enabled for `cast.feeds`. Subsequent slices cleaned
    the remaining modules, ending with `cast.blocks`, `cast.models.pages`, and `cast.views.styleguide`. The final
    2026-07-06 project-level probes for both flags passed with no issues in 142 source files, so the rollout now
    enables `disallow_incomplete_defs = true` and `disallow_untyped_defs = true` globally in `pyproject.toml`.
  - Done when: the preferred strictness level and rollout strategy are documented, and at least one initial
    module is either cleaned up or explicitly excluded/deferred. Completed with no deferred source modules.

- [x] Documentation polish pass
  - Notes: [backlog/2025-07-11-documentation-polish.md](backlog/2025-07-11-documentation-polish.md)
  - Scope: retire the stale documentation task list by checking remaining docs structure, links, and warnings.
  - Notes: completed 2026-07-07. Consistency pass over the current docs tree: `index.rst` navigation is
    already well-structured, no orphaned pages, and the `just docs` (`sphinx -b html -W`) build is clean.
    Fixed the one latent nitpicky broken reference (a stray `:class:`Audio`` domain role that could not
    resolve without autodoc, now a literal) so the tree is also clean under `sphinx -n`, and turned the
    illustrative `localhost:8000` example URLs in the tutorial/installation guides into inline literals so
    they no longer render as dead links. Remaining beta wording in `content/organization.rst` is owned by
    the "Tags/categories and faceted navigation completion" item, not this pass.
  - Done when: docs build cleanly and remaining docs TODOs are either implemented or intentionally removed.
