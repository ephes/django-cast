# Podcast Episode Contributors

## Summary

Add a podcast-only contributor feature that links people directly to podcast
episodes. Keep the first slice deliberately narrow: no blog-post contributors,
no podcast-level contributor relationship, and no automatic defaulting logic in
the persisted public model.

The primary use case is making hosts and guests visible on episode pages and in
podcast feeds, with a profile link and optional avatar image. Production
contributors are not part of the first slice.

## Motivation

Podcast episodes often involve people beyond the Wagtail page owner:

- hosts
- co-hosts, represented as hosts
- guests

For normal blog posts this is not currently worth the extra model and template
surface area. For podcasts, the information is useful to listeners and can be
expressed in the Podcasting 2.0 feed namespace with ``podcast:person``.

## External References

- Podlove Publisher contributor model:
  https://docs.podlove.org/podlove-publisher/reference/templates/template-tags/contributor/
  - global contributors with visibility, avatar, profile/services, affiliation,
    and episode associations
  - contribution rows carry role, group, position, and an optional comment
  - contributor listings can be filtered by role, group, and episode
- Podcasting 2.0 ``podcast:person``:
  https://podcasting2.org/docs/podcast-namespace/tags/person
  - valid under channel or item
  - supports role, group, image URL, and profile URL attributes
  - item-level people replace channel-level people in consuming apps

## Episode Page Presentation Research

A survey of existing podcast episode pages shows two useful presentation
patterns: a top-of-page people block for the humans who define the episode, and
a lower credits block for production work.

Good examples:

- Syntax episode pages show headshots directly under the episode title, with a
  clear role label such as ``Guest`` or ``Host`` and social links:
  https://syntax.fm/show/190/migrating-deploying-and-hosting-wordpress
- Changelog episode pages use a compact ``with ...`` line and ``Featuring`` row
  near the title, then repeat the same contributors in a more detailed
  ``Featuring`` section with personal links:
  https://changelog.com/friends/73
- a16z podcast pages put contributor names in the byline and add an ``About the
  Contributors`` section with images, bios, links, and related content:
  https://a16z.com/podcast/the-hidden-economics-powering-ai/
- Huberman Lab guest episodes add an ``About this Guest`` section with a short
  guest bio and external links:
  https://www.hubermanlab.com/episode/guest-series-dr-paul-conti-how-to-understand-and-assess-your-mental-health
- 99% Invisible shows ``Producer`` as episode metadata near date/category and
  adds a lower ``Credits`` section for production detail:
  https://99percentinvisible.org/episode/449-mine/
- Radiolab uses a role-first ``EPISODE CREDITS`` block, with lines such as
  reported by, produced by, mixing, fact-checking, and edited by:
  https://radiolab.org/podcast/brain-balls
- Darknet Diaries highlights the guest in the intro copy and keeps production
  roles in a lower ``Attribution`` section:
  https://darknetdiaries.com/episode/126/

Design implications for django-cast:

- The first public episode detail rendering should focus on episode identity:
  hosts and guests, in editorial order, with compact role labels.
- Place the contributor block close to the episode title/player or the opening
  show notes, not buried after the transcript or metadata.
- Show avatar, display name, role label, and selected profile link when present.
  Keep biographies out of the default compact block; ``short_bio`` can support
  later richer layouts or public contributor detail pages.
- Keep production credits conceptually separate from host/guest identity. When
  broader roles are added later, a lower role-first credits section is a better
  fit for producer, editor, mixing, music, artwork, fact-checking, and similar
  roles.
- Preserve theme flexibility: expose ordered assignments and role information so
  themes can choose between a compact strip, grouped role lists, or richer
  contributor cards.

## First Slice

Create a global person/contributor snippet and an ordered episode-to-person
relationship.

Suggested models:

```text
Contributor
- display_name
- slug or identifier
- visible, as a global public/private switch for hiding a contributor without deleting episode assignments
- avatar image, using Wagtail's image chooser
- short_bio

ContributorLink
- contributor
- service, using fixed choices for the first supported services
- url
- sort_order

EpisodeContributor
- episode
- contributor
- role
- sort_order
- link
```

Use ``Contributor`` as the public/domain term unless implementation details make
``Person`` clearly better. Avoid ``Collaborator`` because it sounds like editing
permissions rather than public credits.

Use a structured ``ContributorLink`` relation instead of a JSONField for public
links. That keeps validation, ordering, Wagtail editing, and template/feed usage
explicit while still supporting multiple profiles such as a personal site,
GitHub, Mastodon, Twitter/X, LinkedIn, or YouTube. Keep ``service`` as fixed
choices in the first slice; add new services deliberately instead of allowing
arbitrary labels.

## Feed Behavior

Emit ``podcast:person`` only on episode feed items in the first slice.

Do not emit channel-level ``podcast:person`` yet. That avoids merge/defaulting
rules and avoids the Podcasting 2.0 replacement behavior where item-level people
replace channel-level people.

For each visible episode contributor:

- element text: contributor display name
- ``role``: assignment role, either ``host`` or ``guest``
- ``img``: absolute URL for the contributor avatar image when configured
- ``href``: the selected contributor link for this episode assignment when configured; omit the attribute when no link is selected

Keep existing ``itunes:author`` behavior unchanged.

## Website Behavior

Expose contributors in episode template context so themes can render a compact
people/credits section.

The first template implementation should be intentionally small:

- group or label by role when useful
- link the contributor name/avatar to the selected contributor link when present
- hide non-visible contributors from public rendering and feeds

Defer sibling theme template updates for the first slice. Keep the template
context stable enough that sibling themes can adopt the contributor block later.

Do not add person detail pages in the first slice.

## Admin Behavior

Editors should be able to:

- manage contributor snippets globally
- add ordered contributors to an episode
- choose ``host`` or ``guest`` per episode assignment
- optionally choose which contributor link should be used for this episode/feed

Assignment-specific comments/notes are deferred until there is a concrete public
or editorial use case.

Role choices should start narrow:

- host
- guest

Keep the role field extensible enough to add more taxonomy roles later without a
large migration.

## Later Options

Automatic/default contributors can be added later without changing the public
read model by materializing defaults into ``EpisodeContributor`` rows.

Possible later approaches:

- an ``EpisodeTemplate`` snippet that stores common contributors and can be
  copied into a new episode
- podcast-level default settings that prefill episode contributors on creation
- a Wagtail admin action/button to copy default hosts into an existing episode
- public contributor detail pages with lists of related episodes
- API fields for themes such as ``cast-vue``

## Open Questions

- Which fixed ``ContributorLink.service`` choices should be included initially?

## Success Criteria

- No changes to normal blog post author behavior.
- Existing podcast feeds remain valid and keep current iTunes metadata.
- Episode RSS items include valid Podcasting 2.0 ``podcast:person`` tags for
  visible contributors.
- Query counts for episode detail pages and feed rendering stay controlled with
  explicit prefetch/select behavior.
- Tests cover admin/model behavior, feed XML output, visibility filtering, and
  rendering context.
