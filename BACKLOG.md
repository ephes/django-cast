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

- (none — the editor API episode publish action shipped; see `docs/releases/0.2.61.rst`. Pick the next item from
  Research / Shaping.)

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
    top of the podcast feed import workflow.
  - Done when: the current workflows are documented in one place, gaps are listed, and follow-up items are split
    into concrete implementation tasks.

- [ ] Podcast publishing metadata follow-up triage
  - PRD: [backlog/2026-06-18-podcast-publishing-metadata.md](backlog/2026-06-18-podcast-publishing-metadata.md)
  - Status: first implementation slice landed for optional episode number, episode type, podcast-scoped seasons,
    Wagtail editing, feed tags, validation, repository/cache serialization, docs, and release notes. The automatic
    podcast episode numbering follow-up also landed for opt-in podcast-scoped first-publish assignment.
  - Related to: Podcast feed import and podcast contributor follow-up options.
  - Scope: decide the remaining deferred questions in the PRD: season editing shape, duplicate number policy, legacy
    import values, and possible channel-level `itunes:type` support.
  - Done when: the remaining PRD questions are either split into concrete implementation items under
    `Next`/`Ready`/`Later` or explicitly deferred in the PRD.

- [ ] Editor API rendered-preview endpoint
  - PRD:
    [backlog/2026-06-19-programmatic-content-editing-api.md](backlog/2026-06-19-programmatic-content-editing-api.md)
  - Related to: Editor API scoped-token / IndieAuth scope mapping.
  - Status: shaping. The shipped editor API returns an admin-session `preview_url` that only works for a human in a
    Wagtail admin session; token-only/non-admin clients cannot self-render a draft.
  - Scope: design a server-rendered draft preview path for token-only/non-admin editor clients (likely a
    `GET /api/editor/posts/{id}/preview/`-style endpoint returning rendered draft HTML), preserving Wagtail page
    permissions and not leaking unpublished content beyond the caller's permissions.
  - Done when: there is a decision on whether rendered preview is needed before scoped-token auth ships, a proposed
    endpoint/response contract, the permission model, and a first implementation slice or an explicit deferral with
    rationale.

- [ ] Editor API scoped-token / IndieAuth scope mapping
  - PRD:
    [backlog/2026-06-19-programmatic-content-editing-api.md](backlog/2026-06-19-programmatic-content-editing-api.md)
    (see Authentication And Permissions, Open Questions)
  - Design: [backlog/2026-06-30-editor-api-scoped-token-auth.md](backlog/2026-06-30-editor-api-scoped-token-auth.md)
  - Status: **shaping complete** — decided two logical scopes (`write`/`publish`, reads scope-free), a per-method
    `required_scopes` mapping enforced by a generic `HasEditorScope` class (so mixed `GET`/`PATCH` views resolve
    per method), session and unscoped-token fallback to pure Wagtail permissions, configurable `CAST_EDITOR_SCOPES`,
    and an `insufficient_scope` 403 error. Ready to promote to an implementation slice (see the design's "First
    implementation slice").
  - Related to: Editor API rendered-preview endpoint — the design resolves that rendered preview is **not** a
    blocker for scoped-token auth.

- [ ] Editor API remote media import
  - PRD:
    [backlog/2026-06-19-programmatic-content-editing-api.md](backlog/2026-06-19-programmatic-content-editing-api.md)
    (see Open Questions)
  - Status: shaping. Blocked on safety constraints before any implementation.
  - Scope: design how editor clients could import images/media from remote URLs with explicit server-side validation
    (SSRF protection, allowed schemes/hosts, size/content-type limits, the existing editor probe budget) so it is useful
    for agents but safe for production sites.
  - Done when: the safety constraints, request/response contract, and reuse of existing media validation/probing are
    documented, with a recommended first implementation slice or an explicit deferral.

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

- [ ] Editor API optional If-Match/ETag conflict tokens
  - PRD:
    [backlog/2026-06-19-programmatic-content-editing-api.md](backlog/2026-06-19-programmatic-content-editing-api.md)
    (see Conflict Detection)
  - Scope: add `If-Match`/ETag as an equivalent transport for the existing `base_revision_id` conflict semantics on
    `PATCH`, without changing the JSON-body contract that already works.
  - Done when: the header transport maps to the same `revision_conflict` behavior, both transports are documented, and
    tests cover header- and body-supplied base revisions.

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

- [ ] Optimize public transcript speaker sanitization copies
  - Scope: avoid deep-copying large transcript structures on public player/transcript requests when all speaker
    labels are already public or when no speaker metadata is present.
  - Done when: Podlove and DOTe sanitizers preserve current output, keep stored files untouched, and skip copying
    for no-op requests with focused tests.

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
