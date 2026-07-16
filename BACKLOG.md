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

## Research / Shaping

- [ ] Typeahead search
  - Scope: research whether current full-text search is fast enough for typeahead, what API/frontend surface is
    needed, and how to keep it optional for themes.
  - Done when: there is a short implementation note with benchmark expectations, proposed endpoints or context
    contracts, accessibility constraints, and a first implementation slice.

- [ ] Revisit onboarding and authoring workflows
  - Design record:
    [backlog/2026-07-09-cast-studio-product-boundary.md](backlog/2026-07-09-cast-studio-product-boundary.md)
  - Scope: review the existing `django-cast-quickstart`, `example/scripts/bootstrap_example_data.py`, and
    `ensure_reference_site` workflows and decide what onboarding should mean for django-cast users: new developer
    project setup, local development setup, editor onboarding, assisted content authoring, or an installed desktop
    product.
  - Notes: the paths are now deliberately separate. `django-cast-quickstart` remains developer-facing; the example
    bootstrap/reference site remain development and theme-test tooling; a private sibling Cast Studio product is
    researching an offline-capable, no-signup macOS Electron application for non-developers. Cast Studio's first proof
    is blog + image authoring through Wagtail, not a custom editor. Include "try django-cast with your own podcast
    feed" as a later Cast Studio/getting-started path built on the podcast feed import workflow. The quickstart
    template-drift implementation slice landed on 2026-07-06: generated project files now come from packaged templates
    and a smoke test verifies the generated project boots through Django's system check.
  - Done when: the current workflows and audiences are documented in one place, gaps are listed, Cast Studio-specific
    work is kept out of core unless it proves generic, and django-cast follow-ups are split into concrete implementation
    tasks.

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

- [ ] Model-layer decoupling (architecture review H1/H2/M1/M8)
  - Notes: [backlog/2026-07-02-architecture-review.md](backlog/2026-07-02-architecture-review.md)
  - Status: phase 1 landed on 2026-07-02 — `HtmxHttpRequest` lives in `cast/http_types.py` (models no longer import
    from views), `get_description` is side-effect free, `Video.save` is transactional, and `Post.save` has
    `sync_media`/`create_renditions` opt-outs. Post-description rendering moved to `cast.presenters` on 2026-07-16;
    `Post.get_description()` remains only as a compatibility wrapper.
  - Scope: phase 2 remaining — extract media derivation into service modules (and decide on async), and invert the
    remaining model→blocks/filters imports. (The mixed blog-index snapshot N+1 (M8) was fixed on 2026-07-02 with a
    flat-query-count guard test.)
  - Done when: save-side effects are explicit service calls and the remaining inverted presentation imports are gone.

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

- [ ] Paged feeds
  - Scope: add paginated feed support so large podcasts and blogs can expose older posts or episodes without huge
    feed responses.
  - Done when: feed pagination behavior is documented, feed URLs are stable, and tests cover large archives and
    existing feed compatibility.

- [ ] Podcast feed import
  - Notes: [backlog/2026-05-18-podcast-feed-import.md](backlog/2026-05-18-podcast-feed-import.md)
  - Related design:
    [backlog/2026-07-09-cast-studio-product-boundary.md](backlog/2026-07-09-cast-studio-product-boundary.md)
  - Status: deferred for django-cast core and not part of Cast Studio's first blog proof. The `../django-chat`
    site-specific importer is now the concrete reference for provenance, idempotency, limited/dry-run operation,
    streaming media copy, sanitization, SSRF protection, and fixture-only tests. Cast Studio should prove a generic
    RSS-first contract in its own repo before shared services or models are promoted into django-cast.
  - Related to: Revisit onboarding and authoring workflows.
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
