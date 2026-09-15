# Architecture and Codebase Review

Date: 2026-09-15

Status: Findings list from a read-only architecture review of `develop` at commit `b36ddd4b`. The bug and
test-hygiene items are being implemented as small slices in the order given under "Recommended sequence"; an item
that has landed carries a dated "Fix note" and everything without one is still open. The structural themes need
shaping first. Security was in scope only where it overlaps correctness — the
standing observations stay in [2026-09-07-security-review.md](2026-09-07-security-review.md).

Method: four parallel automated review passes (data/domain layer; views/API/feeds/comments; cross-cutting coupling;
tests/tooling/frontend), each followed by an adversarial verification pass that reproduced or refuted every claim
against the source, plus a backlog cross-reference pass against [BACKLOG.md](../BACKLOG.md) and the `backlog/` notes.
46 findings survived verification (2 high, 24 medium, 20 low) plus 8 defects the passes found while checking others
(listed as `-extra` below; their severities are this note's own triage, not the verification pass's); verifier
corrections are folded into the directions below. Previous review:
[2026-07-02-architecture-review.md](2026-07-02-architecture-review.md).

## Top themes (prioritized)

1. **One stranded-state bug plus small correctness defects** come first: X1 (paid Voxhelm job orphaned, row stuck
   QUEUED), D1/D-extra (podcast Atom loses `<updated>`, 500s on audio-less episodes), V10 and its webvtt twin (500
   where a sibling endpoint 404s), V-extra (admin audio replacement keeps the old duration).
2. **Publication rules have no shared seam** — an admin form `clean` keyed on the `action-publish` POST field
   (`models/pages.py:652-658`), the editor API's `_reject_unpublishable_episode` (`api/editor/views.py:344,378`), a
   monkeypatch of Wagtail's private `PublishRevisionAction._publish_revision` (`podcast_numbering.py:168-200` via
   `apps.py:60`) and a `page_published` receiver (`post_media.py:100-102`). The v3 evaluation, publication approval
   binding and scheduled publishes all need one publication-policy service.
3. **Upload safety lives in the transport layer, not a media service**: lock, probe budget and size handling exist
   only in `api/editor/media.py`; admin `MediaAdminViews`, `TranscriptForm` and `media_derivation.py` have none.
   Admin hardening, transcript caps, remote media import, media replacement and podcast feed import are all blocked
   on a shared ingest service plus an SSRF-safe fetch helper that today lives inside `voxhelm/client.py`.
4. **The editor body converter is the reusable content core but is welded to DRF**: `api/editor/body.py` and
   `richtext.py` raise `EditorValidationError` (`errors.py:5-10`) and stop at the first nested failure. A
   transport-neutral `cast.content` with an error collector unblocks v3 reuse, Markdown input, embeds, inline-media
   placeholders, nested error aggregation and the rich-text audit at once.
5. **Presentation state still rides on model instances** (D2, D8). Theme redesign, view transitions,
   template-contract promotion, paged feeds and v3 previews all get safer once render state moves onto the context
   object and the model is fields-only.
6. **Duplication is where recent hardening paid twice**: V11, V3, V6, V9, V5, V10, X3 — and X3 has already drifted
   with user-visible effect.
7. **The read-model boundary serializes for a cache that does not exist** (D5), while
   `docs/reference/settings.rst:749` calls it "uses optimized SQL". Decide cache-or-drop before extending it.
8. **The coverage gate is healthy; the suite around it is not**: ruff blankets hiding 849 unused imports and shadowed
   fixtures (T1), a regrown root conftest (T3), TypeScript never type-checked (T4), `DeprecationWarning` silenced
   across a Django 5.2–6.1 / Wagtail 7.0–8.0 matrix (T5), one shared media root for concurrent runs (T6).
9. **Bookkeeping drift** (fixed with this note): the 2026-07-02 review claimed its residual themes lived as
   `BACKLOG.md` items (they did not); headings were stale against their own fix notes; M7's "removable after one
   release" fallbacks are two releases past due; the OPEN modelsearch note was unindexed; and `AGENTS.md` steered new
   tests at a convention 106 of 107 modules do not use.

## Data and domain layer

Plain `save()` does no I/O (H2 holds), transcript parsing lives in `cast.transcripts` (H3 holds), theme choices are a
callable, the M8 prefetch is intact and the M7 discriminator is written everywhere. The rest is structural residue.

- **D1. `serialize_episode` omits `last_published_at`** (medium, bug, prior M7) — `repository/serialization.py:283`.
  `serialize_post:268` carries it, the episode twin does not, so under `CAST_REPOSITORY="default"` `Atom1Feed`
  silently drops the Atom-required `<updated>` from `cast:podcast_feed_atom` while the blog feed and the `"django"`
  repository keep it (reproduced). Direction: build both dicts from one `_serialize_post_common(post)` (also fixes
  D-extra) plus a podcast twin of `test_latest_entries_atom_feed_entry_has_updated_and_uuid_id`.
  Fix note (2026-09-16, fixed): `_serialize_post_common(post)` now holds the nine shared post fields and both
  `serialize_post` and `serialize_episode` build on it, so `last_published_at` reaches the episode dict and
  `cast:podcast_feed_atom` carries `<updated>` again. `tests/feed_test.py::test_podcast_atom_feed_entry_has_updated`
  is the podcast twin, pinned to `CAST_REPOSITORY="default"`, and a key-parity test in
  `tests/repository/serialization_test.py` fails if the two field sets drift apart again. The podcast twin asserts
  only `atom:updated`, because `AtomPodcastFeed` defines no `item_guid` and its entry ids are page URLs rather than
  post UUIDs (unchanged, out of scope).
  Not done: the default-vs-django context parity test named in the recommended sequence; it belongs with D5.
- **D2. `Post`/`Episode` still own template selection, request-aware URLs, renditions and DRF fields** (medium,
  architecture, prior H1 residual) — `models/pages.py:540`. Still on the model: `get_template`/
  `get_template_base_dir` (266-277), a `get_context` that copies the page and fabricates an owner (396-418),
  rendition generation (529-561), three `reverse()`+`build_absolute_uri` URLs (801-836), a `comments` property
  querying `django_comments` (473-503) and two DRF `Field` subclasses (87-128). Direction: fields to `cast/api`,
  cover/social and Episode URL assembly into a `build_post_detail_context(post, request, repository)` presenter, both
  `get_context`s thinned to delegates. No theme repo imports these names, so one release of re-exports suffices; keep
  the `ContentBlock` alias (`pages.py:45`) that `ContentBlock.deconstruct` hard-codes for migrations.
- **D3. Import inversion relocated, not removed** (medium, coupling, prior M1 residual) — `models/index_pages.py:21`.
  `cast.blog_index` (module-level in `index_pages`, `repository/contexts.py:10`, `builders.py:10`) reaches
  `cast.filters`/`forms`/`player`/`follow_links` through function-body imports the AST guard
  (`tests/import_cycle_test.py:89`) cannot see, and `pages.py:36-47` imports four presentation modules directly.
  Direction: move `Blog.get_context`/`serve`/`get_repository` and `Post.get_context` into the view layer; a
  transitive guard cheaply lists the edges but fails on the deliberate lazy imports, so commit it with the move.
- **D4. Legacy key-sniff fallbacks are past due and unreachable** (low, duplication, prior M7 residual) —
  `repository/contexts.py:296`. 0.2.64 shipped after the 2026-07-03 discriminator, and the cachable dicts are never
  written to any cache (`urls.py:45-60` caches HTTP responses, not dicts), so no legacy entries can exist; three
  branches (`contexts.py:293-298`, `486-491`, `serialization.py:242-250`) and five tests still constrain every new
  field. Direction: delete the branches, raise on a missing discriminator, delete
  `serialization_test.py:252,290,513,529,545` in the same change to hold 100%, centralize the repeated
  `collection_id`/`"collection": None` handling.
- **D5. The cachable boundary serializes and immediately deserializes per request with no cache** (medium,
  architecture) — `models/index_pages.py:286`, `feeds.py:95-98`, plus a FIXME `refresh_from_db` (`contexts.py:253`).
  The deserializers also disagree on key normalization (`FeedContext._int_keyed` vs `BlogIndexContext` indexing
  `data["audios"]`/`owner_username_by_id[post.pk]` directly), so a JSON round trip raises `KeyError` on the
  blog-index path (reproduced) while the feed path has a passing round-trip test. Direction: decide explicitly —
  wire a real cache keyed on version+blog+params with one shared `_normalize_cachable_data()` and publish-signal
  invalidation, or drop the round trip and build contexts from `PostQuerySnapshot` directly. Either way remove the
  FIXME, fix the settings doc, and add a default-vs-django parity test (D1 and D-extra are symptoms of its absence).
- **D6. `has_audio` and the cover fallback are computed in several places** (medium, duplication) —
  `repository/snapshot.py:176`. `Post.has_audio` (`pages.py:320-333`) recomputes it with two extra queries and a
  different exception set; cover resolution exists five times (`pages.py:517-527`, `529-548`, `550-561`,
  `blog_index.py:125-131`, `builders.py:89-95`) and `cover_image.file.url` at four more sites. Direction:
  `compute_has_audio(*, audio_in_body, audios_count, podcast_audio_id)` and `resolve_cover(...) -> (url, alt)`, with
  `file.url` derived once in the snapshot. Apply `resolve_cover` *inside* `Post.get_cover_image_context`: it is a
  staticmethod over a context dict that templates and `Episode.get_context` call, so its signature must not change.
- **D7. `PostDetailContext`'s shape is hand-maintained in four places** (low, duplication) — `models/pages.py:131`.
  `HasPostDetails` (15 attrs) mirrors `PostDetailContext.__init__` (`contexts.py:54-91`), which
  `get_context_from_repository` copies a third time; `PostQuerySnapshot`'s 17 kwargs are mirrored in
  `CachableBlogData`, `add_queryset_data` and both `create_from_cachable_data`. Direction: frozen kw-only
  dataclasses, drop the Protocol, move the copier on as `as_template_context()`. Three traps: the snapshot exposes
  `post_queryset` as `self.queryset`; `PostDetailContext.__init__` has a `cache_page_url` side effect that must move
  to `__post_init__`; and it needs the `site` attribute D8 describes first.
- **D8. `Post` branches on a `_repository` attribute nothing in `src/` sets** (low, coupling, prior Low-1) —
  `models/pages.py:340`. `comments_are_enabled` and `get_site` (589-590) check it, but the only writer is
  `tests/cast_comments_internals_test.py:281`, so the asserted zero-query branch never runs in the app; the wider
  item is unchanged (`_media_lookup`, `owner`, `page_url`, `cover_image_url`, `cover_alt_text_display`,
  `blog._last_build_date` injected onto instances). Direction: delete both dead branches with their test, or wire
  `post._repository` — but `get_site` reads `self._repository.site` unguarded and `PostDetailContext` has no `site`,
  so wiring it as-is raises `AttributeError`.
- **D9. `Audio`/`Video`/`Transcript` share no base and use three sentinel conventions** (low, duplication, prior H2)
  — `models/audio.py:347` (`_SAVE_OPTION_UNSET`, "unset means True if the other is set"), `video.py:182-188`
  (`kwargs.pop("poster")`), `transcript.py:85-92` (`kwargs.pop("sync_speaker_mappings")`); all three hand-roll
  `get_all_paths`, `admin_form_fields`, `Meta.permissions`, a user FK and a `TaggableManager`. Direction: an abstract
  `CastMediaBase` with `file_field_names` driving `get_all_paths()` and one `_save_with_optional_derivations()`
  behind a uniform `derive=` keyword, old kwargs deprecated for a release; `docs/reference/models.rst` and
  `media/video.rst` document the current contract and must move with it.
- **D10. Contributor models validate (and query) inside `save()`** (low, bug, prior Low-2) —
  `models/contributors.py:286`. Two `save()`s call `clean()`, and `ContributorLink.save` repeats the `exists()` query
  its own `clean` already runs, so admin saves validate twice. Direction: validate in `clean()` only, call
  `full_clean()` at the editor-API/admin boundaries, drop the duplicate. Two review sub-claims fail:
  `deserialize_episode_contributor` never calls `save()`, and the "save only persists fields" rule is documented for
  `Audio`/`Video`/`Transcript`/`Post` only.
- **D11. The editor body converter hard-codes the built-in block list** (low, coupling) — `api/editor/body.py:15`
  keeps its own frozenset plus a 75-line `if`/`elif` chain (289-364) separate from
  `post_body_blocks.DEFAULT_CONTENT_BLOCK_NAMES`, re-implementing validation the blocks own, while custom blocks
  already use the generic `to_python`/`sanitize`/`clean`/`get_prep_value` path. Direction: a registry in
  `post_body_blocks` mapping each name to `to_stream`/`to_author`, media blocks supplying the choose-permission
  check, so `body.py` iterates `default_content_blocks() + configured_content_blocks(section)`. Low, not medium:
  `embed`-as-placeholder is a documented contract (`api.rst:584-588`) and the author-facing format is a curated
  public API, not a StreamField mirror, so some lockstep is by design.
- **D12. `add_site_raw` fallback picks an arbitrary `wagtailcore_site` row** (low, bug) — `builders.py:135` runs raw
  SQL with no `ORDER BY` and no `is_default_site` filter, so multi-site `root_nav_links` and URL building depend on
  row order. Degenerate setups only, but it is the package's one raw statement. Direction:
  `Site.objects.filter(is_default_site=True)...first()`, raising `ImproperlyConfigured` on an empty table instead of
  omitting `data["site"]`; this rewrites `test_add_site_raw_falls_back_to_sql_when_no_context` and
  `test_add_site_raw_handles_empty_site_table` and needs one new test for the raise.
- **D-extra. `serialize_episode` crashes on a live `Episode` with NULL `podcast_audio`** (medium, bug) —
  `serialize_episode` (`serialization.py:283`) calls `serialize_audio(post.podcast_audio)` unconditionally at line
  295, and `serialize_audio:26` reads `audio.pk` on `None`, so the podcast index 500s under `"default"` and renders
  under `"django"`. Reachable: `podcast_audio` is `null=True, on_delete=SET_NULL` (`pages.py:669-673`) and
  `views/media.py:197-207` does not stop you deleting audio attached to a live episode. The ORM path is safe because
  `PostQuerySnapshot` guards the same access (`snapshot.py:199-207`, `if podcast_audio is not None`); the serializer
  has no equivalent. Direction: make `serialize_episode` emit `None` for an absent audio and have the deserializer
  accept it, alongside D1's shared post-field helper, with a test for an episode whose audio was deleted.
  Fix note (2026-09-16, fixed): `serialize_episode` emits `"podcast_audio": None` for an absent audio and
  `deserialize_episode` only rebuilds the audio when the value is not `None`, so both `FeedContext` and
  `BlogIndexContext` accept it. Covered by `test_episode_without_podcast_audio_in_podcast_index`
  (`tests/blog_index_test.py`, podcast index 200 under `"default"`) and
  `test_feeds_do_not_crash_for_episode_without_podcast_audio` (`tests/feed_test.py`, podcast feed still omits the
  episode, blog feed still lists it), plus a serialize/deserialize round trip.
  Not done: `views/media.py` still lets you delete audio attached to a live episode (deliberate).

Strengths: H2 genuinely holds, with ffprobe/ffmpeg/rendition work behind explicit transactional services.
`podcast_numbering.assign_episode_number_for_publish` is a model of careful domain logic (`select_for_update` on the
podcast row, revision and live object updated together, pure predicates, guarded private hook).
`file_replacement.StagedFileReplacementGroup` and the ContextVar-backed `PageLinkHandlerWithCache` are the right
shapes for storage-touching and per-request state, and `PostQuerySnapshot.create_from_post_queryset` groups
specific-model fetches with `in_bulk`, so the M8 N+1 fix is intact.

## Views, API, feeds and comments

The editor API's permission chain and error envelope are the clear standard, the H4 media-view dedup has held, and
the feed hardening orders access checks before the shared cache. The rest is mostly duplication that the hardening
commits paid for twice.

- **V1. Admin media edit deletes the old file before the replacement save can fail** (low, bug) —
  `views/media.py:156`: `_delete_old_audio_files` (`views/audio.py:47-51`) runs before `form.save()`, so a failing
  save rolls the row back to a file already gone while the new upload is orphaned; the editor API path cleans up and
  `StagedFileReplacementGroup` is used only by transcripts/voxhelm. Low, not medium: `create_duration` only runs when
  `duration is None`, `validate_audio_upload` already ran, and the video path catches everything, so the realistic
  window is a storage write error. Direction: capture old names, save first, delete in `transaction.on_commit`, with
  a failure-injection test.
- **V2. Editor slug lookup deserializes every sibling's latest revision** (medium, performance) —
  `api/editor/views.py:419`. A documented deterministic single-object lookup does one `.specific` query plus a
  revision fetch and full StreamField deserialization *per child of the parent* (~2,000 queries for a 1,000-post
  blog); `_check_unique_slug:195` already has the efficient primitive. Direction: prefilter with
  `Q(latest_revision__content__slug=slug) | Q(latest_revision__isnull=True, slug=slug)` then re-check in Python,
  preserving the `ambiguous_lookup` 409 semantics covered by `test_lookup_rejects_ambiguous_latest_draft_slug`; add a
  `django_assert_num_queries` test.
- **V3. Editor API has no service layer; `Post` and `Episode` create/patch are near-verbatim duplicates** (medium,
  duplication) — `api/editor/views.py:762`. The two `patch` and two `post` bodies differ only in serializer class,
  lookup, noun and one `_apply_episode_metadata` call; revision-conflict check, draft-only enforcement, slug lock,
  cover/tags/categories, section merge, `save_revision` and `refresh_from_db` repeat line for line inside a 240-line
  view mixin that carries the whole domain, and the last three hardening commits each edited both copies. Direction:
  `_create_draft`/`_patch_draft` template methods with one `_apply_type_specific_fields` hook (or
  `api/editor/services.py` with thin adapters), `_serialize` moved to an output serializer. Keep the ordering:
  Episode create applies metadata before the atomic block, patch after the base fields.
- **V4. Legacy and editor API generations are mutually dependent and render scope errors differently** (medium,
  coupling, prior M4) — `api/views.py:111`. `cast.api.views` imports `HasEditorScope` and the editor media policies
  while `api/editor/media.py:29` imports `StandardResultsSetPagination` back: a legacy→editor→legacy cycle papered
  over with local imports. `VideoDetailView`/`AudioDetailView` enforce `HasEditorScope` (raising `EditorFlatError`)
  without `editor_exception_handler`, so scope failures render as DRF's `{"detail": ...}` with no `code`. Direction:
  pagination to `api/pagination.py`, policies to `media_permissions.py`,
  `get_exception_handler = editor_exception_handler` on the legacy detail views, body-shape assertions in the scope
  tests. `insufficient_scope` is documented only for the editor API (`api.rst:1185`), so this is an undocumented
  inconsistency rather than a broken contract — still worth fixing because `api.rst:64-66` promises the editor
  envelope for legacy upload validation errors.
- **V5. Collection permission policies are instantiated ad hoc in nine places** (medium, duplication) —
  `api/editor/body.py:53`. `media_permissions.py` holds only audio and transcript; video/audio policies are built in
  `forms.py:99`, `wagtail_hooks.py:61,81`, `body.py:53,72` (per call), `api/editor/media.py:35-36`,
  `views/video.py:16` and `views/voxhelm.py:24`, so the video equivalent of the transcript tightening would touch
  five files. Direction: add `video_permission_policy` to `media_permissions.py`, import all three from there, add an
  AST guard failing on any `CollectionOwnershipPermissionPolicy(` outside it. `body.py` uses function-local imports
  to dodge cycles and `media_permissions` imports `.models` at module level, so check the new import against the
  cycle test.
- **V6. Feed querysets and their stale-blog FIXME are duplicated** (medium, duplication, prior M5) — `feeds.py:101`.
  `RepositoryMixin.get_repository` (99-119) and `FeedContext.data_for_feed_cachable` (`contexts.py:253-268`) hold the
  same two querysets verbatim, including the same `refresh_from_db()` FIXME in two wordings; the base queryset exists
  twice more in `blog_index.unfiltered_published_posts` and `Blog.last_build_date`. Direction: `published_posts(blog)`
  and `published_episodes(podcast)` in `blog_index.py` used by all four sites, then one
  `FeedContext.create_for_request(...)`, resolving the FIXME once. The import-cycle test requires `blog_index.py` to
  import before `django.setup()`, so keep the new `Episode` import function-local.
- **V7. `feeds.py` carries dead guards, never-called hooks and a test-only injection path** (low, architecture, prior
  M5) — `feeds.py:325`. B1 made `Blog.last_build_date` unable to raise `IndexError`; `itunes_categories` (498) and
  `item_keywords` (516) are not Django `Feed` hook names and have no callers; two methods are pure pass-throughs; and
  `repository=` makes `get_object` return `repository.blog` instead of the URL slug, with a comment calling it "kind
  of dangerous", on the production path. Direction: delete the guard, the non-hooks and the pass-throughs, move the
  injection to a test-only subclass. `test_itunes_elements_add_root_elements_index_error` must be deleted with the
  guard, and `repository=` appears ~10 times in `feed_test.py` while production passes only `None`.
- **V8. Styleguide view seeds the database and fetches remote media on GET** (medium, architecture, prior M6) —
  `views/styleguide.py:279`. Dev-only (404 unless `CAST_ENABLE_DEV_TOOLS`, guard at 189-191) but shipped and wired
  unconditionally in `urls.py:68`; every GET creates a user, a `Site` if none exists, blog/podcast/posts/comments,
  and with `CAST_STYLEGUIDE_REMOTE_MEDIA` performs `urlopen()` calls under bare `except Exception`. Of 1595 lines,
  ~300 are scrapers, ~200 fetchers, ~500 seeders, ~100 the actual view. Direction: split into
  `cast/styleguide/{seed,remote,context}.py`, expose seeding as a `cast_styleguide_seed` command, make the view
  read-only — keeping the `cast/{theme}/styleguide/index.html` and `sections.html` contracts for the theme repos.
- **V9. Facet filtering and counting are implemented three times** (medium, duplication) —
  `modal_facet_counts.py:141`. `_apply_selection` re-implements the three `*FacetFilter.filter` methods,
  `_fetch_date_counts` the `TruncMonth` aggregation, `_fetch_*_counts`/`_fetch_*_universe`
  `CountChoicesMixin.fetch_facet_counts` four times, and `FacetCountSerializer.get_facet_counts` is a third
  transform. Direction: `cast/facets.py` with `apply_facet`, `date_counts`, `slug_counts`, `facet_options`, called
  from all three. Treat "decide once on `distinct=True`" as hygiene, not an observed bug: with single-value filters
  and the `post__in` subquery, duplicates are unlikely in practice.
- **V10. Public transcript payload pipeline copied five times with inconsistent errors** (medium, bug) —
  `views/transcript.py:566`. `podlove_transcript_json` opens the file outside its `try`, so a missing storage file
  raises `FileNotFoundError` → 500 while `podcastindex_transcript_json` 404s the identical case and
  `webvtt_transcript` handles nothing; the security-relevant load → `public_episode_from_request` →
  `apply_public_speaker_mapping` → sanitize sequence repeats in `_render_transcript_html` and
  `AudioPodloveSerializer._load_podlove_data` with a third exception set. Direction:
  `cast/transcripts/public_payloads.py` owning IO, mapping and sanitization, raising typed
  `TranscriptArtifactUnavailable`/`TranscriptArtifactInvalid` that all five callers map to 404/400, plus a
  missing-file test per format. `_render_transcript_html` is exempt from the missing-file case
  (`Transcript.podlove_data` returns `{}`); it only diverges in shape.
  Fix note (partial, 2026-09-16): the missing-storage-file half is fixed, including the webvtt twin below. A shared
  `_read_transcript_artifact` helper in `views/transcript.py` reads the artifact once for all three public endpoints,
  so a Podlove, DOTe or WebVTT field whose storage file is gone returns 404 instead of 500, with a regression test
  per format. Still open and deliberately deferred: the `cast/transcripts/public_payloads.py` consolidation with
  typed `TranscriptArtifactUnavailable`/`TranscriptArtifactInvalid` shared by `_render_transcript_html` and
  `AudioPodloveSerializer._load_podlove_data`.
- **V11. Comment posting is duplicated across the AJAX and stock-override views with two parent validators** (medium,
  duplication) — `comments/views.py:343`. `post_comment_ajax` (41-112) and `post_comment` (324-370) each implement
  authenticated name/email fill (already drifted: `username` vs `get_username()`), target resolution,
  `comments_are_open`, `comment_target_is_accessible`, form construction, the `comment_will_be_posted` receiver loop
  (a third copy in the edit view) and row-locked parent validation via two helpers with different exception sets; the
  last two security fixes patched both. Direction: one `submit_comment(request, data, using, *, is_preview)` in
  `comments/services.py` returning a saved comment or a typed rejection with a single `_parent_matches` validator —
  preserving the delegation to django_comments' stock view when there is no parent or the form has errors/preview.
- **V12. `forms.py` is a grab-bag and `SpeakerContributorMappingForm.save` orchestrates domain rules** (low,
  architecture, prior M9) — `forms.py:494`. The 699-line module mixes collection-member model forms, chapter-mark
  parsing, three dynamic speaker forms, the admin search form and the theme selector, and `save` (494-533) decides
  review-state transitions, computes artifact fingerprints and calls `full_clean`/`save` on mapping rows. Direction:
  move the rules into `transcripts/editing.apply_speaker_mapping_updates(updates, now)` and split into
  `forms/{media,transcript,misc}.py`, keeping `cast.forms` re-exporting `AudioForm`, `get_video_form`,
  `TranscriptForm`, `NonEmptySearchForm` and `SelectThemeForm` (imported by `views/media.py`, `api/editor/media.py`,
  possibly theme repos).
- **V-extra. Admin audio replacement never re-probes duration** (medium, bug) — `media_derivation.py:102` calls
  `create_duration` only when `duration is None`, `AudioForm` never resets it on a changed file, and no
  `.duration = None` exists in `src/cast`, so feeds and the podlove player keep the old file's duration while cached
  file sizes *are* refreshed. `tests/audio_views_test.py:313` asserts only the redirect.
- **V-extra. `webvtt_transcript` 500s on a missing storage file** (medium, bug) — `views/transcript.py:606-608`,
  independent of V10's podlove case; `podcastindex_transcript_json` 404s the same condition and
  `tests/transcripts/podcastindex_webvtt_test.py:148` covers only the dote variant.
  Fix note (2026-09-16): fixed together with V10's podlove case; see the V10 fix note.
- **V-extra. A test exists solely to cover an unreachable branch** (low, testing) — `tests/feed_test.py:929-945`
  mocks the XML handler to raise `IndexError` so the dead guard at `feeds.py:325-328` stays covered; V7 must delete
  both together.

Strengths: editor API access control is exemplary and should be the template for everything else — `EditorAPIView`
chains `IsAuthenticated` + `HasWagtailAdminAccess` + `HasEditorScope`, which fails closed on a missing
`required_scopes` entry and on present-but-empty token scopes. Feed hardening landed cleanly:
`unrestricted_page_required` runs before `cache_page` so restricted pages cannot populate the shared cache,
`request_local_feed` gives each miss a fresh instance, `feed_url` is separated from the request host. Comment
handling is careful where it counts: parents row-locked with `select_related(None)`, non-oracle denials,
`comment_was_posted` after commit, session-bound author self-edits.

## Cross-cutting concerns

Settings resolve through a central registry with complete reference docs (all 51 `CAST_*` names verified present),
Voxhelm is a real subpackage with AST-pinned boundaries, the wheel ships no test settings, and the theme contract is
documented in tiers that match the code. The remaining problems are concentrated rather than diffuse.

- **X1. A missing `cast_transcripts` task backend strands `TranscriptGeneration` in QUEUED with an orphaned Voxhelm
  job** (high, bug, prior M3) — `voxhelm/service.py:455`. Reproduced in-process: without that `TASKS` entry,
  importing `cast.voxhelm_tasks` raises `InvalidTaskBackendError` (an `ImproperlyConfigured` subclass) — *after*
  `submit_for_audio()` created the remote job and `queue_submission()` saved `status=QUEUED`, and outside both
  `mark_failed` guards (441-444, 459-461). The admin views catch `ImproperlyConfigured` and flash a message, but
  nothing resets the row, so `ACTIVE_STATUSES` keeps it active, later clicks return `enqueued=False`, and the paid
  job is never collected. Direction: resolve the task reference at the top of
  `enqueue_audio_transcript_generation`, before any remote work, in a `try` that raises without touching the DB,
  keeping `.enqueue()` inside the existing guard; add a `cast.E009` check erroring when Voxhelm is configured but
  `cast_transcripts` is absent, hinting at `docs/operations/deployment.rst`.
  Fix note (2026-09-16, fixed): `enqueue_audio_transcript_generation` now calls `_resolve_completion_task()` before
  the first database read, which keeps the function-body import (the optionality seam) but wraps it so a missing
  backend raises `ImproperlyConfigured` with no remote submission and no row written; `.enqueue()` stays inside the
  `mark_failed` guard. `cast.checks.check_voxhelm_transcripts_task_backend` adds `cast.E009`, reading only Django
  settings and the environment so the check needs no database, and `docs/operations/deployment.rst` documents it.
  Not done: already-orphaned queued rows are not detected or retried.
- **X2. Test settings point `TEMPLATES` DIRS into `src/cast/cast` and theme tests write into the package tree**
  (medium, tooling, prior M6) — `tests/settings.py:12`. `APPS_DIR = ROOT_DIR / "cast"` resolves to `src/cast/cast`,
  which does not exist in git (an M6 leftover), and `tests/theme_test.py::create_new_theme` takes the first loader
  dir and `mkdir(parents=True)`, materialising `src/cast/cast/templates/cast/<theme>/` inside the shipped tree while
  only `rmtree`ing the leaf; `test_get_template_base_dir_choices` has no `try`/`finally`, so a failed assertion
  leaves `.html` files `uv_build` would package. Direction: `DIRS` and `STATIC_ROOT` under `TESTS_DIR`, delete
  `APPS_DIR`, build themes under `tmp_path` with `settings.TEMPLATES` overridden plus the choices-cache clear. The
  residue is an empty directory chain, so a CI guard must look for files, not `git status --porcelain` output.
- **X3. `transcript_sanitization.py` duplicates the transcripts package and has already diverged** (medium,
  duplication, prior H3) — `transcript_sanitization.py:13`. This 482-line module (imported by `player.py`,
  `api/serializers.py`, `views/transcript.py`) keeps byte-identical copies of `VOICE_OPENING_RE`,
  `GENERIC_SPEAKER_PREFIX_RE` and `clean_speaker_label` plus its own `apply_speaker_mapping_to_*`. Drift with
  user-visible effect: `_map_webvtt_payload_line` (324-347) also rewrites `Speaker N:` prefixes while
  `webvtt.rewrite_payload_line` only rewrites `<v>` spans, so an editor rename updates Podlove/DOTe but leaves the
  stored VTT prefix stale. Direction: move the pure mapping/sanitising functions next to `rewrite_speakers` in
  `cast/transcripts/` (upstreaming the prefix handling so both paths agree) and the Episode-visibility policy into
  `audio_access.py` or a `transcripts/visibility.py`. The claim that its `from .models import Episode` reintroduces
  the models cycle is wrong — nothing under `cast/models` or `cast/transcripts` imports this module.
- **X4. The theme contract is enforced only by `DeprecationWarning`s emitted during discovery** (medium,
  architecture) — `models/theme.py:109`. The soft-required tier is the staged-enforcement mechanism the docs
  promise, but the warning is hidden by Python's default filters, by pytest's
  `filterwarnings = ignore::DeprecationWarning` and by runserver, and it fires as a side effect inside
  `get_template_base_dir_candidates`, cached per process, so it is emitted at most once per worker and never on
  `manage.py check`; `CAST_CUSTOM_THEMES` and `TemplateName` built-ins get no existence check at all. Direction: a
  `check_theme_contract` system check iterating `get_template_base_dir_choices()` and probing required names with
  `get_template` (`cast.E010`/`cast.W002`), discovery made side-effect free, `docs/features/themes.rst` pointed at
  the check id. `tests/theme_test.py:420-440` assert the warning is emitted and must be rewritten in the same change.
- **X5. The theme fallback to `plain` is hand-rolled at five call sites** (low, duplication) — `views/theme.py:52`.
  `views/feed.py`, `views/gallery.py` and `views/transcript.py` each define a `_resolve_*_template` with its own
  `*_FALLBACK_THEME = "plain"`, and `blocks.py:248-258` / `views/defaults.py:24-60` implement the same probe
  differently; `select_theme.html` is documented as optional yet the HTMX branch renders it with no fallback, so a
  theme satisfying the documented contract 500s on theme switching. Direction: one
  `resolve_theme_template(template_base_dir, name, fallback=...)` used everywhere including `select_theme`, taking a
  fallback *template name* (or `None`) rather than a theme slug — `blocks.get_block_template` falls back to the
  block's `default_template_name` and `views/defaults.py` to Django's built-in error views.
- **X6. Dev tooling still ships and is imported by every deployment** (medium, architecture, prior M6) —
  `devdata.py:8`. `urls.py:14` imports `views.styleguide` unconditionally and that module (1595 lines, the largest in
  the wheel) imports `cast.devdata` at module level, so every production URLconf load pulls in fixture factories;
  `devdata` hard-codes `auth.models.User` while `Audio.user`/`Video.user` use `get_user_model()`, and
  `ensure_reference_site.py`/`styleguide_prefetch.py` import `RequestFactory` into runtime code and mutate
  `settings.CAST_STYLEGUIDE_REMOTE_MEDIA`. Direction: `cast/dev/` plus a `cast/dev_urls.py` included only when
  `dev_tools_enabled()`, a small `build_internal_request()`, parameters instead of settings mutation, `runner.py`
  moved to `tests/` (updating `TEST_RUNNER`, dropping the coverage omit). The `AUTH_USER_MODEL` breakage is confined
  to actually using the styleguide/`ensure_reference_site`, not URLconf load.
- **X7. Three settings accessors still live outside `CAST_SETTING_REGISTRY`** (low, architecture, prior M2) —
  `voxhelm/client.py:137`. The nine `CAST_VOXHELM_*` settings keep inline defaults in `from_settings` and
  `voxhelm/settings.py`, absent from the registry, the `TYPE_CHECKING` stubs and `check_cast_setting_types`;
  `CAST_ENABLE_DEV_TOOLS`/`CAST_ENABLE_STYLEGUIDE` resolve in `dev_tools.py` with their own inline `False`; and
  `views/styleguide.py:600` reads `int(getattr(settings, "POST_LIST_PAGINATION", 5))`. Direction: register them, have
  `voxhelm/settings.get_setting` fall back to the registry default, replace the `getattr`, add an AST test that no
  `getattr(settings, "CAST_` remains outside `appsettings.py`. Do **not** give the voxhelm floats/bools a strict
  `check_type`: `get_setting` falls through to `os.getenv`, so `CAST_VOXHELM_POLL_TIMEOUT = "900"` is legitimate and
  would be newly flagged — check `../homepage` and `../python-podcast` first.
- **X8. The `voxhelm` package re-exports 55 names, so it has no real boundary** (low, coupling, prior M3) —
  `voxhelm/__init__.py:81` still exports everything the pre-split monolith had, including
  `cast.models.Transcript`/`TranscriptGeneration` and internals like `open_url`, `read_response_bytes` and
  `replace_file`, so the intended seam (settings + service + exceptions) is invisible and every helper is frozen as
  public API. Direction: trim `__all__`, drop the model re-exports, have tests import from
  `.client`/`.service`/`.task_refs`. Keep `get_transcript_generation_status_context` and `transcript_complete` (or
  update `views/voxhelm.py:21` and `management/commands/generate_transcripts.py:12` in the same slice); grep
  `from cast.voxhelm import` across `src/` and `tests/` first.
- **X9. Ruff's selection excludes `I`, so the isort config is dead** (low, tooling) — `pyproject.toml:126`. The
  pinned selection has no import-sorting rule and pre-commit shares the config, so `[tool.ruff.lint.isort]` has no
  effect; `ruff check --select I src tests` reports 57 auto-fixable `I001` findings. Direction: add `"I"` and run
  `--fix` once, or delete the table; it reorders imports in files like `views/styleguide.py`, so land it as a
  standalone formatting commit.
- **X10. Asset-freshness logic is duplicated between `checks.py` and `scripts/check_asset_freshness.py`** (low,
  duplication) — `checks.py:19`. Both implement the same extension set, mtime comparison and source→manifest pair
  table, so a new bundle needs two edits. Direction: keep the pure functions in one module and have the script import
  them. Three premises are weaker than stated: CI's "Verify committed assets are up to date" is a
  `git diff --exit-code` after a rebuild and never invokes the script (its only consumer is `just verify-assets`),
  neither theme repo calls it, and the two pair tables differ on purpose. Prefer making CI use the script over
  deleting it — it is covered by `tests/checks_test.py` and backs the `cast.W001` check documented in
  `docs/releases/0.2.53.rst`.
- **X-extra. `cast.transcripts.webvtt` is internally inconsistent** (medium, bug), independent of X3:
  `webvtt.get_speaker_labels` (`transcripts/webvtt.py:44-47`) reports generic `Speaker N` labels that
  `services.get_speaker_labels` surfaces to the editor, but `rewrite_payload_line` (193-202) rewrites only `<v>`
  spans, so the editor offers labels `services.rewrite_speaker_labels` cannot rename in the VTT artifact. X3's
  fix must correct `webvtt.py`'s own extraction/rewrite pair, not just the duplicate.

Strengths: `CAST_SETTING_REGISTRY` plus module `__getattr__` (copy-on-read, `TYPE_CHECKING` stubs) is a clean single
source of truth that `check_cast_setting_types` and `comments/appsettings.py` derive from, and every `CAST_*` name in
`src/` is documented. `VoxhelmClient` is small and defensive: bearer auth only to the configured origin, no-redirect
artifact downloads, bounded reads, explicit terminal states. Packaging and CI are solid: `uv_build` with
`module-root = src`, a verified wheel with no test settings, tox envs applying the real migration graph with per-env
media roots. The theme system's prior low finding is fixed and `docs/features/themes.rst` matches the code exactly.

## Tests, tooling and frontend

The coverage gate produces real tests, not pragma sprawl: 37 `pragma: no cover` in 28.7k source lines (17 in
`devdata.py`), 5 `noqa` in `src`, 2233 test functions. The debt is on the test-suite side, mostly M10-split debris.

- **T1. The M10 split left 33 file-level ruff blankets hiding 849 unused imports, shadowed fixtures and uncollected
  tests** (high, testing, prior M10) — `tests/repository/rendering_test.py:1`. Each fragment inherited the original
  ~70-line import header and silenced the fallout with `# ruff: noqa: F401,F811,I001`. The F811 suppression is the
  hazard: `post` is defined in `tests/conftest.py:726`, `tests/repository/conftest.py:119` **and**
  `rendering_test.py:225`, and `blog_data`/`renditions_for_post`/`post_with_link_to_itself`/`debug_settings` exist
  twice; `tests/repository/conftest.py:148` and `helpers.py:94` hold `def test_...` bodies pytest never collects
  (both have collected twins). Direction: remove the blankets, run `ruff check --fix --select F401,I001 tests`,
  hand-resolve the two (benign) F811s, delete the duplicate fixtures and dead bodies, then add `I` to `select`.
  Caveat: fixtures imported into a module namespace (`from tests.repository.helpers import blocker, debug_settings`)
  are used by pytest, not Python, so `--fix --select F401` deletes them — review that hunk by hand.
- **T2. Copy-pasted `superuser` (x6) and `transcript_urls` (x7) fixtures** (medium, duplication, prior M10) —
  `tests/api/editor_media_test.py:59`. The identical `superuser` is defined in six `tests/api/editor_*_test.py`
  modules while `tests/api/conftest.py` holds only mp3 fixtures, and `transcript_urls(transcript)` repeats verbatim
  in all seven `tests/transcripts/*_test.py` modules, a directory with no conftest. Direction: `superuser` to
  `tests/api/conftest.py` (purely additive for the two modules lacking it), a new `tests/transcripts/conftest.py`,
  `rf_request` lifted to the root conftest, and the four ad-hoc `transcript` overrides in
  `tests/endpoint_authorization_test.py` (at `tests/` root, not under `tests/transcripts/`) folded into named
  variants so they stop shadowing `tests/conftest.py:553`.
- **T3. Root conftest regrew to 1048 lines / 70 fixtures; four test modules are back over 1000 lines** (medium,
  testing, prior M10) — `tests/conftest.py:217`. M10 trimmed it to 876; it is now larger than before the fix. ~150
  lines implement the reused-sqlite schema fingerprint and ~60 hand-maintain Wagtail's FTS table and three triggers
  in raw SQL (because `--no-migrations` skips the `RunSQL` migration) with no comment naming the migration they
  mirror, next to 70 unrelated domain fixtures; `feed_test.py` (1443), `api/editor_posts_test.py` (1254),
  `cast_comments_internals_test.py` (1082) and `comment_author_edits_test.py` (1053) exceed the fix note's ~940-line
  target. Direction: create the deferred `tests/support/` package (`reuse_db.py` registered via `pytest_plugins`, the
  only supported way to register hook-bearing modules; `wagtail_bootstrap.py` with a migration pointer; `media.py`
  for the media builders), move comment fixtures into a `tests/comments/` package, split `feed_test.py`.
- **T4. TypeScript is never type-checked and `just js-coverage` cannot run** (medium, tooling) —
  `javascript/tsconfig.json:12`. All 13 sources are `.ts` with `strict: true`, but Vite/esbuild and Vitest only strip
  types and nothing runs `tsc --noEmit`, so the flag is decorative; the `paths` alias also disagrees with
  `vite.config.ts`'s `@ -> ./src/`. Separately `vitest run --coverage` needs `@vitest/coverage-v8`, present in the
  lock only as an optional peer and absent from `node_modules`, so the recipe fails on a fresh checkout (reproduced).
  Direction: add `typescript`, `@types/node` and `@vitest/coverage-v8` to devDependencies plus a `typecheck` script
  run in the CI `javascript` job, drop `@types/jest` (Vitest 4 ships globals via `vitest/globals`), fix or delete
  `paths`.
- **T5. `DeprecationWarning` is globally silenced while supporting Django 5.2–6.1 and Wagtail 7.0–8.0** (medium,
  tooling) — `pyproject.toml:141`. 20 tox envs and a history of compatibility breaks found after the fact, yet the
  one early signal is discarded everywhere, including the `*-django61-wagtail80` envs whose purpose is to hear it;
  Django's `RemovedInDjangoXXWarning` classes subclass `(Pending)DeprecationWarning`, so both signals drop.
  Direction, staged: first surface them in the `django61`/`wagtail80` tox factors, then move the ini filter to
  `error::DeprecationWarning` with targeted `ignore:<message>:DeprecationWarning:<module>` entries built from that
  run — flipping straight to `error` surfaces third-party noise across 20 envs at once. Use pytest's own
  `-W default::DeprecationWarning -W default::PendingDeprecationWarning` for the first step, **not**
  `PYTHONWARNINGS`: verified in a scratch project that the env var only suppresses pytest's built-in defaults, after
  which `apply_warning_filters` re-inserts the ini `ignore::DeprecationWarning` ahead of it and the warning stays
  hidden, while `-W` (a command-line filter, applied last) does surface it.
- **T6. Plain pytest runs share and `rmtree` the same media root** (medium, testing) — `tests/conftest.py:203`.
  [2026-08-10-test-media-root-isolation.md](2026-08-10-test-media-root-isolation.md) isolated tox but left plain
  pytest on the fixed `tests/media` path, and every developer recipe uses plain pytest, so two concurrent local runs
  delete each other's uploads and produce the documented spurious `ffprobe ... returned non-zero exit status 1`
  failures — worked around by hand today (CI runners are isolated, so the exposure is local). Direction: in the
  session autouse fixture use `tmp_path_factory.mktemp("media")`/`mktemp("private-media")` with a session-scoped
  `override_settings(MEDIA_ROOT=..., CAST_PRIVATE_MEDIA_ROOT=...)`, keep the tox env-var overrides, drop the `rmtree`
  pair. Verified feasible: `appsettings` resolves the private root at access time and `private_storage` caches per
  location string.
- **T7. 37 test files and the root conftest depend on the shipped `cast.devdata`** (medium, coupling, prior M6) —
  `tests/conftest.py:30`. `devdata.py` is test scaffolding (binary blobs, factory helpers) that ships in the wheel
  and is coverage-excluded line by line, yet `generate_blog_with_media`, `create_post`, `create_python_body` and
  `create_transcript` are used across `tests/repository`, `tests/transcripts`, `tests/models`, `tests/api` and
  `tests/voxhelm`; every pragma there is a permanent hole in the 100% gate. Direction: move the builders to
  `tests/support/devdata.py`, keep in `src` only what the styleguide needs, renamed and fully covered. Important
  correction: the styleguide is **not** the only non-test consumer — `example/scripts/*.py` import
  `generate_blog_with_media`, `create_user`, `add_audio_to_body`, `create_audio`, `create_python_body` and
  `create_transcript` from `cast.devdata`, so keep a thin re-export or re-point those scripts in the same slice.
- **T8. Lint and type gates are narrower than configured** (low, tooling, prior M11) — `pyproject.toml:126`. The
  isort block is dead (X9); mypy has no `warn_unused_ignores`, so 16 of 30 `type: ignore`s in `src` are stale and 16
  carry no error code; the `ignore_missing_imports` blanket hides ~219 import errors (mostly legitimately untyped
  third parties, but also any future typo); tests are excluded entirely, so 41k lines get no type feedback.
  Direction: set `warn_unused_ignores`, `enable_error_code = ["ignore-without-code"]` and `warn_redundant_casts`,
  replace the blanket with per-module overrides, add `tests` to `files` — with the `tests.*` override
  (`disallow_untyped_defs = false`, `follow_imports = skip` removed) in the same change or mypy emits thousands of
  errors. Adding `"B"` to ruff `select` is a larger step than `I` and belongs on its own.
- **T9. Architecture and development docs are out of sync with the layout** (low, docs) —
  `docs/architecture.rst:94` has the page-model location wrong, `docs/development.rst:322` pointed at
  `tests/models_test.py::TestPostModel::test_post_slug` (moved to `tests/models/posts_test.py` by the M10 split;
  fixed with this note), and the "Code Organization" tree (277-287) lists 9 entries for a package with ~50 top-level
  modules plus `transcripts/`, `voxhelm/`, `comments/`, `admin_urls/` and `models/repository/`. Direction:
  regenerate the tree from the real layout; consider a docs test asserting every ``path.py`` it mentions exists.
- **T10. Vite manifest post-processing is hand-duplicated in the justfile and CI** (low, duplication) —
  `justfile:149`. The six-step move/strip-newline/copy dance exists twice with different shell semantics, and a third
  mechanism (`scripts/check_asset_freshness.py`, X10) is documented in `development.rst:262` but used by neither, so
  an output-layout change must be fixed twice or CI's `git diff --exit-code` guard fails for everyone. Separately
  `justfile:109,116` and `workflow.yml:193` still `rm -f docs/cast.api.rst ...` while `docs/conf.py:17` has
  `extensions = []`. Direction: one `scripts/build_frontend.py` called from both, and delete the apidoc `rm -f` lines
  (a shared script stays outside coverage `source`, which is `src/cast`).
- **T11. Audio and video Wagtail chooser JS are sed-identical copies outside the TS pipeline** (low, duplication,
  prior H4) — `static/cast/js/wagtail/audio-chooser.js:1`. 446 lines of jQuery in three audio files are
  byte-for-byte the video files after a rename; living outside `javascript/src/` they get no TypeScript, no bundling
  and no Vitest coverage, while `contributor-link-select.js` is tested only by importing the built file. Direction:
  move them to `javascript/src/wagtail/` as TypeScript with one `createMediaChooser(kind)` factory plus unhashed Vite
  entries, and port the test to import from source. The served static paths must stay identical or the widget
  `Media.js` entries change in the same commit, and CI's asset guard must cover the new output directory.
- **T12. Test-only leftovers in the shipped package and test settings** (low, testing, prior M6) —
  `tests/settings.py:12`. `src/cast/runner.py` (a `manage.py test` → pytest shim) still ships, is referenced only by
  `tests/settings.py:66` and is hidden from the 100% gate via the coverage `omit` list — dead code the gate was meant
  to flush out; `APPS_DIR`/`TEMPLATES` DIRS point at a non-existent directory (X2), `STATICFILES_DIRS` duplicates
  `AppDirectoriesFinder`, and `tests/test_heading_migration.py` is the only `test_*.py` module among 106 `*_test.py`
  files. Direction: delete `runner.py`, its `TEST_RUNNER` line and the omit entry (with a release-notes entry, since
  it is a shipped if undocumented module); simplify `APPS_DIR`; rename the outlier; pin
  `python_files = ["*_test.py"]` — which contradicted `AGENTS.md` until this note's slice fixed the convention there.
- **T-extra. `AGENTS.md` steered new tests at the naming outlier** (low, docs) — it said new tests use `test_*.py`
  and showed `tests/test_file.py::TestClass::test_case` while 106 of 107 modules use `*_test.py`. Fixed with
  `docs/development.rst:322` in this note's slice; any `python_files` pin (T12) must stay aligned.
- **T-extra. `javascript/vite.config.ts` and `vite.comments.config.ts` are ESM in a package.json with no
  `"type": "module"`** (low, tooling), so `npx vitest run` warns they are ESM loaded as CommonJS and they stop
  loading on the next Vite major. Fix: add `"type": "module"` or rename them to `.mts`.
- **T-extra. `.pre-commit-config.yaml:33-63` carries a ~30-line commented-out `mirrors-mypy` hook** (low, tooling)
  — a stale `additional_dependencies` list pinned to v1.11.2, while the live mypy gate runs only in CI and
  `just typecheck`. It is the only place pre-commit mentions type checking and misleads contributors; delete it or
  replace it with a `local` hook calling `uv run mypy`.

Strengths: coverage discipline is real rather than pragma-driven — 2233 test functions with 716 `django_db` marks and
exactly one `transaction=True`. `tests/import_cycle_test.py` is an AST layering guard plus a subprocess test that
`import cast.blog_index` works before `django.setup()`, cited by the architecture docs as the enforcement mechanism
for the transcripts/voxhelm boundaries. The reused-sqlite lifecycle is thoughtfully engineered: a schema fingerprint
that self-heals a stale `--reuse-db --no-migrations` database, plus `migrations-{oldest,latest}` envs applying the
real migration graph. The frontend flow is guarded rather than trusted: CI rebuilds and fails on
`git diff --exit-code` against the committed bundles.

## Status of the 2026-07-02 findings

Fully fixed and now marked in that note: B1, B2, H2–H6, M4, M5, M8, M9, M11, M12, Low-3. Still open, with the
residual tracked above: H1 → D2, D8; M1 → D3; M2 → X7; M3 → X1, X8; M6 → X2, X6, T7, T12; M7 → D1, D4;
M10 (worse) → T1, T2, T3; Low-1 → D8; Low-2 → D10; Low-4 → D5's `refresh_from_db` FIXME and V7; Low-5 → theme 3
plus the missing ffprobe/ffmpeg check; Low-6 → [2026-09-07-security-review.md](2026-09-07-security-review.md)
and V9; Low-9/Low-10 → T10. Unchanged, untracked elsewhere: Low-7 (`RemoveNullBytesMixin` mutates `request.GET`,
`api/views.py:360-383`), Low-8 (repo-root clutter; the sdist half is answered by `uv_build` with `module-root = src`),
Low-11 (`slow` marker used by two modules), H6-residual (import-time comment-form base-class selection,
`comments/forms.py:27-30`).

## Recommended sequence

1. **Bug fixes and test hygiene first** — small, independently valuable, no new abstractions: (1) X1, resolve the
   task reference before the remote Voxhelm call plus the `cast.E009` check; (2) D1 and D-extra, one shared
   post-field serialization helper with a default-vs-django parity test; (3) V10 and its webvtt twin, uniform 404
   mapping for missing transcript artifacts; (4) V2, the editor slug-lookup SQL prefilter with a query-count
   assertion; (5) X2, test settings and theme fixtures under `tests/`/`tmp_path`; (6) the admin audio re-probe on
   file replacement; (7) `"type": "module"` plus `typescript`/`@vitest/coverage-v8` and a `tsc --noEmit` CI step
   (T4); (8) T1 and T2, remove the ruff blankets, resolve the shadowed fixtures and dedupe the copied ones;
   (9) T6, a per-session test media root.
2. **Then the three seams**, each shaped as its own backlog item before implementation: a **publication policy
   service** (theme 2), a **media ingestion service** with an SSRF-safe fetch helper (theme 3), and a
   **transport-neutral content converter** (theme 4). Each is independently valuable and each unblocks several
   deferred backlog items.
3. **Then the Wagtail v3 evaluation**, measured against those seams rather than today's coupling — the publication
   policy and the DRF-free converter are its prerequisites, so the verdict lands on a codebase where "reuse
   upstream" is a small change rather than a rewrite.
4. **Then the read-model decision (D5) and the rest of H1** (D2, D7, D8): cache-or-drop the cachable round trip,
   move render state onto the context object, make the model fields-only. Default theme design, view transitions,
   template-contract promotion, paged feeds and v3 previews are all waiting on this.
5. **Fold the duplication items in when touching their area** rather than as standalone slices: D4, D6, D7, D9, D11,
   D12, V1, V3–V7, V9, V11, V12, X3–X10, T3, T7–T12. Several are one-line-plus-tests once the seam exists.

Deferred on purpose (unchanged from the backlog): local authoring/sync, the external desktop client and podcast feed
import await Cast Studio evidence; embed blocks, remote media import, media replacement and Markdown input await the
ingestion and converter seams plus consumer demand; default theme design and view transitions need design direction
and H1 completion; contributor follow-ups have no demand.
