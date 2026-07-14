# Plan: migrate homepage off the built-in `heading` block, then remove it from django-cast

Status: DRAFT — revised after pi review rounds 1 (9 findings) + 2 (6 findings) folded in
Owner: cast maintainer
Repos touched: `django-cast` (this repo), `homepage` (`~/projects/homepage`)
Out of scope / user-owned: `daybook` (switches to rich-text headings independently);
`python-podcast` and `django-chat` (use their own `show_note_heading` block, not the
built-in one — see "Consumer audit").

## 1. Goal

1. Change homepage's Micropub converter so it stops emitting the built-in `heading`
   block and instead emits rich-text `paragraph` blocks that preserve the real
   heading level (`<h2>`/`<h3>`/`<h4>`). Rich text already renders real heading tags.
2. Remove the built-in `heading` block from django-cast entirely (both models that
   embed it), with a data migration so **existing stored content survives** the
   removal, converting any stored `heading` values to rich-text `paragraph`.

## 2. Why this is safe to remove (consumer audit)

Real, non-test consumers of the *built-in* `heading` block:

| Project        | Emits built-in `heading`? | Mechanism | Disposition |
|----------------|---------------------------|-----------|-------------|
| homepage       | **Yes** | Micropub converter (`converters.py`) | Slice 1 migrates it |
| daybook        | **Yes** | overview prose | user switches to rich text (out of scope) |
| python-podcast | No — custom `show_note_heading` | `CAST_POST_BODY_BLOCKS` in `config/settings/base.py:387` | unaffected |
| django-chat    | No — custom `show_note_heading` | its own StructBlock + template | unaffected |

`{"type":"heading",...}` in python-podcast / django-chat appears **only in test
fixtures** as filler; their converters emit `show_note_heading`. Their *real* stored
data still could, in theory, contain a built-in `heading` if an author added one in the
Wagtail editor — the cast data migration (Slice 3) covers that case for every consumer.

## 3. The critical risk: stored data

`heading` is embedded in **two live models**:
- `Post.body` — via `default_content_blocks()` (`src/cast/post_body_blocks.py:39`) and
  `DEFAULT_CONTENT_BLOCK_NAMES` (`:22`); nested inside the `overview` and `detail`
  StreamBlocks.
- `HomePage.body` — a flat StreamField at `src/cast/models/pages.py:1028`.

Removing a block type from a Wagtail `StreamField` orphans any stored `("heading", …)`
value: Wagtail keeps it as raw undeclared data that no longer renders (and can raise in
some code paths). Therefore a **data migration must convert stored `heading` →
`paragraph` rich text**. Because cast migrations run against every consumer DB on
upgrade, this one migration protects homepage, daybook, python-podcast and django-chat
alike.

**Stored data lives in more than the live field (pi finding #1, Critical).** Wagtail 7
also stores block JSON in **page revisions** — `wagtail.models.Revision.content`, a
**`JSONField`** (verified: `wagtail/models/revisions.py:110`; the field is `content`,
NOT the legacy `content_json`) — for `cast.Post` and `cast.HomePage`. If the data
migration only rewrites the live `body`, a later *revert/publish of an old revision*
resurrects orphaned `heading` blocks. The migration MUST therefore also rewrite the
`body` inside matching `Revision.content` rows (and the page's `latest_revision`) for
both models. Because `content` is a `JSONField`, the value is already a Python dict — no
manual `json.loads`/`json.dumps` of that column is required.

**The migration cannot rely on live block definitions (pi finding #2, Major).** Slice 3
and Slice 4 ship in the **same release**, so when a fresh install runs migrations the
current Python code has *already* removed the `heading` block. `ContentBlock` is also
dynamic (its children come from `default_content_blocks()` at runtime — see §4a).
Therefore the data migration must be a **pure JSON transform** that walks the raw
StreamField/revision JSON directly and does not instantiate, import, or call
`get_prep_value()` on any block class. It is tested with the *current* (post-removal)
code.

**Exact JSON shape (pi finding #3, Major).** Wagtail JSON StreamField data is
**dict-shaped**, not tuples:
- `Post.body` top level: a list of `{"type": "overview"|"detail", "value": [ …children… ],
  "id": "…"}`. Each child is `{"type": "heading", "value": "<text>", "id": "…"}`.
- `HomePage.body`: a flat list of `{"type": "heading", "value": "<text>", "id": "…"}`.
The transform recurses into `overview`/`detail` `value` lists, and for every child with
`type == "heading"` rewrites it in place to
`{"type": "paragraph", "value": "<h2>{html-escaped text}</h2>", "id": <unchanged>}` —
**preserving the block `id`**.

Because django-cast is a **published open-source package**, removing a built-in block is
a breaking change for third-party sites too. See §7 (release/versioning).

## 4a. How `Post.body` is defined — and why it needs NO schema migration (pi finding #4)

`Post.body` is `StreamField([("overview", ContentBlock(section="overview")),
("detail", ContentBlock(section="detail"))])` (`models/pages.py:213-216`).
`ContentBlock.deconstruct()` (`models/pages.py:81-82`) returns
`("cast.models.pages.ContentBlock", [], {"section": self.section})` — it serializes
**only `section`**, never the child block list. The children are injected at runtime from
`default_content_blocks() + configured_content_blocks(section)` (`:79`).

Consequence: **removing `heading` from `default_content_blocks()` produces no field-state
change that `makemigrations` can see for `Post.body`** — no `AlterField` is generated,
and none is needed. The change is purely in *runtime* block availability. By contrast,
`HomePage.body` (`models/pages.py:1026-1034`) lists its blocks **inline**, so removing
the `heading` tuple there **does** change the deconstructed field state and **will**
generate an `AlterField` migration.

So Slice 4's schema migration covers `HomePage.body` only; `Post.body` content is handled
entirely by the Slice 3 data migration. Verify with `makemigrations --check` that no
unexpected `Post.body` migration is produced (and no *missing* one is needed).

## 4. Footprint in django-cast (every site to change)

- `src/cast/post_body_blocks.py:22` — `DEFAULT_CONTENT_BLOCK_NAMES` (drop `"heading"`).
- `src/cast/post_body_blocks.py:39` — `default_content_blocks()` (drop the tuple).
- `src/cast/models/pages.py:1028` — `HomePage.body` (drop the tuple).
- `src/cast/api/editor/body.py:13` — `SUPPORTED_BODY_BLOCKS` (drop `"heading"`).
- `src/cast/api/editor/body.py:187-191` — heading serialization branch (remove).
- `src/cast/api/editor/body.py:300` — `if block_type in ("heading","paragraph")` (adjust).
- `src/cast/devdata.py:98,107` — dev fixtures emit heading blocks (switch to paragraph).
- History migrations (`0001…0059`) reference it — **immutable, do NOT edit**; they
  describe past states. New migrations are additive.
- Docs / release notes (§7).

## 5. Slices

Each slice is independently reviewable, testable, and (where possible) independently
shippable. Ordering matters: **homepage data is protected by cast's own data migration**,
so homepage does not need its own data migration, but homepage's *converter* change
(Slice 1) is independent and can land first. Cast Slices 3→4→5 must land in that order.

### Slice 1 — homepage: Micropub converter emits rich-text headings (repo: homepage)
- `homepage/micropub/converters.py:136-137` (HTML path): fold `h2/h3/h4` into the
  rich-text branch — `return ("paragraph", str(element))` — preserving the original tag
  and therefore the level.
- `homepage/micropub/converters.py:198-201` (markdown path): compute
  `level = min(max(len(heading_match.group(1)), 2), 4)` (clamp 2..4; `#`→h2 to match
  rich-text feature set which offers h2/h3/h4, not h1) and emit
  `("paragraph", f"<h{level}>{escape(heading_text)}</h{level}>")` — **HTML-escape**
  `heading_text` (`django.utils.html.escape`) so markdown heading text cannot inject
  markup (finding #7). (The HTML path uses `str(element)`, already well-formed markup.)
- `homepage/micropub/views.py:109-113`: drop the `heading` preview branch; the
  `paragraph` branch already appends the value verbatim, so the heading HTML renders.
- Tests: update `homepage/micropub/test_micropub_simple.py:92` and any other assertion
  expecting a `heading` block to expect a `paragraph` block whose value contains the
  heading tag. Add a test asserting markdown `##`/`###` produce `<h2>`/`<h3>`.
- Verify: Wagtail default rich-text features include `h2/h3/h4`; `expand_db_html` passes
  heading tags through unchanged, so they render as real headings.
- Acceptance: no code path in homepage emits `("heading", …)`; new content renders
  multi-level headings; existing published homepage content is handled by Slice 3.

### Slice 2 — homepage: confirm/convert any pre-existing stored heading blocks (repo: homepage)
- Determine whether homepage has published `Post.body`/`HomePage.body` content
  containing stored `heading` blocks (`manage.py` query over StreamField data).
- If cast's Slice 3 data migration is present when homepage bumps its cast dependency,
  those blocks convert automatically — so this slice is primarily a **verification**
  step: after upgrading cast + running migrations, assert zero residual `heading` blocks
  in homepage's DB. Only author a homepage-local data migration if homepage must convert
  before it can bump cast.
- Acceptance: homepage DB has zero stored `heading` blocks after migrate.

### Slice 3 — django-cast: data migration converting `heading` → `paragraph` (repo: cast)
- New **data-only** migration implemented as a **pure JSON transform** (per findings
  #1/#2/#3) — it does NOT import or instantiate any block class, because the `heading`
  block no longer exists in the code at the time it runs.
- A shared helper `convert_heading_blocks(data)` that:
  - accepts the parsed StreamField JSON (a list of dicts);
  - for `Post.body`: recurses into each `overview`/`detail` entry's `value` list;
    for `HomePage.body`: iterates the flat list;
  - rewrites every `{"type": "heading", "value": "<text>", "id": …}` in place to
    `{"type": "paragraph", "value": "<h2>{escaped}</h2>", "id": <unchanged>}`,
    **HTML-escaping** the text (`django.utils.html.escape`) and **preserving `id`**;
  - is **idempotent** (a second run finds no `heading` blocks and is a no-op);
  - is **defensive about the value type** (finding #6): only `str` values are escaped;
    a non-string / missing / null `value` is coerced to `""` (documented decision) rather
    than stringified into `"None"`, and is covered by a test.
  - Old stored data has **no level** (always a bare string) → default `<h2>`; documented.
- **Access the data WITHOUT deserializing StreamField (finding #2).** Loading
  `instance.body` or calling `save()`/`save_revision()` would instantiate `StreamValue`
  against post-removal block definitions and choke on orphaned `heading` data. Instead:
  1. **Live bodies** — read raw JSON via `Model.objects.values("pk", "body")` (the
     `JSONField`/`use_json_field=True` StreamField yields the raw list/dict, no
     `StreamValue`); transform; write back with `Model.objects.filter(pk=pk).update(
     body=converted)`. Verify at implementation time that `update()` writes the raw JSON
     without re-instantiating blocks; if `get_prep_value` interferes, fall back to a
     direct JSON-column update. Do **not** call block APIs, `get_prep_value()`, or full
     model validation.
  2. **Revisions** — for every `Revision` whose `content_type` points at `cast.Post` /
     `cast.HomePage`, read `.content` (already a dict via the `JSONField`), transform its
     `"body"` key, and write back via `Revision.objects.filter(pk=…).update(content=…)`,
     preserving all other keys. Reach both models via `apps.get_model(...)` and the
     revision model via `apps.get_model("wagtailcore", "Revision")`.
- **Reverse migration: intentionally irreversible / no-op reverse** (finding #6). A
  reverse cannot restore the original `heading` blocks (level was never stored and the
  block type is gone); declare `RunPython(forward, RunPython.noop)` and document that
  downgrading leaves the converted `<h2>` paragraphs in place. No false "reversible"
  claim.
- Runs in **every consumer DB** on upgrade, protecting homepage/daybook/etc.
- Tests (run against current post-removal code): seed `Post` (overview+detail) and
  `HomePage` with raw `heading` JSON *and* a `Revision` containing a `heading` block; run
  the migration; assert live + revision JSON become `paragraph`/`<h2>`, ids preserved,
  text HTML-escaped, and a second run is a no-op.
- Acceptance: after this migration, no stored `heading` blocks remain in live bodies or
  revisions for either model; content renders.

### Slice 4 — django-cast: remove the block from live definitions + schema migration (repo: cast)
- `post_body_blocks.py`: remove `"heading"` from `DEFAULT_CONTENT_BLOCK_NAMES` and the
  tuple from `default_content_blocks()`.
- `models/pages.py:1028`: remove the tuple from `HomePage.body`.
- `devdata.py:98,107`: replace heading fixtures with paragraph rich-text headings.
- New **schema** migration for **`HomePage.body` only** — `Post.body` produces no schema
  change because `ContentBlock.deconstruct()` omits child blocks (see §4a). Do NOT
  hand-write a `Post.body` `AlterField`.
- After editing, run **`makemigrations`** to generate the `HomePage.body` `AlterField`;
  inspect it (it must touch `HomePage.body` only, not `Post.body`). Then run
  **`makemigrations --check`**, which does not generate anything and must exit 0,
  confirming nothing further is pending (finding #5).
- Tests: adjust any cast test that authors/asserts a `heading` block.
- Acceptance: `makemigrations --check` clean after the generated `HomePage.body`
  migration; test suite green; a Post/HomePage authored via the block set no longer
  offers `heading`.

### Slice 5 — django-cast: programmatic editor API (repo: cast)
- `api/editor/body.py`: remove `"heading"` from `SUPPORTED_BODY_BLOCKS`; remove the
  `heading` serialization branch (`:187-191`); adjust the `("heading","paragraph")`
  grouping at `:300`.
- **Decision (locked): reject.** On receiving a `heading` block from an API client,
  reject with `unsupported_block_type` (consistent with removal — the block no longer
  exists). No coercion.
- Tests: update editor-API tests that exercise heading; add a test asserting a `heading`
  payload is now rejected (or coerced, per decision).
- Acceptance: API no longer advertises/accepts `heading`; tests cover the new behavior.

### Slice 6 — django-cast: docs + release notes (repo: cast)
- Document that multi-level headings are authored in **rich text**, and that the
  standalone `heading` block is removed (with the auto-migration to `<h2>` paragraphs).
- Update `docs/releases/<current-version>.rst` — breaking change + migration note +
  the downstream-consumer note from §6.
- Resolve the backlog item `backlog/2026-07-07-overview-heading-block-rendering.md`.
- **Theme repos (pi finding #9): CHECKED — no changes needed.** `cast-bootstrap5` and
  `cast-vue` contain zero `block-heading` / `"heading"` references in templates, Vue, JS
  or CSS; they render blocks generically via `block-{{ block_type }}`, so block removal
  needs no theme change. (Re-grep at implementation time to confirm still true.)
- Acceptance: docs build; release notes describe the breaking change, the auto-migration,
  and the downstream-consumer follow-up.

## 6. Cross-repo sequencing

1. Land cast Slices 3 → 4 → 5 → 6 (order enforced by migration dependency).
2. Release a cast version containing them.
3. **homepage (strict order, finding #4):** homepage Slice 1 (converter) MUST be deployed
   **before or in the same deployment as** the cast dependency bump — never after. After
   cast removes `heading`, `_create_streamfield_content` builds its `StreamValue` from
   `Post.body.field.stream_block` (`handler.py:233`) and would **fail** if the converter
   still emitted `heading`. Slice 1 works on the current cast too, so shipping it first is
   safe. Then bump cast, run migrations, and do Slice 2 verification.
4. **daybook (gate, finding #3):** the cast data migration only protects *existing* stored
   data — it does NOT stop daybook from *creating new* invalid `heading` blocks. So
   daybook MUST stop emitting/authoring the built-in `heading` block (switch to rich-text
   headings) **before** it bumps to the cast release that removes the block. Same ordering
   constraint as homepage. Implementation is daybook-owned/out of scope here, but this
   ordering is a hard gate, tracked as a daybook follow-up.

### Downstream consumer follow-ups (pi finding #5) — not blockers, but must be tracked
`python-podcast` and `django-chat` carry **test fixtures** containing literal
`{"type": "heading", …}` payloads (e.g. `test_convert_show_notes_command.py`,
`test_custom_player.py`, `test_persistent_player.py`). Their *real* content uses
`show_note_heading`, but these test fixtures reference the built-in block and **will fail
or emit unsupported blocks once they bump to the cast version that removes it** — the cast
data migration does not touch test fixtures created after migration. Action: when each
sibling repo bumps cast, update those fixtures to use `paragraph`/`show_note_heading`.
Record as a tracked follow-up in each repo; flag in cast's release notes ("consumers
using the built-in `heading` block in fixtures/content must migrate").

## 7. Versioning / breaking change (public package)

- This removes a built-in block → **breaking** for third-party cast installs. Treat as a
  minor/major bump per cast's semver policy; the data migration makes existing content
  safe automatically, but the *editor* no longer offers the block.
- Release notes MUST call out: the block is gone, existing `heading` content is
  auto-converted to `<h2>` paragraphs, and multi-level headings live in rich text.
- **Decision (locked): no deprecation window.** Direct removal in a single release,
  relying on the protective data migration (Slice 3) to keep existing content safe. No
  intermediate release that keeps the block with a template/warning.

## 8. Assumptions to verify (before/within implementation)

- A1: **VERIFIED.** cast pins `wagtail>=7.0,<8`; default `RichTextBlock` feature set
  includes `h2/h3/h4`. The only `register_rich_text_features` hook
  (`wagtail_hooks.py:297`) merely swaps the page-link handler for a cache-aware one — it
  does not restrict heading features. `expand_db_html` passes `<hN>` through unchanged.
- A2: **VERIFIED.** Only `Post` (via `ContentBlock`/`default_content_blocks()`) and
  `HomePage` (inline) embed the built-in `heading` block. Re-grep at implementation time.
- A3: **VERIFIED.** `Post.body` data is dict-shaped and nested under `overview`/`detail`
  `value` lists; `HomePage.body` is a flat dict list. The transform recurses accordingly
  (see §3, Slice 3).
- A4: **VERIFIED.** homepage's `CastPostMicropubHandler` writes to cast `Post.body`
  (`homepage/micropub/handler.py:67-77`, StreamValue built from
  `Post.body.field.stream_block`). So the cast Slice 3 migration covers homepage; and
  once cast drops `heading`, homepage's converter MUST already emit rich text or
  StreamValue construction fails — reinforcing §6 sequencing.
- A5: python-podcast / django-chat have no *stored* built-in `heading` blocks in real
  content (only test fixtures — see §6 downstream follow-ups). If any live/revision data
  exists, Slice 3 converts it on upgrade.

## 9. Definition of done

- No django-cast code path defines or accepts the built-in `heading` block.
- After generating the `HomePage.body` `AlterField` migration, `makemigrations --check`
  exits 0 (nothing pending); no `Post.body` schema migration is generated or needed (§4a).
- Data migration converts existing `heading` content to `<h2>` rich-text paragraphs in
  both `Post.body` (overview+detail) and `HomePage.body`, in **both live bodies and page
  revisions** for each model, preserving block `id`s and HTML-escaping text; idempotent;
  covered by a migration test.
- homepage emits rich-text multi-level headings and has zero stored `heading` blocks
  after upgrade; homepage tests green.
- Editor API rejects (or coerces) `heading` per the confirmed decision, with tests.
- Docs + release notes updated; backlog item resolved.
- Final cross-repo review (codex) clean.
