# Chapter marks in podcast feeds — implementation plan

Date: 2026-07-07
Branch: `feature/chapter-marks-feeds`
Backlog item: **"Chapter marks in podcast feeds"** (`BACKLOG.md:133`)

## Goal

Emit existing per-episode `ChapterMark` data into podcast feeds in two forms:

1. **Podlove Simple Chapters** — inline `<psc:chapters version="1.2">` containing
   `<psc:chapter start=… title=…/>` under a new `xmlns:psc="http://podlove.org/simple-chapters"`
   namespace.
2. **Podcasting 2.0 chapters** — a `<podcast:chapters url=… type="application/json+chapters"/>`
   element referencing an external JSON document served from a stable URL (existing
   `xmlns:podcast` namespace, already declared at `feeds.py:389`).

Emission is **conditional**: an episode with no chapter marks produces zero extra elements, so
podcast feed XML for chapterless episodes stays byte-stable. No new runtime dependencies.

## Verified facts (read before implementing)

- `ChapterMark` (`src/cast/models/audio.py:410-442`): FK `audio` → `Audio`
  (`related_name="chaptermarks"`), `start = TimeField` (a `datetime.time`, **not** seconds),
  `title = CharField`, `link`/`image = URLField(null, blank)`, `unique_together=(("audio","start"))`,
  no Meta ordering (callers `order_by("start")`).
- `Audio.chapters` property (`audio.py:224-238`) already yields ordered
  `{"start": str(chapter.start).split(".")[0], "title", "href"=link, "image"}` dicts — note it
  **strips fractional seconds** and is keyed `href`, not `link`.
- `player.build_chapters(audio)` (`src/cast/player.py:122-139`) returns
  `[{"start": int_seconds, "title": str}, ...]` (drops unparseable start / empty title). Reused
  for the PC2.0 JSON (`startTime` in seconds).
- Feed per-item emission: `PodcastIndexElements.add_item_elements`
  (`feeds.py:358-385`). `episode = item["post"]`; the per-episode snapshot is
  `repository = self.repository.get_episode_feed_detail_repository(episode)` and URL helpers take
  it (mirror `episode.get_vtt_transcript_url(self.request, repository)` at `feeds.py:368`).
- Namespaces: `PodcastIndexElements.namespace_attributes` (`feeds.py:387-390`). Adding one entry
  propagates to both RSS (`rss_attributes`, `feeds.py:401`) and Atom (`root_attributes`,
  `feeds.py:394`).
- Nested-container emission precedent: `itunes:owner` block (`feeds.py:286-289`) uses
  `handler.startElement(name, attrs)` / `handler.addQuickElement(...)` / `handler.endElement(name)`.
  `itunes:category` (`feeds.py:270-274`) is the same shape with a loop.
- Snapshot machinery (avoids N+1): `EpisodeFeedContext` (`contexts.py:124-138`) carries
  `podcast_audio` + `transcript`; built by `FeedContext.get_episode_feed_detail_repository`
  (`contexts.py:368-376`) from `PostQuerySnapshot.podcast_audio_by_episode_id` /
  `.transcript_by_audio_id`. `PostQuerySnapshot` (`snapshot.py:43-93`) is populated in the Django
  path (`create_from_post_queryset`, `snapshot.py:94-231`; podcast prefetch at
  `snapshot.py:110`, `transcript_by_audio_id` filled at `:186-190`) and rebuilt in the cachable
  path (`contexts.py:create_from_cachable_data:254-339`, transcripts at `:291-294,320`). Cachable
  (de)serialization: `builders.py:169-196` (serialize), `types.py:CachableBlogData:50-73` (dict
  shape), `serialization.py` (`serialize_transcript`/`deserialize_transcript:50-70`).
- `PostQuerySnapshot(...)` construction sites (each must pass the new field): `snapshot.py:215`
  (`cls(...)`), `contexts.py:312` (cachable feed path), `contexts.py:491` (blog/index path — passes
  `podcast_audio_by_episode_id={}` / `transcript_by_audio_id={}`).
- Transcript URL helper precedent: `Episode.get_vtt_transcript_url` (`pages.py:976-982`) and
  `get_podcastindex_transcript_url` (`pages.py:1001-1007`):
  `reverse("cast:<name>", kwargs=…)` + `?episode_id={self.pk}` + `request.build_absolute_uri(...)`.
- Serving endpoints precedent: `views/transcript.py:571-610` — `get_object_or_404(...)` →
  `authorize_*_access(request, …, explicit_anchor_id=request.GET.get("episode_id"))` → guard →
  response. `authorize_audio_access(request, *, audio, explicit_anchor_id=None)`
  (`audio_access.py:92-112`) authorizes by audio and **raises `Http404` on denial (never 403)**;
  the `?episode_id=` round-trips as `explicit_anchor_id`.
- URL routes: `src/cast/urls.py:21-33` (`app_name="cast"`; transcript routes use `<int:pk>`).
- Feed tests: `tests/feed_test.py` — string-contains (`:300-310`), namespaced-xpath parse
  (`:346-357, 442-455`, register the `psc` namespace), namespace-count assert (`:440`), and
  mocked-handler unit tests (`:588-608`, a `DummyHandler` for `startElement/endElement`).
- Version: `0.2.62` (`src/cast/__init__.py:5`, `pyproject.toml:3`) → next release note **0.2.63**.

## Key decisions (locked)

| Topic | Decision |
|-------|----------|
| Slicing | **3 slices**: (1) N+1 data threading, isolated; (2) Podlove PSC inline; (3) PC2.0 external JSON. |
| Conditional emission | No chapter marks → zero extra elements; chapterless feed XML byte-stable. |
| Chapters scope | Audio-scoped (`Audio.chaptermarks`); can exist without a Transcript. |
| Threaded shape | `chapters_by_audio_id: dict[int, list[dict[str, str]]]`, each entry `{"start": <str>, "title": <str>}`. Plain JSON-safe strings → round-trips through the cache with no new (de)serializer (mirrors `has_audio_by_id`, not the model-serializing transcript path). |
| `start` string form | Thread `chapter.start.isoformat()` (full precision, e.g. `"01:02:03"` or `"01:02:03.500000"`). Feed formats to PSC on emit. |
| PSC attributes (v1) | `start` + `title` only (mirrors `build_chapters` v1). `link`/`image` are **out of scope** (documented follow-up), keeping byte-stability tests simple. |
| PSC `start` format | `HH:MM:SS` when no microseconds, else `HH:MM:SS.mmm` (milliseconds, 3 digits). Deterministic helper, unit-tested. |
| PC2.0 JSON endpoint | New view + URL **keyed by audio pk** (`chapters/<int:pk>/`, name `cast:chapters-json`), mirroring the audio-scoped transcript endpoints; authorized via `authorize_audio_access`. New module `src/cast/views/chapters.py` (chapters are not transcripts). |
| PC2.0 JSON body | `{"version": "1.2.0", "chapters": [{"startTime": <int seconds>, "title": <str>}, ...]}`, built from `player.build_chapters(audio)` (`start`→`startTime`). Served with `content_type="application/json+chapters"`. |
| `xmlns:psc` placement | **Declare inline on each emitted `<psc:chapters>` element** (`{"xmlns:psc": "http://podlove.org/simple-chapters", "version": "1.2"}`), **NOT** in `PodcastIndexElements.namespace_attributes`. See "Byte-stability & the psc namespace" below — a root-level declaration would change the root element of *every* RSS/Atom feed (including wholly-chapterless ones) and break the locked byte-stability constraint. `podcast:chapters` (slice 3) reuses the already-root-declared `xmlns:podcast`, so it adds no namespace and needs no special handling. |

## Open question — RESOLVED

**Where to serve the PC2.0 JSON.** Resolved: a dedicated view/URL **keyed by audio pk**
(`path("chapters/<int:pk>/", ...)`, `pk` = `Audio.pk`), authorized with `authorize_audio_access`.
Rationale: chapters live on `Audio` and can exist without a `Transcript`; routing through the
transcript pk would 404 chaptered-but-transcriptless episodes. This mirrors the audio-scoped access
model already used by the transcript endpoints (which authorize on the underlying audio).

## Byte-stability & the `psc` namespace (design constraint resolution)

The locked constraint is that **podcast feed XML stays byte-stable for episodes/feeds without
chapters** (Acceptance Criterion #2). `namespace_attributes` (`feeds.py:387`) feeds the RSS/Atom
**root element** attributes (`<rss … xmlns:…>` / `<feed … xmlns:…>`), so adding `xmlns:psc` there
would mutate the root of *every* feed, including feeds whose episodes all lack chapters — violating
byte-stability. (`xmlns:podcast` is already root-declared unconditionally, but we are not free to
add a second unconditional root namespace without breaking the stated requirement.)

Resolution: **declare `xmlns:psc` inline on the `<psc:chapters>` element itself**. XML namespace
declarations are legal on any element and apply to it and its descendants, and inline `xmlns:psc`
on `<psc:chapters>` is a standard, widely-consumed form of Podlove Simple Chapters in RSS. Result:

- Feeds/items **without** chapters: root and item XML byte-identical to before (nothing emitted).
- Feeds/items **with** chapters: each chaptered `<item>`/`<entry>` carries one
  `<psc:chapters xmlns:psc="…" version="1.2">` block.

Consequence for tests: a feed with *k* chaptered episodes contains `xmlns:psc="…"` exactly *k*
times (not once). The namespace-count assertion becomes "== number of chaptered episodes" (and
"== 0" for a wholly-chapterless feed), replacing the handoff's "== 1" (which assumed a root
declaration).

---

## Slice 1 — N+1-safe chapter data threading (no feed output change)

**Purpose:** carry each episode's chapter list into the pre-built feed snapshot so slices 2 & 3
read it without per-item queries. Produces **no feed XML change** (nothing emitted yet), so all
existing feeds stay byte-stable trivially.

**Files to touch**

1. `src/cast/models/repository/snapshot.py`
   - `PostQuerySnapshot.__init__`: add keyword param + attribute
     `chapters_by_audio_id: ChaptersByAudioId` (new type alias in `types.py`, `dict[int, list[dict[str, str]]]`).
   - `create_from_post_queryset`:
     - Add `"podcast_audio__chaptermarks"` to the podcast `prefetch_related` (extend the
       `select_related("podcast_audio__transcript", "season")` at `:110` and the specific-model
       requery at `:148` — use `prefetch_related` for the reverse FK; do **not** try to
       `select_related` a reverse relation).
     - Init `chapters_by_audio_id: ChaptersByAudioId = {}` near `:126`.
     - **Populate chapters independently of transcript presence.** In the podcast-audio block
       (`:183-190`), add the chapters line **immediately after**
       `podcast_audio_by_episode_id[post.pk] = podcast_audio` (`:186`) and **before** the
       `try: transcript_by_audio_id[...] = podcast_audio.transcript` block. That transcript access
       raises `ObjectDoesNotExist` for transcriptless audios, so putting chapter population inside or
       after it would silently drop chapters for chaptered-but-transcriptless episodes — violating
       the locked "chapters are audio-scoped, can exist without a Transcript" decision. Concretely:
       ```python
       if podcast_audio is not None:
           podcast_audio_by_episode_id[post.pk] = podcast_audio
           marks = _serialize_chaptermarks(podcast_audio)   # transcript-independent
           if marks:
               chapters_by_audio_id[podcast_audio.pk] = marks
           try:
               transcript_by_audio_id[podcast_audio.pk] = podcast_audio.transcript
           except ObjectDoesNotExist:
               pass
       ```
       `_serialize_chaptermarks` iterates `podcast_audio.chaptermarks.all()` (prefetched — sort in
       Python by `start` so the prefetch is reused, **not** `.order_by()` which re-queries),
       producing `[{"start": cm.start.isoformat(), "title": cm.title}]`. Only add a key when the
       list is non-empty (keeps the snapshot/cache small; "no chapters" = missing key).
       **Test:** include a chaptered episode whose audio has **no** transcript and assert its
       chapters still thread through.
     - Pass `chapters_by_audio_id=chapters_by_audio_id` in the `cls(...)` call (`:215`).
   - Add module-private `_serialize_chaptermarks(audio) -> list[dict[str, str]]` (or place on
     `Audio`; see note). Sort by `start` in Python.
2. `src/cast/models/repository/types.py`
   - Add `ChaptersByAudioId = dict[int, list[dict[str, Any]]]` alias.
   - Add `chapters: dict[int, list[dict[str, Any]]]` (or `NotRequired`) to `CachableBlogData`
     alongside `transcripts` (`:61`).
3. `src/cast/models/repository/builders.py`
   - In `data_for_blog_cachable`'s serializer (near `:169-196`): add
     `data["chapters"] = queryset_data.chapters_by_audio_id` (already plain strings/lists → no
     per-item serializer needed).
4. `src/cast/models/repository/contexts.py`
   - `create_from_cachable_data`: rebuild the map with **int-normalized keys** —
     `chapters = {int(audio_pk): marks for audio_pk, marks in data.get("chapters", {}).items()}`
     — and pass `chapters_by_audio_id=chapters` into the `PostQuerySnapshot(...)` at `:312`.
     `data.get("chapters", {})` keeps old cache entries (no `"chapters"` key) working; the `int(...)`
     cast makes the lookup (`chapters_by_audio_id.get(podcast_audio.id, [])`, an int key) survive a
     JSON-serialized cache, where dict keys round-trip as strings. (The existing `transcripts` /
     `podcast_audio_by_episode_id` maps do not cast today because the default feed path builds and
     consumes the cachable dict in-process without JSON serialization; we normalize the new map
     defensively so a future JSON-backed cache cannot silently drop chapters. A test JSON-round-trips
     the cachable dict — `json.loads(json.dumps(data))` — and asserts chapters survive.)
   - Blog/index `PostQuerySnapshot(...)` at `:491`: pass `chapters_by_audio_id={}` (mirrors the
     `transcript_by_audio_id={}` there).
   - `EpisodeFeedContext.__init__` (`:131-138`): add `chapters: list[dict[str, str]]` param +
     attribute (default `()`/`[]`).
   - `get_episode_feed_detail_repository` (`:368-376`): read
     `chapters = self.queryset_data.chapters_by_audio_id.get(podcast_audio.id, [])` and pass to
     `EpisodeFeedContext(...)`.
5. `src/cast/models/repository/__init__.py` — export the new type alias / helper if the module's
   `__all__` pattern requires it (match how `TranscriptByAudioId` is handled).

**Note on the serializer location:** prefer a small module-private helper in `snapshot.py` over a
new `Audio` method, to avoid an `Audio.chapters`-style property that `.order_by()`s (re-queries and
would defeat the prefetch). If a reusable `Audio` method is cleaner for the reviewer, it must use
`sorted(self.chaptermarks.all(), key=lambda c: c.start)` to reuse the prefetch.

**Tests** (`tests/repository_test.py` or `tests/feed_test.py`; match where transcript-threading is
tested — grep `transcript_by_audio_id`):
- Django-models path: build a `FeedContext` from a blog with **N chaptered episodes**; assert
  `get_episode_feed_detail_repository(ep).chapters` is populated and correctly ordered by `start`.
- **N+1 guard:** wrap feed-context construction + iterating every episode's `.chapters` in
  `assertNumQueries(constant)` (or `django_assert_num_queries`) and prove the count does **not**
  grow when episodes go from 1 → N (parametrize N). Mirror the existing blog-index flat-query-count
  guard (release note `0.2.62.rst:53-56`; find its test via `grep -rn "assertNumQueries\|assert_num_queries" tests/`).
- Cachable path: round-trip `data_for_blog_cachable` → `create_from_cachable_data`; assert chapters
  survive and old cache dicts without a `"chapters"` key still deserialize (backward-compat).
- **JSON-key safety:** round-trip the cachable dict through `json.loads(json.dumps(data))` before
  `create_from_cachable_data` and assert chapters are still found by int audio-id lookup (guards the
  string-key regression).
- `isoformat()` precision preserved through the snapshot (a mark with microseconds keeps them).

**Acceptance:** `just check` green (100% branch coverage, mypy, ruff). No feed XML change (add/keep
a byte-stability assertion that a chaptered episode's feed output is identical before/after this
slice — i.e. still no chapter elements). N+1 guard passes.

**Docs/release note:** none (internal-only; no user-visible behavior). Do not touch BACKLOG yet.

---

## Slice 2 — Podlove Simple Chapters inline

**Purpose:** emit `<psc:chapters>` for chaptered episodes in RSS + Atom.

**Files to touch**

1. `src/cast/feeds.py`
   - **Do NOT touch `namespace_attributes`** — see "Byte-stability & the `psc` namespace" above.
     `xmlns:psc` is declared inline on `<psc:chapters>` instead.
   - `PodcastIndexElements.add_item_elements` (`:358-385`): after the transcript block, using the
     already-computed `repository`, read `chapters = repository.chapters if repository else []`. If
     non-empty:
     ```python
     handler.startElement(
         "psc:chapters",
         cast(Any, {"xmlns:psc": "http://podlove.org/simple-chapters", "version": "1.2"}),
     )
     for chapter in chapters:
         haqe("psc:chapter", attrs={"start": _psc_start(chapter["start"]), "title": chapter["title"]})
     handler.endElement("psc:chapters")
     ```
     Guard exactly like the transcript URLs so chapterless episodes emit nothing. (Define the
     namespace URI as a module constant to avoid duplicating the literal between the emit and tests.)
   - Add module-private `_psc_start(iso: str) -> str`: parse the isoformat time string and return
     `HH:MM:SS` (no microseconds) or `HH:MM:SS.mmm` (milliseconds, floor to 3 digits). Deterministic;
     unit-tested directly (incl. a microsecond case and a whole-second case).
2. `docs/features/feeds.rst` — document the Podlove Simple Chapters emission (namespace, element
   shape, conditional behavior, `start` format, v1 = start+title only).
3. `docs/releases/0.2.63.rst` — **create** it (unreleased header, mirror `0.2.62.rst:1-3`), with a
   user-facing bullet for Podlove Simple Chapters in podcast feeds.
4. `docs/releases/index.rst` — add `0.2.63` above `0.2.62` (`:11`).

**Tests** (`tests/feed_test.py`):
- Parse + namespaced xpath (register `"psc": "http://podlove.org/simple-chapters"`): episode with
  chapters emits `<psc:chapters>` with the right `<psc:chapter>` `start`/`title` in the right order,
  in **both** RSS and Atom.
- Namespace declared **inline**: for a feed with *k* chaptered episodes,
  `content.count('xmlns:psc="http://podlove.org/simple-chapters"') == k`; for a wholly-chapterless
  feed the count is `0` and the root element is byte-identical to a pre-change baseline (this is the
  key byte-stability assertion — see the namespace design note above; replaces the handoff's `== 1`).
- Episode **without** chapters: no `psc:` element; assert its `<item>`/`<entry>` and the feed root
  are byte-identical to a pre-change baseline (existing-feed compatibility).
- Mocked-handler unit test asserting the `startElement("psc:chapters", …)` /
  `addQuickElement("psc:chapter", …)` / `endElement` call sequence (`DummyHandler`, mirror `:588-608`).
- `_psc_start` unit tests (whole seconds → `HH:MM:SS`; microseconds → `HH:MM:SS.mmm`).

**Acceptance:** `just check` green; `just docs` builds clean (`-W`). Chaptered RSS+Atom feeds carry
inline Podlove chapters; chapterless feeds unchanged.

---

## Slice 3 — Podcasting 2.0 external chapters JSON

**Purpose:** serve an `application/json+chapters` document at a stable URL and reference it from the
feed via `<podcast:chapters>`.

**Files to touch**

1. `src/cast/views/chapters.py` (**new**): `chapters_json(request, pk)`:
   ```python
   audio = get_object_or_404(Audio, pk=pk)
   authorize_audio_access(request, audio=audio, explicit_anchor_id=request.GET.get("episode_id"))
   chapters = build_chapters(audio)              # [{"start": int, "title": str}]
   data = {"version": "1.2.0",
           "chapters": [{"startTime": c["start"], "title": c["title"]} for c in chapters]}
   return JsonResponse(data, content_type="application/json+chapters")
   ```
   (`JsonResponse` forwards `content_type` to `HttpResponse`, overriding its `application/json`
   default.) No transcript dependency.
2. `src/cast/urls.py`: import `chapters_json`; add
   `path("chapters/<int:pk>/", view=chapters_json, name="chapters-json")` near the transcript routes
   (`:26-33`).
3. `src/cast/models/pages.py`: add `Episode.get_chapters_url(self, request, repository)` mirroring
   `get_podcastindex_transcript_url` (`:1001-1007`). Return `None` when the episode has no chapters
   (derive "has chapters" from `repository.chapters` when a repository is present, else from
   `self.podcast_audio` chaptermarks). Build:
   `reverse("cast:chapters-json", kwargs={"pk": <audio pk>})` + `?episode_id={self.pk}` +
   `request.build_absolute_uri(...)`. Audio pk from `repository.podcast_audio.pk` when present else
   `self.podcast_audio_id`.
4. `src/cast/feeds.py` `add_item_elements`: after the PSC block, if
   `(url := episode.get_chapters_url(self.request, repository)) is not None`:
   `haqe("podcast:chapters", attrs={"url": url, "type": "application/json+chapters"})`.
5. `docs/features/feeds.rst` — document the `<podcast:chapters>` reference + JSON endpoint
   (URL shape, media type, auth = Http404 on denial).
6. `docs/releases/0.2.63.rst` — add a bullet for the PC2.0 external chapters JSON + endpoint.
7. `BACKLOG.md:133` — mark the item `- [x]` and add a short `Notes: implemented 2026-07-07 …`
   line (convention per `BACKLOG.md:182-193`); the user-facing summary lives in the release note
   (no separate done list, per `BACKLOG.md:9`).

**Tests** (`tests/feed_test.py` + a view test near `tests/` transcript-endpoint tests — grep
`podcastindex_transcript_json`):
- Endpoint **authorized** (public episode references the audio): 200, `Content-Type:
  application/json+chapters`, body `version` + `chapters[].startTime`/`title` correct (seconds).
- Endpoint **denied**: unauthorized/restricted or missing/mismatched `episode_id` → **Http404**
  (never 403; existence not leaked). Cover both the no-anchor and bad-anchor paths.
- Endpoint with an audio that has **no** chapters → `chapters: []` (still 200 for an authorized
  request), OR document/choose 404 — **decide in impl**; default: 200 with empty list (a valid
  chapters doc). Note: the feed only references the URL when chapters exist, so an empty doc is only
  reachable by direct request.
- Feed: chaptered episode emits `<podcast:chapters url=… type="application/json+chapters"/>` with a
  URL that resolves to the endpoint, in **both** RSS and Atom; chapterless episode emits none and
  stays byte-stable.
- N+1: extend the slice-1 guard (or add one) so the whole podcast feed with chaptered episodes,
  including `get_chapters_url`, stays flat in query count.

**Acceptance:** all Acceptance Criteria met; `just check` + `just docs` green.

---

## Cross-cutting acceptance (all Acceptance Criteria)

1. RSS + Atom emit inline `<psc:chapters>` and a working `<podcast:chapters>` reference for
   chaptered episodes. ✅ slices 2, 3
2. Chapterless episodes → no chapter elements; chapterless output byte-stable. ✅ all slices
3. JSON endpoint authorizes via `authorize_audio_access` (Http404 on denial). ✅ slice 3
4. No N+1 — query-count guard over the chaptered feed. ✅ slice 1 (extended in 3)
5. Tests: with/without chapters, RSS + Atom, namespace declaration, JSON endpoint
   (authorized + denied), existing-feed compatibility. ✅ slices 2, 3

**Verify:** `just check` (ruff + mypy + full suite @ 100% branch coverage); `just docs`
(`python -m sphinx -b html -W --keep-going docs docs/_build/html`).

## Out of scope / deferred

- PSC `href`/`image` and PC2.0 `img`/`url`/`toc`/`endTime` per-chapter attributes (v1 = start+title;
  `ChapterMark.link`/`image` exist but are deferred — documented follow-up, keeps byte-stability
  tests tractable).
- Any change to `podcast:transcript` / `itunes:*` emission.
- New runtime dependencies (none added).

## Risks

- **Prefetch correctness:** using `.order_by("start")` or `.chapters` (which does) inside the
  snapshot would re-query and defeat the prefetch → N+1. Must sort the prefetched
  `chaptermarks.all()` in Python. The N+1 guard is the safety net.
- **Cache backward-compat:** old cached blog dicts lack a `"chapters"` key; `data.get("chapters", {})`
  handles it (test it).
- **Byte-stability:** every slice must keep chapterless feed XML identical; assert against a
  captured baseline, not just "no psc substring".
- **mypy/coverage strictness:** repo enforces `disallow_untyped_defs` + 100% branch coverage; new
  helpers need full annotations and every branch (empty/non-empty chapters, auth pass/deny) exercised.
