# Repository Read-Model Cleanup Experiment

Status: implemented and merged into `develop` in `0b44f6be`. Kept as historical
context for the local typed-shape decision; no active backlog item remains.

## Summary

Do not add `django-mantle` to django-cast yet. The useful idea is narrower:
extract selected read-side business logic into local typed shapes while keeping
the existing repository contexts and template-facing model-like objects.

The current repository layer already handles project-specific Wagtail behavior
that Mantle does not provide directly: `Page.specific`, `StreamField`, image
renditions, rich-text link priming, request/site-aware URLs, theme compatibility,
and aggregate lookup maps.

## Original Recommended First Slice

Create an experiment branch such as:

```text
experiment/repository-readmodels
```

Keep existing public/template contracts intact and avoid adding a new dependency.

Suggested steps:

1. Extract repeated media lookup rebuild logic from `src/cast/models/repository/contexts.py` into a shared helper.
2. Add explicit `TypedDict` definitions for cacheable dict boundaries between `builders.py` and `contexts.py`.
3. Add small local `attrs` read shapes only where they clarify pure read-side logic, such as cover fallback or
   comment enablement.
4. Keep current repository queries and template-facing model-like objects.
5. Preserve zero-query render behavior and assert that with focused tests.
6. Audit the Wagtail API serializer path for `.specific` / blog lookup N+1 behavior outside the repository layer.

## Success Criteria

- Zero-query render invariants stay intact.
- Cache-boundary typing catches missing keys or shape mismatches earlier.
- Any adapter layer needed for template compatibility stays small.
- Tests become clearer than the current manual snapshot setup.

Stop or limit the experiment if query counts get worse, the adapter layer grows
large, Wagtail reconstruction dominates the work, or typed shapes encourage
misleading immutability around mutable repository state.

## Mantle Decision

Revisit `django-mantle` only if local typed-shape work proves a concrete need for
query-backed projections that the current repository layer does not provide.

## Experiment Findings (2026-06-16)

Run first on branch `experiment/repository-readmodels`, then merged into
`develop`. Baseline before the slice: `tests/repository_test.py` 73 passed,
`mypy src/cast/models/repository/` clean.

### What was implemented (narrow slice)

1. **Extracted the repeated media-lookup rebuild loop** into
   `builders.build_media_lookup(post_pk, *, images_by_post_id, ..., images, ...)`.
   The same nine-line loop appeared three times (`FeedContext.create_from_django_models`,
   `FeedContext.create_from_cachable_data`, `BlogIndexContext.create_from_cachable_data`).
   All three now call the helper. Net effect in `contexts.py`: three ~9-line blocks
   collapse to one 8-line call each, with the grouping logic stated once. Also replaced
   `setdefault(...).update({k: v})` with `setdefault(...)[k] = v` (same behavior, less noise).

2. **Added a `CachableBlogData` TypedDict** (`types.py`) describing the dict that crosses
   the `builders.py` → `contexts.py` cache boundary. The three consumer signatures
   (`FeedContext.create_from_cachable_data`, `BlogIndexContext.create_from_cachable_data`,
   and the two `data_for_*_cachable` producers) now reference it instead of
   `dict[str, Any]` / `dict`. Path-dependent keys (`filterset`, `pagination_context`,
   `blog_url`, `last_build_date`) are modeled with `NotRequired`; keys the builder always
   writes (including `blog_cover_image_url` / `blog_cover_alt_text`) are required, so the
   boundary type matches the producer contract, and consumer-side key typos are caught.
   (Producer-side key removal is not caught, because the builder returns
   `cast("CachableBlogData", data)`, which erases mypy's checking at that point.)

3. **Added a `MediaLookup` type alias** for `dict[str, dict[int, Audio | Video | Image]]`,
   which previously appeared as an inline annotation in three places.

4. Added two focused unit tests for `build_media_lookup` (grouping + empty-post no-op).

### Measured against the success criteria

- **Zero-query render invariants stay intact** — ✅ The existing zero-query tests
  (`test_internal_page_link_is_cached_*`, the round-trip serialization tests) still pass
  unchanged. Full suite: **1609 passed**. The refactor is behavior-preserving; no query
  count moved.
- **Cache-boundary typing catches mismatches earlier** — ✅ Demonstrated: with the old
  `dict[str, Any]`, `data["typo"]` type-checks silently. With `CachableBlogData`, a probe
  renaming `data["template_base_dir"]` → `data["template_base_dirr"]` produces
  `error: TypedDict "CachableBlogData" has no key "template_base_dirr" [typeddict-item]`.
  This is the concrete payoff: typos and renames on the cache boundary are now compile-time
  errors instead of runtime `KeyError`s.
- **Adapter layer stays small** — ✅ No adapter layer was needed. One `cast()` at the
  builder's return statement names the boundary; consumers read the TypedDict directly.
- **Tests become clearer** — partial. The new helper got two readable unit tests, but the
  bulk of the safety still comes from the pre-existing snapshot-style integration tests.
  No reduction in manual snapshot setup was attempted in this slice.

### Findings / judgments

- **Helper extraction is a clear, low-risk win.** Three copies → one. Worth keeping
  independent of the typing question.
- **The TypedDict models the *completed boundary*, not incremental construction.** The
  builder assembles `data` key-by-key as `dict[str, Any]` and casts once at return; trying
  to make the builder body itself `CachableBlogData`-typed fights mypy (a `total=True`
  TypedDict wants all required keys at the literal). Typing the *consumer* side is where
  the value is, and that worked cleanly. This matches the note's "type the boundary"
  intent and avoids the stop-condition of a growing adapter layer.
- **`attrs` read shapes were not needed for cover fallback.** `apply_cover_fallback`
  already takes four scalars and returns a tuple with one test; wrapping it in an attrs
  `CoverImage` shape would add a type without clarifying the two-line fallback rule. Per
  the note's "only where they clarify," this slice was skipped — a real (small) finding,
  not an omission. `attrs` 26.1.0 is available if a future, genuinely branchy read shape
  warrants it.
- **API serializer `.specific` audit (step 6):** No `.specific`/blog N+1 was found in the
  cast-owned serializer path. The public audio endpoints (`AudioPodloveDetailView`,
  `AudioPlayerTranscriptView`) are single-object retrievals; `_get_authorized_post` does
  one `Post.objects.get(...).specific` (O(1) per request), and
  `test_podlove_detail_endpoint_contributor_query_count_is_constant` already pins query
  count independent of payload size. The only list path, `FilteredPagesAPIViewSet`,
  delegates to Wagtail's `PagesAPIViewSet.get_queryset()` and inherits Wagtail's own
  `.specific` handling — any N+1 there lives in Wagtail's API serialization, not the cast
  repository layer, and is a separate (larger) optimization task, not part of this slice.

### Recommendation

The narrow typed-shape slice **proves the hypothesis affirmatively**: local typed read
shapes (the `MediaLookup` alias + `CachableBlogData` TypedDict) clarify the repository
read path and make cache-boundary mismatches compile-time errors, with **no change to
template contracts and no change to query counts**. None of the stop conditions
(worse query counts, growing adapter layer, Wagtail reconstruction dominating, misleading
immutability) were triggered. This supports keeping the slice and **not** adopting
`django-mantle`: the concrete need it would address (query-backed projections) did not
appear.

Diff footprint: `builders.py`, `contexts.py`, `types.py` (+166 / -43) and 39 test lines.
