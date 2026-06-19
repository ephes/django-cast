# Podcast Publishing Metadata

Date: 2026-06-18
Status: first metadata slice and automatic numbering follow-up implemented.
Remaining active work is limited to deferred follow-up questions: season editing
shape, duplicate number policy, legacy import values, and possible channel-level
`itunes:type` support.

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
`itunes:episode`, `itunes:season`, or `itunes:episodeType`. The feed also does
not emit a channel-level `itunes:type` (episodic vs serial), so Apple currently
treats every django-cast show as episodic by default; this matters because
episode numbers are only optional for episodic shows and effectively required
for serial shows (see Feed Behavior and Open Questions).

The Podcasting 2.0 `xmlns:podcast` namespace is already declared on the podcast
feed (`src/cast/feeds.py`, `PodcastIndexElements.namespace_attributes`), so
emitting `podcast:episode` / `podcast:season` does not require introducing a new
namespace — only deciding whether to populate the tags.

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

- Podcast de facto standard (consolidated iTunes/podcast namespace reference,
  including `itunes:episode`/`itunes:season` "must be a positive integer" and
  `itunes:episodeType` value rules):
  https://podcast-standard.org/podcast_standard/
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
- Emit Podcasting 2.0 `podcast:episode` and `podcast:season`, reusing the
  `xmlns:podcast` namespace already declared on the podcast feed.
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
- `number`: positive integer. `itunes:season` requires a positive non-zero
  integer; the Podcasting 2.0 `podcast:season` node value only requires an
  integer, so keeping it positive satisfies both
- `name`: optional short label for display and `podcast:season name="..."`; cap
  at `max_length=128` to match the Podcasting 2.0 `name` attribute limit
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

- `episode_number`: nullable positive integer (see numeric policy below)
- `episode_type`: choices `full`, `trailer`, `bonus`; recommended blank default
  (see Backwards Compatibility)
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
Recommendation: model `episode_number` as a positive integer for the first
slice. A positive integer is the only value valid for `itunes:episode`, and it
is simultaneously a valid `podcast:episode` decimal node value, so a single
integer field can feed both tags without conflict. Defer decimal support
(e.g. `100.5` mini-episodes) and the `podcast:episode` `display` attribute
(≤32 chars) to a later slice if a concrete need appears, since neither maps to a
valid iTunes value.

## Feed Behavior

Existing feed behavior must remain compatible:

- continue emitting `guid` from `post.uuid` with `isPermaLink="false"`;
- do not change GUIDs for existing episodes;
- continue emitting existing iTunes item tags.

When metadata is present:

- emit `itunes:episode` from `Episode.episode_number` only when the value is a
  positive integer (the spec requires a non-zero positive integer; suppress the
  tag for `0`, negative, or non-integer values);
- emit `itunes:season` from `Episode.season.number` only when it is a positive
  integer;
- emit `itunes:episodeType` from `Episode.episode_type` only when explicitly set
  (see the default-policy note below);
- emit `podcast:episode` from `Episode.episode_number`; the `xmlns:podcast`
  namespace is already declared on the podcast feed, so this is a populate-only
  decision, not a namespace change. An integer `episode_number` is a valid
  decimal node value;
- emit `podcast:season` with the `name` attribute when `Episode.season.name` is
  present (the `podcast:season` node value is the integer season number).

Do not emit empty tags. Do not infer a season number from publication year.

Repository/cache path: the podcast feed renders from a `FeedContext` repository
built from cachable data (`src/cast/feeds.py`), and existing feed tests assert
the cached/repository feed renders with zero database queries. Episode number
and episode type live on `Episode`, but emitting `podcast:season` /
`itunes:season` requires the season `number` and `name`. The implementation must
carry season fields through the repository's cachable representation (and add
the matching `select_related` on the live path) so reading `Episode.season`
during feed generation does not introduce new queries. Cover this with the
existing zero-query feed test contract, not only with live-feed tests.

Display note: Apple Podcasts only shows season numbers once a feed contains more
than one season, so emitting `itunes:season` for a single-season show is valid
and harmless but will not be surfaced. Do not treat a hidden single-season badge
as a bug.

Channel-level `itunes:type` (episodic vs serial) is currently not emitted and is
out of scope for the first slice, but it is the natural companion to season and
episode-number metadata for serial shows. The first slice should not silently
imply serial ordering; if a later slice adds serial support it must add an
explicit `itunes:type` channel control rather than inferring it from the
presence of seasons. Tracked under Open Questions.

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

Automatic assignment was added in a follow-up implementation:

- automatic numbering is disabled by default and enabled per `Podcast`;
- draft saves and future scheduling approvals do not consume a number;
- blank/full episodes consume the podcast-scoped sequence on first real publish
  when `episode_number` is blank;
- trailer and bonus episodes do not consume numbers in the first automatic
  numbering slice;
- existing non-empty numbers remain authoritative;
- assignment locks the podcast counter row and skips already-used manual numbers
  under the same podcast;
- assigned numbers are written into Wagtail revision content as well as the live
  object being saved.

This remains a policy layer separate from the base metadata fields. Feed import,
renumbering, season-scoped numbering, and channel-level `itunes:type` remain out
of scope and tracked separately when needed.

## Backwards Compatibility

Existing sites should see no public change until editors populate metadata or a
project deliberately backfills it.

Migration expectations:

- add nullable fields/models with no required default that changes existing
  pages;
- keep existing feed tests passing;
- add new feed tests only around populated metadata;
- document how consumer sites can backfill from import metadata if needed.

Recommendation for `episode_type`: keep it blank by default and omit the tag
when blank. The spec treats an absent `itunes:episodeType` as equivalent to
`full`, so a blank default is both standards-correct and a no-op for existing
feeds — no feed output change and no release-note burden. If a future decision
instead defaults to `full` and emits `<itunes:episodeType>full</itunes:episodeType>`
for every existing item, that is a feed output change for all current episodes
and must be called out in release notes.

## Open Questions

- Should `Season` be a Wagtail snippet or a regular model edited through a
  podcast-scoped admin view? (open)
- Should duplicate non-null episode numbers be validated per podcast, per season,
  or only for full episodes? (open — note trailers/bonus may legitimately reuse
  or skip numbers)
- How should consumer importers handle legacy source values that are not valid
  iTunes episode numbers (e.g. `0`, blank, or non-integer)? (open)
- Should a later slice add channel-level `itunes:type` (episodic vs serial) so
  serial shows can declare ordering, given episode numbers are effectively
  required for serial shows? (open — deliberately out of the first slice)

Resolved with a recommended default (kept here for visibility, may still be
revisited):

- `Episode.episode_type` default: keep blank and omit the tag; absent equals
  `full` per spec, so this is standards-correct and changes no existing feed.
- Episode number type: positive integer for the first slice; defer decimal /
  `podcast:episode display` support.
- Podcasting 2.0 output: emit `podcast:episode` and `podcast:season` alongside
  the iTunes tags, since the `xmlns:podcast` namespace is already declared.

## First Implementation Slice

1. Add the optional model fields and migrations.
2. Add Wagtail panels and validation for same-podcast season assignment.
3. Update podcast feed generation for valid iTunes metadata (`itunes:episode`,
   `itunes:season`, `itunes:episodeType`) and the matching Podcasting 2.0 tags
   (`podcast:episode`, `podcast:season`), suppressing tags for absent or
   out-of-range values.
4. Add focused tests for model validation and feed output, including the
   repository/cache feed path under the existing zero-query assertions.
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
