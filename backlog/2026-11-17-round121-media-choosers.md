# Modal-local media chooser state and lifetime

Round 121 B09–B11, based on fresh `origin/develop` at
`bf0265de9d88d2d1cbd100bd1e00a241bee36780`. All six scout slices still applied;
none needed an owner decision. Local branch: `codex-q/r121-django-cast`.
No push, merge, PR, release, deployment, external reviewer or work-app write.

## Implemented

- `media-chooser-dom-scoped-to-own-modal`: captured modal-local search fields,
  collection, tags, results, uploads and errors for Audio and Video.
- `media-chooser-search-latest-intent-wins`: one generation for result intents,
  aborted superseded requests, immediate invalidation on input and cancellation
  of obsolete debounce timers on page/tag/collection/submit actions.
- `media-chooser-retirement-cancels-pending-work`: Bootstrap hide and Wagtail
  dialog hide events, onload step retirement, detached/replaced-body detection,
  timer/request cancellation and namespaced handler removal. Choice navigation
  is owned too, so its late response cannot advance a closed modal.
- `media-chooser-upload-single-inflight-submission`: one upload attempt, disabled
  submit controls, failure/retry ownership, fenced success/error publication.
  Aborting a browser request cannot undo an upload already accepted server-side.
- `media-chooser-clear-coherent-widget-state`: null resets public/hidden state,
  title, Edit link and blank presentation. Clear supports old class selectors
  and current Wagtail data attributes; actual telepath duplication stays empty.
- `media-chooser-user-change-notifies-editor`: one native bubbling change per
  changed user-selected ID; hydration, same-ID choice and repeated Clear stay
  silent.

The two shipped controllers remain aligned without a new chooser framework.
`docs/media/overview.rst` documents the frontend contract; pending release notes
are in `docs/releases/unreleased.rst`. The previous `0.2.68.rst` pending notes
were moved there intact so there is still exactly one unreleased notes page,
with no false release declaration. No versions, consumer pins, schema,
public-theme structure or backend data/locking behavior changed.

## Regression evidence

The first B09 run failed all six Audio/Video isolation and ordering cases on the
unmodified scripts. The subsequent B10 lifetime cases failed all ten cases;
adding upload regressions produced fourteen failures. The B11 run then failed
four state/event cases on the unmodified widget scripts. Fixes passed each set.
The final focused Vitest suite contains 38 passing cases, including native
Wagtail dialog events, synchronous abort callbacks, late navigation/step results,
missing-title validation and the shipped telepath adapter's copy/hydration path.
All fixture media and records are synthetic. The final upload fixtures use the
actual `media-chooser-upload-` prefix; two additional red cases exposed and
verified modal-local title validation for these names. File-title population is
also scoped to the changed upload input.

## Local qualification and external acceptance

Logs are in
`/Users/jochen/workspaces/ws-work-planning/coordination/codex/logs/cx-r121-django-cast/`.
Use the workspace tool directory to avoid the read-only default uv tools path:

```sh
UV_TOOL_DIR="$PWD/../.cache/uv-tools" just check
UV_TOOL_DIR="$PWD/../.cache/uv-tools" just check-compatibility
UV_TOOL_DIR="$PWD/../.cache/uv-tools" just check-python
```

`just check` passes: Ruff, mypy (184 files), isolated collection, 5,554 Python
tests, 100% statement/branch coverage, JS typecheck/tests/build/freshness, docs
and both Python audits. After the last JS-only changes, `just check-javascript`
passes with 264 tests (38 chooser regressions) and zero npm vulnerabilities.
Both Python audits also pass with `XDG_CACHE_HOME="$PWD/../.cache"` and the
`UV_TOOL_DIR` above, avoiding advisory-cache write warnings.

The first compatibility run had two failures solely because two unreleased
notes pages existed temporarily; the other four environments passed. The
release-note consolidation passes the docs-path regression (44 tests). The two
previously failing environments both pass their repeat run with:

```sh
UV_TOOL_DIR="$PWD/../.cache/uv-tools" uvx --from tox==4.61.2 --with tox-uv==1.36.0 tox p -p 2 -e py311-django52-wagtail70,py312-django60-wagtail7latest
```

All six configured compatibility environments now pass, including their v3
experiment commands. Python 3.13/Django 6.1/Wagtail 8.1 also passes its full
suite and the 91-test v3 experiment.

The PostgreSQL gate was attempted, despite no changed backend locking behavior:

```sh
UV_TOOL_DIR="$PWD/../.cache/uv-tools" just check-postgres
```

Both configured environments fail setup because there is no local PostgreSQL
service at `127.0.0.1:5432` (`Connection refused`). The clerk must run it with
an isolated test PostgreSQL service. No PostgreSQL server was provisioned here.

The opt-in browser gate is blocked before UI interaction in both cases:

```sh
CAST_RUN_BROWSER=1 uv run pytest tests/media_chooser_browser_test.py -v
```

Chromium aborts during `bootstrap_check_in` for its MachPortRendezvousServer with
`Permission denied (1100)`. The external clerk must run this test with Chromium
outside the sandbox. It uses the real Wagtail page editor/ModalWorkflow and
optional StreamField media blocks: search with a duplicate editor ID, choose,
close during debounce, clear, duplicate/reorder, save draft and reopen. The
assertions include editor change events and saved revision values. This browser
journey has **not** been qualified here. Ordinary and isolated suites intentionally
skip it when opt-in/Playwright are absent.
