# Podcast Feed Import

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

## First Slice

Design a management-command based import workflow, for example:

```text
python manage.py import_podcast_feed <feed-url> --parent <page-id-or-slug> --limit 5 --dry-run
```

The first implementation should support:

- fetching and parsing a public RSS podcast feed;
- dry-run output that shows which podcast and episodes would be created or
  updated;
- creating a Podcast page under a selected parent page when requested;
- creating Episode pages from feed items;
- preserving original publication dates;
- importing or linking episode audio in a deliberate, documented way;
- limiting imports for local trial setups, such as the latest 3 to 5 episodes;
- repeatable duplicate detection using stable feed item identifiers;
- clear reporting for unsupported feed metadata.

Prefer an explicit command over hidden quickstart behavior. The quickstart or
bootstrap path can call or document the command later.

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
- feed language -> existing language behavior, if supported by the current model

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

- Which feed parser should be used, and does django-cast need a new dependency?
- Should imported audio be downloaded into django-cast storage by default, or
  should the first slice support metadata-only imports?
- Should imports create draft episodes first, or publish imported episodes when
  the source feed item is valid?
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
- Tests cover feed parsing, field mapping, duplicate detection, media handling
  decisions, dry-run behavior, and representative RSS/iTunes feed examples.
