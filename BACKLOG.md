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
- The implemented typeahead architecture, performance measurements, and UX rationale remain available in
  [backlog/2026-07-16-typeahead-search.md](backlog/2026-07-16-typeahead-search.md).

## Research / Shaping

- [ ] Paged feeds — research and reviewed migration concept
  - Design record: [backlog/2026-09-19-paged-feeds.md](backlog/2026-09-19-paged-feeds.md)
  - First approved investigation: [baseline and contracts](backlog/2026-09-19-paged-feeds-slice1.md).
  - Implemented and reviewed: [selection service](backlog/2026-09-19-paged-feeds-selection.md).
    Five-minute cache staleness is accepted; no cache repair is required.
  - Next slice: additive opt-in RSS/Atom endpoints; no public paged endpoints exist yet.
  - Scope: scalable RSS/Atom feed infrastructure, documented client-compatibility evidence with unknowns recorded, additive opt-in endpoints,
    and an explicit migration/rollback policy for existing complete feeds. No template work.
  - Gate: research, concept and implementation slices must be independently reviewed and approved before coding.
  - Done when: approved slices are implemented with stable URLs/identities, documented pagination/migration
    behavior, large-archive tests and existing-feed compatibility checks. Research approval alone does not close this item.

- [ ] Local authoring and sync workflow
  - Design record:
    [backlog/2026-07-09-cast-studio-product-boundary.md](backlog/2026-07-09-cast-studio-product-boundary.md)
  - Scope: research whether django-cast should support a local-first editing workflow where content can be pulled
    from a production site, edited locally, previewed, and synced back safely.
  - Notes: compare API-based sync, database snapshot/restore, Wagtail revisions, management commands, and a
    desktop/app wrapper. Avoid direct production database mutation as the default path. This is not a dependency for
    Cast Studio's local Electron playground: that product packages the complete Django/Wagtail site and edits its local
    database through Wagtail. A future **Put this site online** action still requires a separate portable import or
    hosted-trial design and must never overwrite a production database with local SQLite.
  - Done when: tradeoffs are documented for data ownership, conflict resolution, media files, revision history,
    authentication, rollback, and production safety, with a recommended first slice.

- [ ] Example external desktop authoring client
  - Depends on: programmatic content editing API and local authoring/sync workflow shaping.
  - Related to:
    [backlog/2026-07-09-cast-studio-product-boundary.md](backlog/2026-07-09-cast-studio-product-boundary.md)
  - Scope: evaluate whether an example desktop client for a remote django-cast site would improve offline, multi-site,
    specialized media, or agent-assisted authoring workflows.
  - Notes: this is distinct from Cast Studio. Cast Studio is initially a distribution/lifecycle shell around a complete
    local Django/Wagtail site and uses Wagtail admin as its editor; it does not need the editor API or a second content
    editor for its first proof. Candidates for this separate external client include Electron, Tauri, or a PWA.
  - Done when: concrete demand exists and there is a small prototype or design note showing how the client would
    authenticate, list content, edit drafts, preview posts, sync changes, and handle conflicts.

## Later

- [ ] Historical editor API rich-text audit tooling — deferred
  - Design record:
    [backlog/2026-09-07-editor-richtext-sanitization.md](backlog/2026-09-07-editor-richtext-sanitization.md)
  - Decision (2026-09-19): the maintainer confirmed that the pre-fix editor API was used only in development,
    not on the production sites. No known production exposure through that path justifies building tooling now.
  - Revisit only when a deployment with content written through the pre-fix API is identified.
  - If resumed: inspect published content, drafts, and restorable revisions read-only; distinguish potentially
    unsafe markup from harmless normalization and document remediation without silently rewriting history.

- [ ] Require publish revision binding in the next editor API version
  - Decision record: [backlog/2026-09-08-wagtail-v3-editor-api.md](backlog/2026-09-08-wagtail-v3-editor-api.md)
    (follow-up 5); deferral recorded in [backlog/2026-09-07-security-review.md](backlog/2026-09-07-security-review.md)
  - Resume notes: "Resuming the work" in the decision record (current state, run recipes, suggested order)
  - Depends on: an editor API versioning decision.

- [ ] Revisit Wagtail v3 adoption
  - Decision record: [backlog/2026-09-08-wagtail-v3-editor-api.md](backlog/2026-09-08-wagtail-v3-editor-api.md)
    ("Revisit triggers"; follow-ups 6 and 7)
  - Resume notes: "Resuming the work" in the decision record (current state, run recipes, suggested order)
  - Scope: re-run the test-only experiment when v3 is no longer a preview, the supported Wagtail floor includes
    it, and upstream offers request-context serialization and revision-bound writes. Optional preparatory work:
    let `HtmlField` tolerate missing serializer context, and add editor schedule input only if a client needs it.
    Upstream reports for the recorded v3 gaps need separate confirmation before filing.

- [ ] Editor API preservation of paragraphs containing inline media
  - Related design:
    [backlog/2026-09-07-editor-richtext-sanitization.md](backlog/2026-09-07-editor-richtext-sanitization.md)
  - Scope: consider exposing existing paragraphs with inline media as unsupported placeholders, so clients can
    preserve them while editing neighboring blocks. New inline embeds remain rejected by the write API.
  - Done when: the read/preservation contract is specified and tested without allowing clients to forge or change
    preserved content or bypass sanitization on new writes.

- [ ] Editor API remote media import safety design
  - PRD:
    [backlog/2026-06-19-programmatic-content-editing-api.md](backlog/2026-06-19-programmatic-content-editing-api.md)
    (see Open Questions)
  - Status: deferred for now.
  - Prerequisite implemented: the shared upload and bounded-fetch contracts are documented in
    [the media-ingestion service plan](backlog/2026-09-16-media-ingestion-service.md); remote imports must add
    connect-time address pinning and redirect revalidation before accepting attacker-controlled URLs.
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
  - Status: deferred (reconfirmed 2026-07-07). The converter change is small, but the effort and risk are
    concentrated in the oEmbed provider fetch at author time (network egress / SSRF surface, mocked-provider
    tests) — a security decision about a block type the maintainer does not use. The one candidate consumer,
    daybook, posts overview author blocks through this API but renders archive items (incl. watched videos) as
    prose links by design, not embeds, so there is no consumer demand today. Revisit only if daybook (or another
    editor-API client) decides to render items as embedded players/cards; if so, lean toward store-the-URL /
    defer-resolution-to-render validation to avoid per-post provider fetches.
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

- [ ] Podcast feed import
  - Notes: [backlog/2026-05-18-podcast-feed-import.md](backlog/2026-05-18-podcast-feed-import.md)
  - Related design:
    [backlog/2026-07-09-cast-studio-product-boundary.md](backlog/2026-07-09-cast-studio-product-boundary.md)
  - Status: deferred for django-cast core and not part of Cast Studio's first blog proof. The `../django-chat`
    site-specific importer is now the concrete reference for provenance, idempotency, limited/dry-run operation,
    streaming media copy, sanitization, SSRF protection, and fixture-only tests. Cast Studio should prove a generic
    RSS-first contract in its own repo before shared services or models are promoted into django-cast.
  - Scope: design and implement a safe way to import an existing public podcast RSS feed into django-cast.
  - Done when: there is a documented import workflow, clear field-mapping rules, duplicate detection based on stable
    feed item identifiers, tests with representative podcast feeds, and guidance for unsupported metadata.

- [ ] Promote soft-required theme templates to strict requirements
  - Scope: make currently soft-required theme templates strictly required after the deprecation period.
  - Done when: theme discovery enforces the final required template set and the theme docs/release notes explain the
    migration path.

- [ ] Podcast contributor follow-up options
  - Notes: [backlog/2026-05-12-podcast-episode-contributors.md](backlog/2026-05-12-podcast-episode-contributors.md)
  - Scope: consider default contributors, public contributor detail pages, assignment notes, broader role taxonomy,
    and API fields for external themes.
  - Done when: follow-up options are either split into concrete ready items or explicitly deferred.
