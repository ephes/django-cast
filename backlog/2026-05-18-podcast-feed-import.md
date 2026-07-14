# Podcast Feed Import

Status: deferred for django-cast core. A private sibling Cast Studio product may
first prove a generic RSS-first importer after its initial blog-only desktop
proof; see
[2026-07-09-cast-studio-product-boundary.md](2026-07-09-cast-studio-product-boundary.md).
When this resumes, the first decision is where source feed identity, feed item
identifiers, enclosure URLs, and media handling policy are stored so duplicate
detection can be implemented safely.

## Summary

Add a podcast import workflow that can read a public podcast RSS feed and create
or update django-cast podcast content from it.

Keep the first slice focused on a safe, inspectable import path. The main use
case is migration from an existing podcast host, but the same feature should also
support onboarding: a new user can try django-cast locally with a small subset of
their real podcast content instead of generic sample data.

The generated django-cast podcast feed is probably enough as the first export
format. Treat a separate archive/export command as an open question until there
is a concrete gap that the public feed cannot cover.

## Motivation

People evaluating django-cast may already have a podcast. Importing a few
episodes from their public feed would make the local quickstart more realistic
than sample content, while a full import path would also make migration less
manual.

This should not be limited to onboarding. The import should be useful as a
standalone management workflow that can be run against an existing django-cast
site.

## Related Backlog

- Revisit onboarding and authoring workflows.
- Paged feeds, if large imported archives expose feed size or pagination limits.
- Podcast contributor follow-up options, if feeds include people metadata that
  maps to django-cast contributors.

## Concrete Reference: Django Chat

The `../django-chat` sibling now provides a production-shaped, site-specific
importer worth using as the implementation reference rather than starting from
abstract choices. It demonstrates:

- immutable normalized RSS/Simplecast source dataclasses before model writes;
- separate Podcast, Episode, and Audio provenance models;
- idempotent matching by RSS GUID and provider IDs/slugs;
- limited imports and a rollback-only management-command dry run;
- opt-in cover-image and streaming audio copy;
- source-reported versus actually copied byte accounting;
- deterministic collision-resistant storage names;
- explicit HTML sanitization before Wagtail RichText storage;
- imported hyperlink scheme validation;
- SSRF protection with redirect revalidation and connect-time DNS/IP pinning;
- fixture-backed tests that never depend on live network access.

The reference uses Python's standard XML parser and does not explicitly reject
DTDs or test XXE/entity-expansion attacks. A generic importer must add a hardened
XML parser boundary and fixtures rather than treating the reference as complete
for XML security.

Do not copy its site-specific assumptions into django-cast: fixed Django Chat
and Simplecast URLs/IDs, custom show-note block schema, project theme, source
links, and feed-cutover logic belong to that consumer.

A generic implementation should also improve on the reference where its product
scope requires it:

- build a pure read-only plan instead of writing then rolling back;
- scope item identifiers to the imported feed/podcast instead of assuming global
  GUID uniqueness;
- avoid title-only or episode-number-only adoption of existing pages;
- cap feed, artwork, individual media, and total import bytes;
- require per-field last-applied mapped values/digests so local-edit conflicts
  can be detected before reimport overwrites mapped fields;
- model partial media progress, cancellation, cleanup, and retry;
- show estimated disk use before copying audio.

## Next Shaping Slice

Before implementation, settle the import provenance and media policy:

- how an explicit user-selected existing Podcast/source owns a rerun, records
  safely confirmed feed URL changes, and avoids URL-only silent adoption;
- where to store stable feed item identifiers such as podcast-scoped GUIDs,
  canonical links, and enclosure URLs;
- implement the first provenance model in Cast Studio, as decided in
  [2026-07-09-cast-studio-product-boundary.md](2026-07-09-cast-studio-product-boundary.md);
  reconsider django-cast core only after multiple consumers prove a generic
  contract;
- whether enclosure URLs are provenance-only or downloaded into django-cast
  storage through an explicit option; do not silently hotlink remote audio;
- what duplicate detection runs on repeat imports, and how required per-field
  last-applied mapped values/digests identify local edits;
- what a pure dry-run/preview plan must show before database or storage writes;
- what hardened XML parser rejects DTDs/external entities and bounds entity
  expansion, and what response/media size, timeout, redirect, and SSRF limits
  apply;
- imported episodes must remain drafts while audio is absent, pending, failed,
  or canceled; decide whether an episode whose requested audio copy completed
  successfully is then published locally automatically or waits for explicit
  per-item confirmation.

This slice is done when the decisions above are recorded, at least two distinct
consumer feeds have fixtures, and the chosen repository's implementation can
move to `Ready` without assuming Simplecast.

## Candidate Generic Implementation Shape

The first implementation belongs to Cast Studio. Its product UI should call a
repository-local plan/apply service; a management command remains a useful test
and operator adapter. No django-cast core implementation is selected while this
item is deferred. If later evidence justifies promotion, a generic service could
expose a command such as:

```text
python manage.py import_podcast_feed <feed-url> --parent <page-id-or-slug> --limit 5 --dry-run
python manage.py import_podcast_feed <feed-url> --source <import-source-id> --limit 5 --dry-run
```

The Cast Studio implementation, and any later generic extraction, should support:

- fetching and parsing a public RSS podcast feed;
- dry-run output that shows which podcast and episodes would be created or
  updated;
- creating a Podcast page under a selected parent page when requested;
- creating Episode pages from feed items;
- preserving original publication dates;
- copying episode audio into local storage or deliberately importing metadata
  only; never silently hotlink remote enclosures;
- limiting imports for local trial setups, such as the latest 3 to 5 episodes;
- repeatable duplicate detection using stable feed item identifiers;
- clear reporting for unsupported feed metadata.

Prefer an explicit service with a management-command adapter over hidden
quickstart behavior. A future Cast Studio UI can call the same plan/apply service;
the quickstart or bootstrap path can call or document it later only if that
serves its developer audience.

## Field Mapping

Map only fields that django-cast can represent clearly.

Podcast-level candidates:

- feed title -> Podcast title
- feed subtitle or short iTunes summary -> Podcast subtitle, when the source
  value is clearly a short tagline
- feed description or long-form iTunes summary -> Podcast description
- feed author or iTunes author -> Podcast author
- owner email where present -> Podcast email
- iTunes artwork -> podcast artwork or cover image, depending on the final
  storage decision
- iTunes categories -> Podcast iTunes categories, serialized to django-cast's
  nested JSON string shape
- iTunes explicit value -> Podcast explicit setting
- feed language -> report as unsupported or retain in provenance; django-cast
  has no current Blog/Podcast language field

Episode-level candidates:

- item title -> Episode title
- item publication date -> Episode visible date
- item GUID or stable link -> stored import identifier for duplicate detection
- item description or summary -> Episode body or summary content
- item enclosure -> Audio record and Episode podcast audio
- iTunes duration -> Audio duration, if trustworthy and parseable
- iTunes explicit value -> Episode explicit setting
- item keywords -> Episode keywords
- transcript, chapters, funding, and Podcasting 2.0 metadata -> import only if
  django-cast has a clear matching model or explicitly report as unsupported

The first shaping decision before implementation is where original feed
identifiers, enclosure URLs, and source feed URLs live. Avoid relying only on
generated slugs for duplicate detection.

## Onboarding Behavior

For getting-started workflows, the import should be conservative:

- default to a small episode limit;
- require a dry run or preview before writing content;
- make media download behavior explicit;
- avoid surprising storage use;
- leave existing bootstrap sample content available for users without a podcast.

The onboarding goal is "try django-cast with your own podcast feed", not
"silently migrate an entire archive during quickstart".

## Export Question

The generated django-cast podcast feed may be sufficient as the first export
format because podcast directories and other tools already understand it.

Only create a separate export feature if there is a real need for data that the
public feed cannot represent well, such as:

- original media files and artwork as an archive;
- transcripts and chapters that are not included in the current feed;
- django-cast-specific metadata;
- redirects and source identifiers;
- round-trip re-import behavior;
- complete site backup or host migration requirements.

## Open Questions

- Which hardened feed parser should be used to reject DTDs/external entities and
  bound entity expansion, and does the eventual owning repository need a new
  dependency?
- Should imported audio be downloaded into django-cast storage by default, or
  should the first slice support metadata-only imports?
- After a requested audio copy succeeds and the local Audio is attached, should
  the episode publish locally automatically or wait for explicit per-item
  confirmation? Metadata-only, pending, failed, and canceled items remain drafts.
- How should original feed GUIDs, enclosure URLs, and source feed URLs be stored?
  This is the first decision to settle before the item moves from Shaping to
  Ready because duplicate detection depends on it.
- How much Podcasting 2.0 metadata should the first slice recognize?

## Success Criteria

- A user can import a small public podcast feed subset into a local django-cast
  development site and inspect the result in Wagtail.
- A site owner can run a dry run before writing content.
- Duplicate imports do not create duplicate episodes.
- Unsupported metadata is reported clearly instead of being silently lost when it
  looks important.
- Tests cover feed parsing, DTD/XXE/entity-expansion rejection, field mapping,
  explicit podcast-source rebinding, duplicate and local-edit detection, media
  handling decisions, dry-run behavior, and representative RSS/iTunes feed
  examples.
