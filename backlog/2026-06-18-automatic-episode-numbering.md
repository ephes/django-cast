# Automatic Podcast Episode Numbering

Date: 2026-06-18
Status: Implemented in 0.2.61

## Summary

Add generic, opt-in automatic episode number assignment for Wagtail-authored
podcast episodes.

The first podcast publishing metadata slice added canonical
`Episode.episode_number`, `Episode.episode_type`, `Episode.season`, feed tags,
Wagtail panels, and validation. Editors can now set a number manually, but
consumer sites such as Django Chat still need a safe way to create the next
episode without manually checking the current maximum and typing the next
number.

This backlog item covers that policy layer. It should live in django-cast, not
in a consumer site's importer or source-provenance models.

## Motivation

Manual numbering works for imported backfills and one-off corrections, but it
is brittle for regular editorial use:

- editors must know the current latest number before creating a page;
- drafts may be created ahead of time, so numbering on draft creation alone can
  reserve or waste numbers;
- publishing workflows can involve multiple editors, scheduled publishing, or
  programmatic content creation;
- episode numbers are visible podcast publishing metadata, so accidental gaps
  or duplicates are costly to repair after feeds are consumed.

The behavior must remain generic to django-cast and must not change the feed
identity model. RSS GUIDs stay UUID-based.

## Goals

- Provide a generic django-cast mechanism for assigning the next episode number
  for an episode under a `Podcast`.
- Make the behavior opt-in or deliberately configured so existing sites do not
  get surprising metadata changes.
- Keep `Episode.episode_number` manually editable for imports, corrections,
  and special cases.
- Prefill the Wagtail create/edit experience where useful, without treating a
  draft-only page as having consumed a number.
- Assign a number on first publish when the field is blank and the configured
  policy says the episode should consume a number.
- Never rewrite an existing non-empty episode number automatically.
- Prevent automatic assignment from duplicating an existing manual episode
  number for the same podcast.
- Keep episode number assignment scoped to the parent `Podcast` unless a later
  policy explicitly chooses season-scoped numbering.
- Treat occasional gaps as acceptable; avoiding duplicate public numbers matters
  more than enforcing strict contiguity.
- Preserve RSS GUID behavior and never derive slugs, UUIDs, or feed identity
  from episode numbers.

## Non-Goals

- Do not implement feed import in this item.
- Do not renumber existing episodes automatically.
- Do not make episode numbers required for all django-cast podcasts.
- Do not use unlocked `max(episode_number) + 1` assignment in a publish path.
- Do not infer `itunes:type` or serial/episodic show ordering from automatic
  numbering.

## Policy Questions

- Should the default be disabled, enabled per `Podcast`, or enabled globally by
  a setting?
- Should `full` episodes consume the main sequence while `trailer` and `bonus`
  episodes do not, or should sites choose per episode type?
- Should a blank `episode_type` be treated as `full` for numbering purposes?
  This matches feed semantics, but the policy should say so explicitly.
- Should create-form defaults show the current next number for editor clarity,
  while first publish still does the authoritative assignment?
- Should duplicate non-empty episode numbers be rejected for a podcast, and if
  so should that be model validation, a database constraint enabled by a new
  model shape, or part of the assignment service?
- Should season-scoped numbering be supported later, or is podcast-scoped
  numbering enough for the first implementation?

## Implementation Shape To Explore

The implementation should separate advisory UI defaults from authoritative
assignment:

1. Wagtail create/edit form can prefill `episode_number` with the current next
   number when the field is blank and automatic numbering is configured.
2. First publish is the authoritative point where a blank number is assigned.
3. Assignment must run inside a transaction using a lock, counter row, or
   equivalent serialization mechanism so two editors cannot publish the same
   number concurrently.
4. The assignment step must also check existing non-empty numbers for the
   podcast and skip or reject numbers that were entered manually before the
   counter reached them.
5. Once `episode_number` is non-empty, automatic numbering must leave it alone.
6. Programmatic publish paths should share the same service/API as the Wagtail
   editor path.

For Wagtail publish behavior, durable assignment cannot be a live-row-only
update after publish. Wagtail publishes a page by reconstructing the live object
from the revision content, so the assigned number must be written into the
revision/content being published as well as the live `Episode` row. Otherwise a
later re-publish, revert, or edit based on that revision can restore a blank
`episode_number`.

Scheduled publishing should assign only when the episode actually goes live, not
when a future `go_live_at` revision is scheduled or approved. Wagtail's
`page_published` signal is useful as a lifecycle reference because it fires on
real go-live, but it fires after the live object has already been saved and is
therefore too late to be the primary persistence mechanism for the assigned
number.

For a conservative first slice, prefer podcast-scoped numbering with automatic
assignment disabled by default and enabled per `Podcast`. Treat a blank
`episode_type` as `full` for assignment purposes. If the configured policy says
only full episodes consume numbers, decide consumption from the episode type at
first publish: a full episode later changed to trailer keeps its number, and a
trailer later changed to full does not silently receive one.

Possible model/API shapes:

- a podcast-scoped counter model;
- fields on `Podcast` for automatic numbering policy and next number;
- a small service function such as `assign_episode_number_on_first_publish()`
  used by Wagtail hooks/forms and future programmatic editing APIs.

## Test Expectations

Cover at least:

- create/edit form default display for a blank new episode;
- first publish assigns the next number when blank;
- drafts do not permanently consume numbers;
- existing numbers are not changed on save, republish, or edit;
- duplicate assignment is prevented under concurrent publish attempts;
- automatic assignment skips or rejects manually entered numbers that would
  otherwise collide with the counter;
- re-publishing the assigned revision, reverting, and editing after publish do
  not lose the assigned number;
- trailer/bonus policy matches the documented configuration;
- scheduled publish and bulk publish paths either use the same assignment
  behavior or are explicitly unsupported with a documented reason;
- scheduled publish assigns at actual go-live rather than schedule/approval
  time;
- GUIDs and slugs stay unchanged by number assignment.

## Success Criteria

- A django-cast podcast can opt into automatic numbering for newly authored
  episodes.
- Editors can still override or correct `episode_number` manually.
- The first published episode after an imported catalog receives the next
  correct number without consumer-site custom code.
- Number assignment is concurrency-safe and covered by focused tests.
- Feed GUID behavior remains unchanged.

## Implementation Log

Implemented for django-cast 0.2.61:

- Added opt-in `Podcast.automatic_episode_numbering_enabled` and
  `Podcast.next_episode_number` fields.
- Added a small publish-time numbering service in `cast.podcast_numbering` that
  locks the podcast row, skips already-used manual numbers under the same
  podcast, and writes the assigned number into both the Wagtail revision content
  and the live object being saved.
- Integrated the service with Wagtail revision publishing before the live object
  save, so normal editor publish, programmatic `revision.publish()`, and due
  scheduled publishes share the same behavior.
- Kept assignment disabled by default. Blank/full episodes consume numbers on
  first real publish; trailer and bonus episodes do not consume numbers.
- Documented acceptable gaps, manual-number authority, and UUID-based RSS GUID
  preservation.
