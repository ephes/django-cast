# Standalone `heading` block renders as plain text (and is single-level)

## Background

There are two ways to author headings in `Post.body`, and they behave differently:

1. **Rich-text headings — work correctly.** The `paragraph` block is
   `blocks.RichTextBlock()` with no `features=` restriction, so it uses Wagtail's
   default feature set (`h2`, `h3`, `h4`, bold, italic, lists, link, …). Headings
   authored inside rich text render as **real `<h2>`/`<h3>`/`<h4>` tags** at whatever
   level the author picks. Multi-level heading hierarchy is therefore already
   supported.

2. **The standalone `heading` block — broken.** `default_content_blocks()`
   (`src/cast/post_body_blocks.py`) defines
   `("heading", blocks.CharBlock(form_classname="full title"))` — a single string, no
   level, and **no front-end `template=`**. The post-body templates render every block
   with `{% include_block %}` inside `<section class="block-{{ block_type }}">`; for a
   template-less `CharBlock` that emits only the escaped string:

   ```html
   <section class="block-heading">Weeknotes From Real Sources</section>
   ```

   No heading element at all — plain text with a `block-heading` class.
   (`form_classname` styles the Wagtail editor field, not the published page.)

Surfaced from a weeknotes draft whose section titles used the `heading` **block** and
rendered as body text. The sibling section titles there are all one level, so a single
level would be fine for *that* content — but the block cannot express an outline at
all, and it renders flat regardless of level.

## The design question (corrected)

Heading **level is the author's choice** — real content has an h2/h3/h4 outline, so no
fixed level can be right for all headings, and django-cast already honours that via
rich-text headings. So the open question is not "which level" but **what the standalone
`heading` block should be**, given rich text already covers multi-level headings:

1. **Deprecate the `heading` block; author headings in rich text.** Multi-level, works
   today, one obvious mechanism. Callers (incl. daybook) emit headings as rich-text
   `<h2>`/`<h3>` inside paragraph blocks. Keep the block for backwards compatibility
   but give it a rendering template.
2. **Give the `heading` block a level.** Convert to `StructBlock{ text: CharBlock,
   level: ChoiceBlock(h2/h3/h4) }` + a template, making it a first-class multi-level
   heading block. Costs a StreamField migration and changes the overview JSON contract
   (the heading `value` becomes `{text, level}` — see cross-repo impact).
3. **Render it at a fixed documented level** (e.g. `<h2>`) as a simple top-level
   "section title", leaving finer hierarchy to rich text. Small fix, but two heading
   mechanisms with different capabilities is confusing.

**Recommendation:** the mechanism that already respects levels is rich text, so lean
option 1 (or 2 if a dedicated block is genuinely wanted) rather than forcing a fixed
level. Regardless of choice, the `heading` block must stop rendering as plain text —
give it a template at minimum so existing content stops looking broken.

## Immediate daybook implication

For the weeknotes use case, daybook can get correct headings **today, with no
django-cast change**, by authoring section headings as rich-text `<h2>`/`<h3>` inside
paragraph blocks instead of emitting `heading` blocks (`src/daybook/composer.py`,
`src/daybook/cast_smoke.py`, and the weeknotes authoring prompt). That also unlocks
multi-level headings if a weeknote ever needs them.

## Scope

- Decide the `heading` block's fate (options above). Default recommendation: give it a
  rendering template now, and prefer rich-text headings for multi-level content.
- If the block is kept: add `src/cast/templates/cast/blocks/heading.html` and a
  block-render test asserting a real heading element is emitted.
- Document that multi-level headings are authored in rich text, and what the standalone
  `heading` block is for.
- Update `docs/releases/<current-version>.rst` (front-end rendering change).

## Cross-repo impact

`daybook` currently emits overview headings as `{"type": "heading", "value": "<string>"}`.
- The "author via rich text" path (option 1) is a **daybook** change, not a django-cast
  one — django-cast rich text already renders those correctly.
- A **leveled** `heading` block (option 2) changes the heading `value` to an object
  `{text, level}`, which requires a coordinated daybook change — flag before choosing it.

## Done When

- Headings authored either way render as real, correctly-levelled heading elements in
  the `plain` and `bootstrap4` themes.
- The role of the standalone `heading` block vs rich-text headings is documented.
- Tests cover the rendered heading markup.
- Release notes updated.
