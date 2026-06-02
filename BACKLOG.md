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

## Ready

- [ ] Authorize public audio and transcript object endpoints
  - Scope: require public Podlove audio and transcript responses to be anchored to a live, public episode that
    references the requested `Audio` or `Transcript`, instead of serving raw object IDs directly.
  - Affected routes include `/api/audios/podlove/<audio_pk>/`, `/api/audios/podlove/<audio_pk>/post/<post_pk>/`,
    `/transcripts/podlove/<transcript_pk>/`, `/transcripts/podcastindex/<transcript_pk>/`,
    `/transcripts/vtt/<transcript_pk>/`, and `/transcripts/html/<transcript_pk>/`.
  - Done when: bare or mismatched object IDs return 404, Wagtail page view restrictions are respected, and focused
    regression tests cover draft, unpublished, unattached, and restricted episode/audio/transcript cases.

- [ ] Repository read-model cleanup experiment
  - Notes: [backlog/2026-04-18-repository-readmodels.md](backlog/2026-04-18-repository-readmodels.md)
  - Scope: try local typed read shapes around the repository layer before considering `django-mantle`.
  - Done when: a narrow branch proves whether typed read shapes clarify repository logic without changing
    template contracts or query counts.

## Research / Shaping

- [ ] Typeahead search
  - Scope: research whether current full-text search is fast enough for typeahead, what API/frontend surface is
    needed, and how to keep it optional for themes.
  - Done when: there is a short implementation note with benchmark expectations, proposed endpoints or context
    contracts, accessibility constraints, and a first implementation slice.

- [ ] Podlove Web Player replacement
  - Scope: research replacing the current Podlove Web Player integration with a maintainable audio player path.
    Candidates include [Able Player](https://github.com/ableplayer/ableplayer) and a custom HTML/CSS/Web Component
    implementation.
  - Done when: tradeoffs are documented for accessibility, transcript/chapter support, theming, dependencies,
    bundle size, migration impact, and the preferred first slice.

- [ ] Revisit onboarding and authoring workflows
  - Scope: review the existing `django-cast-quickstart`, `example/scripts/bootstrap_example_data.py`, and
    `ensure_reference_site` workflows and decide what onboarding should mean for django-cast users: new project
    setup, local development setup, editor onboarding, or assisted content authoring.
  - Notes: include "try django-cast with your own podcast feed" as one possible getting-started path, built on
    top of the podcast feed import workflow.
  - Done when: the current workflows are documented in one place, gaps are listed, and follow-up items are split
    into concrete implementation tasks.

- [ ] Podcast feed import
  - Notes: [backlog/2026-05-18-podcast-feed-import.md](backlog/2026-05-18-podcast-feed-import.md)
  - Related to: Revisit onboarding and authoring workflows.
  - Scope: design and implement a safe way to import an existing public podcast RSS feed into django-cast.
  - Done when: there is a documented import workflow, clear field-mapping rules, duplicate detection based on
    stable feed item identifiers, tests with representative podcast feeds, and guidance for unsupported metadata.

- [ ] Programmatic content editing API
  - Scope: research and design an API that lets trusted tools or agents create, update, draft, preview, publish,
    and revise posts or episodes programmatically.
  - Notes: target use cases include agents turning assorted Markdown notes on disk into weeknotes, updating draft
    posts after review, and modifying existing content without direct database access.
  - Done when: there is a proposed API shape covering authentication, permissions, draft vs live revisions,
    StreamField/body serialization, media attachment handling, conflict detection, validation errors, and a first
    implementation slice plan with test scenarios for create/update/publish workflows.

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

## Later

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

- [ ] Tags/categories and faceted navigation completion
  - Scope: decide whether tags, categories, or both should remain public organization primitives and finish the beta
    faceted navigation behavior.
  - Done when: the intended model is documented, stale beta wording is removed, and filters/navigation have focused
    tests.

- [ ] Promote soft-required theme templates to strict requirements
  - Scope: make currently soft-required theme templates strictly required after the deprecation period.
  - Done when: theme discovery enforces the final required template set and the theme docs/release notes explain the
    migration path.

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
