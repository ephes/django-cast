# Podcast Publishing Metadata

Date: 2026-06-18
Status: PRD / shaping note

## Summary

Add optional standards-aware publishing metadata for podcast episodes:

- episode number
- episode type (`full`, `trailer`, or `bonus`)
- season assignment

The goal is to let django-cast author and emit common podcast RSS metadata
directly, instead of forcing consuming sites to store publication metadata in
import-only side tables or title text.

Treat this as publishing metadata, not identity. RSS GUIDs remain the stable
identifier for podcast clients and must not be derived from episode numbers,
season numbers, titles, or slugs.

## Motivation

`cast.Episode` currently supports podcast audio, visible date, body, keywords,
explicit/block values, cover image, and contributors, but it has no canonical
episode number, season, or episode type fields. The podcast feed emits GUID,
author, subtitle, summary, duration, keywords, explicit, and block tags, but not
`itunes:episode`, `itunes:season`, or `itunes:episodeType`.

That leaves consumers with two weak options:

- omit standard episode metadata from generated feeds; or
- store canonical publishing metadata in consumer-local models that are not part
  of the Wagtail page revision/editing flow.

The immediate concrete consumer is Django Chat. Its imported catalog preserves
episode numbers in `EpisodeSourceMetadata`, but new Wagtail-authored episodes
need a canonical number source for public badges and podcast feed output. The
same problem is generic to django-cast: imported source metadata should not be
the long-term place for editorial publishing metadata.

Related consumer note:

- `../django-chat/docs/episode-numbering-research.md`

## External References

- Apple Podcasts: episode creation and supported episode types:
  https://podcasters.apple.com/support/825-how-to-create-an-episode
- Apple Podcasts: episodic vs serial ordering, seasons, trailers, and bonus
  placement:
  https://podcasters.apple.com/support/3143-how-to-set-the-order-of-podcast-episodes
- Apple Podcasts: RSS requirements, including stable GUIDs:
  https://podcasters.apple.com/support/823-podcast-requirements
- Apple Podcasts: subscription audio can be matched by GUID or by episode
  number, season number, and episode type:
  https://podcasters.apple.com/support/899-set-up-your-show-for-a-subscription
- Podcasting 2.0 `podcast:episode`:
  https://podcasting2.org/docs/podcast-namespace/tags/episode
- Podcasting 2.0 `podcast:season`:
  https://podcasting2.org/docs/podcast-namespace/tags/season
- Simplecast episode creation and episode types:
  https://help.simplecast.com/hc/en-us/articles/21953684815901-Create-and-Publish-a-New-Episode-in-Simplecast
  https://help.simplecast.com/hc/en-us/articles/21953627428637-Episode-Types
- RSS.com episode types:
  https://help.rss.com/en/support/solutions/articles/44001962081-what-are-episode-types-
- Libsyn episode details:
  https://five.libsynsupport.com/hc/en-us/articles/4402566930829-About-Your-Episode-Details
- Captivate episode publishing:
  https://help.captivate.fm/en/article/how-to-upload-and-publish-your-podcast-episodes-on-captivate-jgis4y/
- Podlove Publisher episode template data:
  https://docs.podlove.org/podlove-publisher/reference/templates/template-tags/episode/

## Goals

- Represent common podcast publishing metadata on django-cast-owned models.
- Keep all fields optional so existing podcast and blog sites continue working
  without data migration decisions.
- Expose the fields in Wagtail editing UI for `Episode`.
- Emit Apple-compatible iTunes tags when metadata is present:
  `itunes:episode`, `itunes:season`, and `itunes:episodeType`.
- Emit Podcasting 2.0 `podcast:episode` and `podcast:season` when doing so is
  clearly compatible with the existing feed namespace behavior.
- Keep RSS GUID generation and preservation unchanged.
- Support season names without overloading the integer season tag.
- Provide enough validation to prevent accidental mismatches such as assigning an
  episode to a season from a different podcast.
- Document field semantics and migration guidance for consumers importing from
  existing podcast hosts.

## Non-Goals

- Do not build podcast feed import in this slice. That remains tracked in
  `backlog/2026-05-18-podcast-feed-import.md`.
- Do not implement full podcast feed migration or redirect workflows.
- Do not rename episode titles or remove existing title text automatically.
- Do not make season metadata required for episodic shows.
- Do not make episode numbers the source of feed identity.
- Do not introduce automatic number assignment in the first slice unless its
  locking and publish-path behavior are explicitly designed and tested.
- Do not add Apple Podcasts subscription publishing support; only avoid blocking
  it by modeling compatible metadata.

## Proposed Model Shape

### `Season`

Add a django-cast model scoped to a `Podcast`.

Suggested fields:

- `podcast`: foreign key to `cast.Podcast`
- `number`: positive integer
- `name`: optional short label for display and `podcast:season name="..."`
- optional description/admin note only if a concrete editor use case appears

Suggested constraints:

- unique `(podcast, number)`
- ordered by podcast and number

Rationale: the iTunes namespace only needs a season number, but Podcasting 2.0
supports a season name. A real model gives editors one season object to reuse,
prevents duplicate season definitions, and avoids repeatedly typing names into
episode rows.

Implementation detail to settle: whether `Season` should be a Wagtail snippet.
Snippet editing is attractive for global editor UX, but the model must still be
strictly scoped to one `Podcast`.

### `Episode`

Add optional fields to `cast.Episode`:

- `episode_number`: nullable numeric value
- `episode_type`: choices `full`, `trailer`, `bonus`; default policy to decide
- `season`: nullable foreign key to `Season`

The first implementation should prefer clear editor-entered values over hidden
automation. Automatic "next number" behavior can be added later with explicit
locking and publish lifecycle coverage.

Open numeric policy: Apple-oriented iTunes examples treat episode numbers as
positive integers, while Podcasting 2.0 allows decimals and some imported legacy
feeds may contain special values such as `0`. Decide whether django-cast should:

- allow only positive integers and let importers suppress invalid legacy values;
- allow non-negative integers but omit invalid iTunes output when needed; or
- support decimal episode numbers for Podcasting 2.0 compatibility.

The first slice should choose the smallest policy that serves existing
django-cast sites and Django Chat without creating invalid default RSS output.

## Feed Behavior

Existing feed behavior must remain compatible:

- continue emitting `guid` from `post.uuid` with `isPermaLink="false"`;
- do not change GUIDs for existing episodes;
- continue emitting existing iTunes item tags.

When metadata is present:

- emit `itunes:episode` from `Episode.episode_number` when the value is valid for
  the iTunes namespace;
- emit `itunes:season` from `Episode.season.number`;
- emit `itunes:episodeType` from `Episode.episode_type` when set;
- consider emitting `podcast:episode` from `Episode.episode_number` when the
  feed already declares or can safely declare the Podcasting 2.0 namespace;
- emit `podcast:season` with `name` when `Episode.season.name` is present and
  the Podcasting 2.0 namespace is active.

Do not emit empty tags. Do not infer a season number from publication year.

## Wagtail Editing Behavior

Editors should be able to set podcast publishing metadata from the episode edit
screen without leaving the page.

Suggested UI:

- a collapsed "Podcast publishing metadata" panel;
- episode type select;
- episode number field;
- season chooser or inline season creation path;
- concise help text explaining that GUIDs, not episode numbers, identify feed
  items to podcast clients.

Validation should reject a season belonging to a different podcast. If the
episode has no parent podcast yet, validation should defer cross-object checks
until the parent exists.

## Number Assignment Policy

Manual metadata fields are enough for the first upstream slice.

If automatic assignment is added later:

- do not consume a number when an editor only creates a draft;
- assign only on first publish when the number is blank;
- never change an existing number automatically after first publish;
- serialize assignment with a real lock/counter/sequence, not an unlocked
  `max(number) + 1` query;
- cover Wagtail editor publish, scheduled publish, and bulk publish paths;
- decide explicitly whether trailers and bonus episodes consume the main
  full-episode sequence.

This is deliberately a follow-up policy layer, not a prerequisite for adding
standard metadata fields.

## Backwards Compatibility

Existing sites should see no public change until editors populate metadata or a
project deliberately backfills it.

Migration expectations:

- add nullable fields/models with no required default that changes existing
  pages;
- keep existing feed tests passing;
- add new feed tests only around populated metadata;
- document how consumer sites can backfill from import metadata if needed.

If `episode_type` gets a default of `full`, decide whether existing feed items
should immediately emit `<itunes:episodeType>full</itunes:episodeType>`. That may
be standards-friendly but is still a feed output change and needs release-note
coverage.

## Open Questions

- Should `Season` be a Wagtail snippet or a regular model edited through a
  podcast-scoped admin view?
- Should `Episode.episode_type` default to `full`, or remain blank until an
  editor/importer sets it?
- Should django-cast support decimal episode numbers for Podcasting 2.0, or stay
  aligned with iTunes integer metadata first?
- Should duplicate non-null episode numbers be validated per podcast, per season,
  or only for full episodes?
- Should the first slice emit Podcasting 2.0 `podcast:episode` and
  `podcast:season`, or only iTunes tags?
- How should consumer importers handle legacy source values that are not valid
  iTunes episode numbers?

## First Implementation Slice

1. Add the optional model fields and migrations.
2. Add Wagtail panels and validation for same-podcast season assignment.
3. Update podcast feed generation for valid iTunes metadata.
4. Add focused tests for model validation and feed output.
5. Update model/feed documentation and current release notes.
6. Add migration/backfill guidance for consumer sites such as Django Chat.

Defer automatic next-number assignment unless the first implementation explicitly
includes the transaction and publish-path design.

## Success Criteria

- Existing django-cast tests pass without requiring existing episodes to have
  numbers, seasons, or types.
- Editors can set episode number, type, and season metadata on an episode.
- Generated podcast RSS includes valid iTunes episode metadata when those fields
  are populated.
- Feed GUIDs are unchanged by the new metadata.
- Season names can be represented internally and, when Podcasting 2.0 season
  output is enabled, emitted without duplicating data on every episode.
- Consumer sites can backfill/import episode metadata without storing canonical
  editorial values in import provenance models.
