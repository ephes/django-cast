# Architecture-review backlog closeout: M4/M5, M6/M7, M10/M11 (2026-07-03)

Three slices, worked sequentially. Roles: pi (gpt-5.5) implements per task briefs; claude reviews every
diff and runs the gates; each slice is committed once clean ("# "-prefixed messages). Model-layer
phase 2 stays deferred (no concrete driver — deliberate non-goal).

## Slice A — M5 feeds.py dedup + M4 legacy-API freeze

Binding decisions:
1. `api/views.py` response contracts are FROZEN, not migrated. The 2026-06-25 media-detail plan already
   recorded: "Keep the older `POST /api/upload_video/` endpoint working with its current response
   contract." cast-vue holds no hardcoded legacy paths (it consumes URLs exposed via page data), so the
   podlove/player-config/facet-counts/theme response shapes must stay byte-stable. M4's "JSON responses
   from VideoCreateView" is superseded by that recorded decision — the slice documents the module as
   legacy-frozen and points new clients at the editor API. Deviation recorded in the M4 fix note.
2. feeds.py dedup is behavior-preserving for podcast feeds (XML byte-stable) with exactly two additive
   changes to the BLOG feed: `item_pubdate` (+`item_updateddate`) and an explicit `item_guid` =
   `str(post.uuid)` (non-permalink). The guid switch means feed readers see each existing blog post as
   new once, then guids survive slug/URL changes — flagged in the release notes.
3. The `PodcastIndexElements`/`ITunesElements` try/except-AttributeError cooperative-super hack is
   replaced by a statically sound hierarchy (mixins declare `SyndicationFeed` as base so `super()`
   resolves for mypy); `# type: ignore` count in feeds.py drops to zero or each survivor is justified.

## Slice B — M6 test settings out of the package + M7 cache type discriminator

Binding decisions:
1. The package-level test settings module moves to `tests/`; every reference (tox, docs, CI,
   scripts, example) is repointed. `dev_tools.py` names the feature-flag-resolver role
   (name decided in the brief after inventorying importers). Shipped-package check: the sdist/wheel must
   not contain test settings. `devdata.py` split is OUT of scope (matches BACKLOG wording).
2. M7: repository cache serialization stores an explicit `type` discriminator; `deserialize_blog`,
   `FeedContext`, and `BlogIndexContext` branch on it instead of key-sniffing. Backwards compatibility
   with already-cached entries without the field is required (fall back to the old sniff once, or bump
   the cache version — decided in the brief after reading the cache versioning scheme).

## Slice C — M10 test-suite split + M11 remainder

Binding decisions:
1. Split the largest test modules and the 912-line `tests/conftest.py` so no module exceeds ~1000 lines
   without a local conftest; per-directory packages with local conftests; zero test-behavior changes
   (same node IDs where feasible, or a recorded rename map).
2. M11 remainder: audit theme-/dev-only runtime dependencies; factor duplicated tox env deps into a
   base env. Dependency removals only when proven unused at runtime (grep + test evidence).

Gates per slice: full pytest, ruff, mypy, 100% branch coverage (`just check`), sphinx when docs change;
claude reviews each diff before commit. Fix notes + BACKLOG updates land with each slice's docs commit.
