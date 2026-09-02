# Typeahead Search

Date: 2026-07-16

Status: implemented on 2026-07-16 in django-cast and cast-bootstrap5. Retained
as the architecture, performance, and UX decision record.

## Summary

The first typeahead slice should be a destination autocomplete: while a user
types in the existing search field, show a small list of matching post or
episode titles. Selecting a suggestion navigates directly to that page.

Use a bounded server-side query over Wagtail/modelsearch's existing title
autocomplete index. Enhance the existing GET search form with JavaScript, but
keep ordinary form submission as the no-JavaScript and failure fallback.

Do not make the visible post list update on every keystroke in the first slice.
Do not download a full body/title index to every browser. Do not add Algolia,
Meilisearch, Typesense, or another search service for this work.

## Product Boundary

Three different features are often called typeahead:

1. **Destination autocomplete** returns matching posts. Choosing one navigates
   directly to it. This is the accepted first slice.
2. **Instant result filtering** replaces the full post list on every keystroke.
   This is deferred because it adds rendering, URL/history, pagination, and
   search-semantics work.
3. **Query completion** suggests search strings rather than posts. This is
   deferred because it needs a vocabulary or query-history design.

The dropdown must be described as destinations, not as a preview of the full
search result set.

## Current Behavior

django-cast's committed search uses `PostFilterset.fulltext_search()` and
Wagtail/modelsearch's full-text `search()` behavior. It searches the inherited
page title plus `Post.body` and `cover_alt_text`. Search input is normalized and
capped by `cast.search_utils`.

`Post` already inherits Wagtail's `AutocompleteField("title")`, so
`queryset.autocomplete(query)` can find title prefixes without a new field or
index migration. Body and cover alt text are not autocomplete fields.

Theme behavior differs:

- the built-in plain and Bootstrap 4 themes submit a GET form and render the
  filtered `posts` only after navigation;
- cast-bootstrap5 already sends a debounced server request while typing, but it
  updates only facet counts, the no-results state, and submit state inside the
  modal; the post list behind the modal does not change until form submission;
- cast-vue fetches and replaces posts and facet counts only after form submit.

The first typeahead UI therefore adds a suggestion list below the existing
input. It does not replace the main result list.

## Architecture Options

### Accepted: server autocomplete plus a small client cache

Query the blog's live, public, unrestricted descendant posts through Wagtail's
title autocomplete, convert the ranked search results back to a Django
queryset, apply the selected date/tag/category facets, and return at most eight
destinations. The performance spike confirmed that modelsearch rejects related
tag/category filters placed before `autocomplete()` unless those relations are
added as indexed `RelatedFields`; applying them to the ranked result queryset
preserves the intended facet scope without expanding the search index.

Order suggestions by Wagtail's indexed `last_published_at` field, with newest
primary key as the deterministic tie-breaker, rather than modelsearch
relevance. The performance spike found that relevance scoring was
the dominant cost for broad prefixes on a 10,000-post SQLite archive, while
recent-first ordering reduced that query from roughly 161 ms to roughly 2 ms.
Recent matching destinations are also a clear, deterministic ordering for a
small navigation list. This ordering uses the `FilterField("last_published_at")`
already inherited from `Page`, so it needs no new index field.

This keeps publication state, visibility rules, facets, and Wagtail search
backend selection on the server. The browser owns only interaction state,
request cancellation, and a small page-lifetime cache keyed by normalized query
plus selected facets.

### Deferred: browser-side index

A downloaded title index could be useful for a deliberately offline or small
theme, but it is not the core default. It introduces archive-sized payloads,
publication invalidation, and a second implementation of facet/filter rules. A
full-body index would be much larger.

Chunked client indexes such as Pagefind are a better fit for immutable static
site builds than for a dynamic Wagtail site.

### Deferred: instant post-list replacement

This is a natural later option for cast-vue, but it must use the same matching
semantics as the committed search, manage loading and history without losing
the existing URL contract, and preserve pagination and facet behavior.

### Excluded for now: external search services

Algolia, Meilisearch, Typesense, and similar services are not options for the
first slice. Wagtail's existing database/search-backend abstraction is the
operational boundary.

## Matching Semantics

Suggestions are title-only.

- The title is visible in every suggestion, so users can understand why it
  matched.
- Wagtail recommends autocomplete fields only for text displayed in results.
- A body-prefix match that displays an unrelated-looking title would feel
  broken without excerpt/highlight work.
- Body autocomplete would increase index size and is unnecessary for a
  destination picker.

Selected date, tag, and category facets constrain suggestions. The current
search text must not first be applied through full-text search and then
intersected with title autocomplete. Apply `autocomplete()` once to the
live/public blog queryset, obtain its ranked Django queryset, and apply only the
non-search facets to that result.

Full-text and autocomplete semantics intentionally differ. For example,
autocomplete may match the title `Hello World` for `hel`, while committed
whole-word full-text search may return no result for `hel`. The UI must therefore
follow these rules:

- selecting a suggestion navigates directly to that post;
- Enter with no manually selected suggestion submits the existing full-text
  form;
- the first suggestion is not automatically selected;
- do not label suggestions as full search results or add a misleading
  "see all results" count;
- never disable ordinary form submission because a live full-text count is
  zero.

A later server-rendered zero-results improvement may offer title-prefix
destinations as "Did you mean?" links.

## Proposed API Contract

Prefer a dedicated read endpoint rather than adding suggestions to the existing
facet-count response. Suggestions and facet counts use different matching
semantics, debounce intervals, cache keys, and failure behavior.

Example request:

```text
GET /cast/api/search-suggestions/17/?search=hel&date_facets=2026-07&tag_facets=django&category_facets=tutorial
```

Example response:

```json
{
  "query": "hel",
  "suggestions": [
    {
      "id": 42,
      "title": "Hello World",
      "url": "/blog/hello-world/",
      "visible_date": "2026-07-10T09:00:00Z"
    }
  ]
}
```

Contract constraints:

- live, public, unrestricted descendants of the requested Blog/Podcast only;
- normalized query echoed in the response;
- minimum two non-whitespace characters, enforced on the server and client;
- at most eight suggestions;
- no HTML, highlight offsets, full-body excerpts, pagination, or full-result
  count;
- `200` with an empty suggestion list for short/no-match queries;
- bounded response size, with a target below 10 KiB;
- endpoint errors never prevent normal form submission.

Expose the endpoint URL through a core context/property such as
`page.search_suggestions_api_url`. Themes choose whether to enhance the input.
Do not add a new setting: the existing `CAST_FILTERSET_FACETS` search entry and
the theme's use of the URL are sufficient gates.

## Frontend and Accessibility Contract

The first frontend integration belongs in cast-bootstrap5. The built-in plain
and Bootstrap 4 themes remain submit-only. Let the endpoint contract settle
before adding cast-vue behavior.

Use the WAI-ARIA editable combobox/listbox pattern:

- keep DOM focus in the search input;
- use `role="combobox"`, `aria-autocomplete="list"`, `aria-expanded`,
  `aria-controls`, and `aria-activedescendant`;
- render a sibling listbox with stable option IDs;
- Down/Up moves the active suggestion;
- Enter navigates only when a suggestion was manually activated; otherwise it
  submits the form;
- Escape closes suggestions and preserves text; in the Bootstrap modal a second
  Escape may close the modal;
- Tab closes suggestions without selecting;
- typing clears the active option without stealing focus; when a settled list
  is already open, keep it visible but temporarily non-selectable while the
  matching response is pending so routine prefix refinement does not flicker;
- use at least 44-pixel pointer targets and a scrollable list of roughly six
  visible rows on mobile;
- use a suggestion-specific polite live region rather than sharing the facet
  status region;
- announce settled counts/no-results/errors, not loading or every arrow move;
- never disable the form submit button.

Suggested request behavior:

- start with a 200-250 ms trailing debounce and tune from measurements;
- abort the previous request and also reject responses whose echoed query no
  longer matches the input;
- clear the active suggestion as soon as the query changes and make the
  previously rendered list busy and non-selectable while a new request is in
  flight; replace or close it when the matching response settles;
- show a loading indicator only after a short delay;
- use a page-lifetime LRU cache keyed by normalized query plus facet state;
- treat aborted requests as normal;
- on a real error, close suggestions, announce once, and leave normal search
  available.

The first cast-bootstrap5 integration retained its existing 150 ms facet
debounce, but combined request review showed that it could send a facet request
for nearly every character before the 225 ms suggestion debounce settled. The
implemented interval is therefore 300 ms: suggestions remain responsive while
facet-count work coalesces behind a longer quiet period. Suggestion and facet
requests remain separate because they have different semantics and failure
behavior.

## Pre-Implementation Performance Gate

The performance decision does not require the endpoint or UI. First implement
or prototype only the bounded query operation:

1. start from `blog.unfiltered_published_posts`;
2. run `autocomplete(normalized_query, order_by_relevance=False,
   order_by="-last_published_at")` once without applying full-text search;
3. convert the ranked search results back to a Django queryset;
4. apply selected date/tag/category facets to that queryset;
5. select only the fields needed by the response and cap at eight;
6. resolve public URLs without per-result queries.

Run the same reproducible benchmark on:

- SQLite, because django-cast tests, quickstart, and the example site use it;
- PostgreSQL, because homepage and python-podcast use it in development and
  production;
- synthetic archives of approximately 100, 1,000, and 10,000 public posts;
- a restored read-only consumer-site database if one is already available
  locally, without sending benchmark traffic to production.

The query corpus must include:

- broad two-character prefixes;
- selective three-to-five-character prefixes;
- no-match and whitespace/normalized inputs;
- multiword title prefixes;
- each facet independently and a combined facet selection;
- warm and cold runs.

Measure the query function first, then a minimal JSON endpoint only after the
query passes. Record SQL query count, server processing p50/p95/p99, payload
size, and a small concurrent run rather than relying on one wall-clock sample.

Provisional go/no-go targets on representative local hardware:

- query count is flat as archive size and returned suggestions grow, with a
  target of no more than five SQL queries for the complete response;
- warm server processing p95 at 10,000 posts is at most 150 ms and p99 is at
  most 300 ms;
- ten concurrent clients complete without errors and with p95 below 300 ms;
- the JSON response remains below 10 KiB;
- with a 200-250 ms debounce and 100 ms simulated round-trip time, suggestions
  become visible within 500 ms of the final keystroke at p95.

These are experience budgets, not permanent public guarantees. Record the
hardware, database/backend, archive size, query corpus, and raw results so later
changes can be compared honestly.

If the gate fails, optimize before building the UI: verify the autocomplete
index, remove URL/query N+1s, raise the minimum length or debounce, reduce the
result cap, and decouple/slow the facet refresh. Do not mask a slow query with
more frontend complexity.

## Performance Spike Results (2026-07-16)

The reproducible harness lives in `scripts/benchmark_typeahead.py`, with
isolated database selection in `scripts/typeahead_benchmark_settings.py`. It
creates deterministic Blogs with 100, 1,000, and 10,000 public posts plus one
restricted control per archive, applies deterministic tags/categories/dates,
and runs eight query shapes for 30 warm and five application-cold iterations.

Environment:

- Apple silicon macOS host, Python 3.11.15, Django 5.2.14, Wagtail 7.4, and
  modelsearch 1.3.1;
- SQLite 3.50.4 with `SQLiteSearchBackend`;
- PostgreSQL 17.10 with `PostgresSearchBackend`;
- ten simultaneous reads for the concurrency check.

The first SQLite run with default relevance ordering exposed a real scaling
problem: broad 10,000-post prefixes took roughly 166-214 ms p95 and ten
simultaneous reads took roughly 1.35 seconds p95. Profiling isolated
modelsearch's relevance score as the dominant cost. Switching the destination
list to deterministic recent-first ordering through the inherited indexed
`last_published_at` field removed that cost without changing matching or adding
an index field.

Final results with recent-first ordering:

| Backend | Public posts | Worst warm p95 | Worst app-cold p95 | 10-client p95 at 10k |
| --- | ---: | ---: | ---: | ---: |
| SQLite | 100 | 5.6 ms | 6.3 ms | — |
| SQLite | 1,000 | 5.2 ms | 5.8 ms | — |
| SQLite | 10,000 | 5.4 ms | 6.0 ms | 29.9 ms |
| PostgreSQL | 100 | 5.3 ms | 8.4 ms | — |
| PostgreSQL | 1,000 | 7.7 ms | 10.8 ms | — |
| PostgreSQL | 10,000 | 13.7 ms | 17.3 ms | 21.6 ms |

Across both backends, complete warm responses used four SQL queries,
application-cold responses used at most five, and the largest measured payload
was below 1.3 KiB. Both backends pass every provisional gate by a wide margin.
With the planned 200-250 ms debounce and a simulated 100 ms round trip, the
measured server budget leaves substantial room under the 500 ms p95
interaction target.

This is a go decision for the bounded endpoint and Bootstrap 5 destination
combobox. The measurements are local synthetic results rather than a permanent
public performance guarantee; retain the flat query-count regression test and
repeat the benchmark after the endpoint exists and when search/backend
dependencies change.

## Validation After the Gate

Backend tests must cover scope, visibility restrictions, facet interaction,
normalization, the two-character boundary, stable ordering, the result cap,
and a flat query-count guard.

Frontend tests must cover keyboard behavior, focus/ARIA state, stale response
rejection, aborts, cache keys including facets, no-results/error recovery,
two-stage Escape behavior in the modal, pointer selection, and ordinary form
submission without or after failed JavaScript.

Before delivery, run the repository's full `just check`. Because the first
theme implementation changes cast-bootstrap5 templates, JavaScript, and HTML
structure, update and verify that sibling repository in the same implementation
slice.

## Independent Frontend Review

Claude Code was consulted read-only on the frontend/product design. It
independently recommended the same title-only, server-backed destination
dropdown and emphasized four constraints retained here: do not auto-select the
first suggestion, keep suggestions separate from facet-count semantics, use a
dedicated live region, and never disable ordinary search submission.

Claude Code also reviewed the implemented Bootstrap 5 slice. Its first pass
identified stale destinations after failures, stale active-option state during
a new query, and results reopening after focus left the input. The fixes clear
suggestions and ARIA selection state on query/error transitions and require
input focus before opening; focused regression tests cover each case. Two
re-review rounds closed the remaining live-region, controller-lifecycle, cache
key, and template-contract suggestions; no Critical or Warning findings remain.

Live homepage testing then exposed a visual integration problem: the first
absolute-positioned list covered only the left side of the facet controls,
leaving their disclosure chevrons visible beside it and showing the full-text
no-results warning at the same time as title destinations. The Bootstrap 5
follow-up anchors a compact, title-only elevated panel to the full modal header,
keeps a six-row visible window with scrolling up to the eight-result bound,
makes only the facet body scroll, and suppresses stale full-text warning copy
while destinations are open. Claude Code reviewed the redesign and its state
coordination; the re-review left no Critical or Warning findings.

## Implemented Sequence

1. Ran and recorded the query-only SQLite/PostgreSQL performance spike.
2. Implemented the bounded JSON endpoint and backend tests.
3. Exposed the optional core template/context URL.
4. Implemented and tested the accessible cast-bootstrap5 combobox.
5. Verified the live rendered contract and endpoint locally; automated tests
   cover interaction and accessibility state. Screenshot-based browser QA was
   unavailable in the implementation session because no interactive browser
   backend was connected.
6. Left cast-vue, instant list filtering, excerpts, and zero-result suggestions
   as future decisions driven by measurements and user feedback.

## Completion Record

- The performance gate and recorded results support server-backed title
  autocomplete on SQLite and PostgreSQL.
- The endpoint is bounded, facet-scoped, visibility-safe, and query-count
  guarded.
- Bootstrap 5 provides an accessible progressively enhanced destination
  dropdown.
- Ordinary full-text form submission and no-JavaScript behavior are unchanged.
- Documentation and release notes describe the implemented behavior.
- `just check` and the relevant cast-bootstrap5 checks pass.
