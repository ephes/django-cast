# Search & Filters Redesign (2026-02-08)

**Date:** 2026-02-08
**Status:** Implemented

---

## Problem Statement

The current search/filter UI on blog list pages has significant UX issues:

1. **Takes up too much space** — A "Search" label, input field, and "Filters" button sit prominently between the blog header and the first post, pushing content down the page
2. **No visual affordance** — No icon or recognizable pattern tells users "this is search." The word "Search" with an empty input is ambiguous and technical-looking
3. **Expanded state is worse** — Clicking "Filters" reveals Date/Tags/Categories accordion panels + Ordering + a Search button, consuming ~400px of vertical space before any post appears
4. **Mobile is painful** — On a 375px-wide phone, the filter area dominates the viewport above the fold
5. **Styleguide incomplete** — The styleguide's Forms section shows the filter form but lacks date facets, tag facets, and category facets — making it impossible to preview the full filter UI during development

**Screenshots captured (2026-02-08):**
- Staging desktop (collapsed): Search label + input + Filters button above posts
- Staging desktop (expanded): Date/Tags/Categories panels + Ordering push first post far down
- Staging mobile: Filter area dominates viewport before any content
- Styleguide: Only shows Date dropdown + Ordering, missing facets

**Reference patterns analyzed:**
- **Tailwind CSS docs** — Cmd+K opens a centered search modal (Algolia-powered), zero page footprint
- **steipete.me** — Dedicated `/search` page with clean input, navbar has search icon
- **dev.to** — Always-visible search bar in navbar header
- **rachelandrew.co.uk** — Search icon in sidebar, minimal footprint
- **iphoneblog.de** — Everything behind hamburger menu (poor discoverability)

---

## Decision: Search Modal Overlay

Replace the inline search/filter section on blog list pages with:

1. **A search icon (magnifying glass) in the navbar** — universally recognized, zero page space
2. **Cmd+K / Ctrl+K keyboard shortcut** — power user convenience (desktop only)
3. **A modal overlay** containing the full search + filter form
4. **An active-filter bar** on the blog list page showing applied filters with remove buttons
5. **Updated styleguide** with full filter/search modal preview including all facets

The modal is purely a UI container for the existing Django filterset form. It submits as a standard GET request to the blog list URL with query parameters — no new API endpoints, no JavaScript search engine, no client-side filtering. The existing `PostFilterset` and all its facets work unchanged.

### Key Design Decisions (from review)

| Question | Decision | Rationale |
|----------|----------|-----------|
| Scope: which pages? | **Blog list pages only** | `filterset` context only exists on list pages. No context processor or view changes needed. Detail pages have browser Ctrl+F. |
| Facet click behavior | **Navigate immediately** (current `CountFacetWidget` behavior) | Each facet link (`<a>`) navigates on click, same as today. The modal is a container, not a multi-select form. No widget changes needed. |
| No-JS fallback | **`<noscript>` inline form** | A `<noscript>` block renders a simple search input + submit button on the blog list page. Filters are JS-enhanced only. |
| Date range filter | **Dropped from modal** | Only `date_facets` (month links) are shown. The `date` (DateFromToRange) picker adds complexity and is rarely used by blog readers. The `date` field is intentionally excluded from the modal. |
| Filter panel auto-expand | **Yes** — auto-expand panels with active values | When the modal opens and a filter has active values (from URL params), its `<details>` panel is auto-expanded via JS. |
| Plain RSS button | **Unchanged** — stays in `blog_list_of_posts.html` | The `{% block feeds %}` section is unaffected by this change. |

---

## Detailed Specification

### 1. Navbar Search Icon

**Location:** Right side of navbar, before the theme switcher and follow links. **Only rendered on blog list pages** (guarded by `{% if filterset %}`).

**Markup:**
```html
{% if filterset %}
<button type="button"
        class="cast-search-trigger{% if has_active_filters %} has-active-filters{% endif %}"
        aria-label="{% translate 'Search posts' %}"
        aria-keyshortcuts="Control+k Meta+k"
        data-cast-search-trigger>
  <svg aria-hidden="true" class="cast-follow-icon" width="20" height="20" viewBox="0 0 16 16" fill="currentColor">
    <path d="M11.742 10.344a6.5 6.5 0 1 0-1.397 1.398h-.001l3.85 3.85a1 1 0 0 0 1.415-1.414l-3.85-3.85zm-5.242.656a5 5 0 1 1 0-10 5 5 0 0 1 0 10z"/>
  </svg>
</button>
{% endif %}
```

**Notes:**
- Uses `cast-follow-icon` class (existing convention, not a new `cast-icon`) for consistency with other navbar icons.
- No `<kbd>` shortcut hint is rendered — it was removed because the badge was unreadable in both light and dark themes. The keyboard shortcut (Cmd+K / Ctrl+K) is advertised via `aria-keyshortcuts` for assistive technology.
- SVG uses Bootstrap Icons `bi-search` path data (already used in the Bootstrap 5 theme ecosystem).
- `has-active-filters` class is toggled based on a `has_active_filters` context variable (computed by `has_active_filters()` in `src/cast/filters.py`) which checks only actual filter params (`date_facets`, `tag_facets`, `category_facets`, `search`, `o`) — not pagination or nav-preview params.

**Styling:**
- Icon: 20px magnifying glass SVG, same color as other navbar icons (`var(--cast-text)`)
- Hover: Same as `.cast-follow-link:hover` for consistency
- When filters are active: A small dot indicator (6px circle, `var(--cast-accent)`) positioned top-right of the icon via `::after` pseudo-element

**Behavior:**
- Click → opens the search modal
- Cmd+K (Mac) / Ctrl+K (Windows/Linux) → opens the search modal (with safety rules, see Section 5)
- Escape → closes the modal (handled by modal itself)

### 2. Search Modal

**Trigger:** Clicking the navbar search icon or pressing Cmd+K / Ctrl+K.

**Layout (desktop, ≥768px):**
```
┌──────────────────────────────────────────────┐
│  ╔══════════════════════════════════════════╗ │
│  ║  🔍 Search posts...              [Esc]  ║ │ ← search input, autofocused
│  ╠══════════════════════════════════════════╣ │
│  ║  ▸ Date        ▸ Tags                   ║ │ ← collapsed filter sections
│  ║  ▸ Categories  ▸ Ordering               ║ │
│  ╠══════════════════════════════════════════╣ │
│  ║          [Clear]  [Search]              ║ │ ← action buttons
│  ╚══════════════════════════════════════════╝ │
│           (backdrop / click to close)         │
└──────────────────────────────────────────────┘
```

**Layout (mobile, <768px):**
- Modal slides down from top, full-width
- Same content but filter sections stack vertically
- Max-height: 85vh with internal scroll if content overflows (consistent between spec text and CSS)

**Markup contract:**
```html
{% if filterset %}
<!-- Modal backdrop -->
<div class="cast-search-overlay" data-cast-search-overlay hidden>
  <div class="cast-search-modal" role="dialog" aria-modal="true" aria-label="{% translate 'Search and filter posts' %}">

    <!-- Search form — submits to blog list URL -->
    <form action="{{ page.url }}" method="get" class="cast-search-modal-form">

      <!-- Search input row -->
      <div class="cast-search-modal-header">
        <svg class="cast-follow-icon" aria-hidden="true" width="20" height="20" viewBox="0 0 16 16" fill="currentColor">
          <path d="M11.742 10.344a6.5 6.5 0 1 0-1.397 1.398h-.001l3.85 3.85a1 1 0 0 0 1.415-1.414l-3.85-3.85zm-5.242.656a5 5 0 1 1 0-10 5 5 0 0 1 0 10z"/>
        </svg>
        {{ filterset.form.search|as_crispy_field }}
        <button type="button" class="cast-search-modal-close" aria-label="{% translate 'Close' %}" data-cast-search-close>
          <kbd>Esc</kbd>
        </button>
      </div>

      <!-- Filter panels (collapsed by default, auto-expanded if active) -->
      <div class="cast-search-modal-body">

        {% if "date_facets" in filterset.form.fields %}
        <details class="cast-modal-filter-panel" data-cast-filter-panel="date_facets"
                 {% if filterset.form.date_facets.value %}open{% endif %}>
          <summary>{% translate "Date" %}</summary>
          <div class="cast-modal-filter-content">
            <div class="cast-facet-group" data-cast-facet-group data-limit="12">
              {{ filterset.form.date_facets }}
            </div>
          </div>
        </details>
        {% endif %}

        {% if "tag_facets" in filterset.form.fields %}
        <details class="cast-modal-filter-panel" data-cast-filter-panel="tag_facets"
                 {% if filterset.form.tag_facets.value %}open{% endif %}>
          <summary>{% translate "Tags" %}</summary>
          <div class="cast-modal-filter-content">
            <div class="cast-facet-group" data-cast-facet-group data-limit="12">
              {{ filterset.form.tag_facets }}
            </div>
            <button type="button" class="cast-facet-toggle" data-cast-facet-toggle hidden>
              <span data-show-text>{% translate "Show all" %}</span>
              <span data-hide-text hidden>{% translate "Show fewer" %}</span>
            </button>
          </div>
        </details>
        {% endif %}

        {% if "category_facets" in filterset.form.fields %}
        <details class="cast-modal-filter-panel" data-cast-filter-panel="category_facets"
                 {% if filterset.form.category_facets.value %}open{% endif %}>
          <summary>{% translate "Categories" %}</summary>
          <div class="cast-modal-filter-content">
            <div class="cast-facet-group" data-cast-facet-group data-limit="12">
              {{ filterset.form.category_facets }}
            </div>
          </div>
        </details>
        {% endif %}

        {% if "o" in filterset.form.fields %}
        <details class="cast-modal-filter-panel" data-cast-filter-panel="o"
                 {% if filterset.form.o.value %}open{% endif %}>
          <summary>{% translate "Ordering" %}</summary>
          <div class="cast-modal-filter-content">
            {{ filterset.form.o|as_crispy_field }}
          </div>
        </details>
        {% endif %}

      </div>

      <!-- Actions -->
      <div class="cast-search-modal-footer">
        <a href="{{ page.url }}" class="cast-btn-clear">{% translate "Clear all" %}</a>
        <button type="submit" class="cast-btn-search">{% translate "Search" %}</button>
      </div>

    </form>
  </div>
</div>
{% endif %}
```

**Key differences from original draft (review fixes):**
- Wrapped in `{% if filterset %}` guard — modal only rendered on pages that have a filterset
- Uses `as_crispy_field` for search and ordering fields (preserves Bootstrap form styling, labels, error wrappers)
- Preserves `data-cast-facet-group` + `data-cast-facet-toggle` markup for "Show all / Show fewer" behavior on facets with many items
- Auto-expands `<details>` panels that have active values via `{% if filterset.form.<field>.value %}open{% endif %}`
- Uses `cast-follow-icon` class (existing convention) instead of a new `cast-icon` class

**Facet click behavior:** `CountFacetWidget` renders each facet as an `<a>` with a full query-string `href` that navigates immediately on click. This behavior is **preserved unchanged** — clicking a facet inside the modal navigates the page, closing the modal. The modal acts as a container for discovery, not a multi-select form. The "Search" button is only needed for the text search input.

**Modal behavior:**
- Opens with `hidden` attribute removed + focus trapped inside modal
- Search input is autofocused on open
- Escape key closes the modal
- Clicking the backdrop closes the modal
- Text search form submits as GET on Enter or "Search" button click (standard page navigation)
- Facet clicks navigate immediately (current behavior)
- If filters are already active (URL has query params), the form fields are pre-populated automatically because the filterset is bound to `request.GET` (existing Django form behavior — see `BlogIndexRepository` which passes `request.GET` to `PostFilterset`)
- "Clear all" is a plain link to the blog URL without query params
- Body scroll is locked while modal is open (`overflow: hidden` on `<body>`)

**Accessibility:**
- `role="dialog"`, `aria-modal="true"`, `aria-label`
- Focus trap: Tab cycles within the modal (using robust implementation — see Section 5)
- Escape closes
- Focus returns to the trigger button on close
- All filter panels use native `<details>`/`<summary>` for expand/collapse (well-supported in all modern browsers and assistive tech)

### 3. Active Filter Bar

When the blog list page has active filters (query params in URL), show a slim bar above the post list inside `{% block filters %}` (preserving the block for template overrides):

```
┌─────────────────────────────────────────────────┐
│  Search: "django" ✕  │  Tag: python ✕  │ Clear  │
└─────────────────────────────────────────────────┘
```

**Markup:**
```html
{% block filters %}
{% if has_active_filters %}
<nav class="cast-active-filters" aria-label="{% translate 'Active filters' %}">
  <ul class="cast-filter-tags">
    {% if filterset.form.search.value %}
    <li class="cast-filter-tag">
      <span>{% translate "Search" %}: "{{ filterset.form.search.value }}"</span>
      <a href="{% remove_filter_url 'search' %}" class="cast-filter-tag-remove" aria-label="{% translate 'Remove search filter' %}">✕</a>
    </li>
    {% endif %}

    {% for facet in active_facets %}
    <li class="cast-filter-tag">
      <span>{{ facet.label }}: {{ facet.display_value }}</span>
      <a href="{% remove_filter_url facet.param_name %}" class="cast-filter-tag-remove" aria-label="{% translate 'Remove' %} {{ facet.label }}">✕</a>
    </li>
    {% endfor %}

    {% if filterset.form.o.value %}
    <li class="cast-filter-tag">
      <span>{% translate "Order" %}: {{ filterset.form.o.value }}</span>
      <a href="{% remove_filter_url 'o' %}" class="cast-filter-tag-remove" aria-label="{% translate 'Remove ordering' %}">✕</a>
    </li>
    {% endif %}
  </ul>
  <a href="{{ page.url }}" class="cast-filter-clear-all">{% translate "Clear all" %}</a>
</nav>
{% endif %}
{% endblock filters %}
```

**Changes from original draft (review fixes):**
- Uses `{% if has_active_filters %}` instead of `{% if request.GET %}` — the `has_active_filters` context variable (from `has_active_filters()` in `src/cast/filters.py`) checks only actual filter/search/ordering params, so pagination-only URLs like `?page=2` or nav-preview params do not show an empty active-filter bar
- Uses `<nav>` with `aria-label` instead of `<div role="status">` (review: `role="status"` is wrong for static content; `<nav>` is semantically appropriate for a set of navigation links)
- Preserves `{% block filters %}` from the current `blog_list_of_posts.html` so sites overriding this block continue to work
- Uses `{{ facet.label }}` and `{{ facet.display_value }}` for human-readable chip text (not raw slugs) — see `active_facets` context below
- `{% remove_filter_url %}` strips the page param alongside the named param (pagination reset)

**`active_facets` and `has_active_filters` context variables:**

The active-filter bar needs human-readable labels for facet values (e.g., "WeekNotes" not "weeknotes"). This requires a small helper that resolves slugs to display names from the filterset's choices. Both are provided in `Blog.get_context()` and in the styleguide context.

```python
# src/cast/filters.py

def get_active_facets(filterset, request):
    """Build list of active facet dicts with human-readable labels."""
    active = []
    facet_fields = [
        ("date_facets", _("Date")),
        ("tag_facets", _("Tag")),
        ("category_facets", _("Category")),
    ]
    for param_name, label in facet_fields:
        value = request.GET.get(param_name)
        if value and param_name in filterset.form.fields:
            field = filterset.form.fields[param_name]
            display = value  # fallback to raw value
            if hasattr(field, 'choices'):
                for choice_val, choice_label in field.choices:
                    if str(choice_val) == value:
                        display = choice_label
                        break
            active.append({
                "param_name": param_name,
                "label": label,
                "display_value": display,
            })
    return active


def has_active_filters(filterset, request):
    """Return True only when actual filter/search/ordering params are active."""
    if get_active_facets(filterset, request):
        return True
    if request.GET.get("search"):
        return True
    if request.GET.get("o"):
        return True
    return False
```

**`remove_filter_url` template tag:**

```python
# src/cast/templatetags/cast_extras.py
@register.simple_tag(takes_context=True)
def remove_filter_url(context, param_name):
    """Build URL with the named filter param (and page) removed."""
    request = context["request"]
    params = request.GET.copy()
    params.pop(param_name, None)
    params.pop("page", None)  # always reset pagination when removing a filter
    query = params.urlencode()
    return f"?{query}" if query else request.path
```

**Note:** `src/cast/templatetags/cast_extras.py` was created as a new file for the `remove_filter_url` tag. Templates load it with `{% load cast_extras %}`.

**Styling:**
- Horizontal row, no background (just a subtle bottom border or none — minimal weight)
- Filter tags as small pills with remove (✕) buttons
- Max: wraps to multiple lines if many filters active (flex-wrap). No truncation — all active filters are visible
- "Clear all" right-aligned
- Height: ~40px per line, minimal visual weight

### 4. Remove Inline Search/Filter from Blog List

The current `{% include "./_filter_form.html" %}` in `blog_list_of_posts.html` is **replaced** by:
- The search modal include in `blog_list_of_posts.html` (before `</body>` or at end of content)
- The active-filter bar inside `{% block filters %}`

**What stays:**
- `{% block filters %}` — now contains the active-filter bar instead of the inline form
- `{% block feeds %}` — the Plain RSS button and podcast feed links are **completely unchanged**
- The `filterset` context variable (unchanged — still provided by BlogIndexRepository)
- All filter form fields and facet widgets (unchanged)

**What's removed:**
- The `{% include "./_filter_form.html" %}` call from the `{% block filters %}` content

**What's added:**
- `{% include "./_search_modal.html" %}` — included in `blog_list_of_posts.html` (not `base.html`, since `filterset` only exists on list pages)
- `{% include "./_active_filters.html" %}` — inside `{% block filters %}`
- The navbar search trigger — rendered conditionally in `base.html` with `{% if filterset %}`

**`_filter_form.html` migration:**
The old `_filter_form.html` is **kept as a functional compatibility wrapper** for one release cycle. It renders the same modal include so that sites with `{% include "./_filter_form.html" %}` in template overrides continue to work. A deprecation comment directs developers to the new `_search_modal.html`. After one release, it can be removed.

### 5. JavaScript

The modal JS is inline in `base.html` inside the `initSearchModal()` function, which is called from `initEnhancements()`.

**Key implementation details:**

- **One-time init guard:** `overlay.dataset.castSearchReady` prevents re-binding all listeners on HTMX swaps. The modal overlay lives outside the HTMX swap target (`paging-area`) so its DOM elements persist across swaps.
- **Shortcut safety:** Cmd/Ctrl+K is ignored when focus is in input/textarea/select/contenteditable.
- **Robust focus trap:** Queries focusable elements fresh each time Tab is pressed (handles `<details>` open/close changing the set of visible elements). Filters to `.offsetParent !== null` (only visible elements).
- **Legacy facet toggle isolation:** `initFacetToggles()` (for non-modal facet groups) skips groups inside `.cast-search-modal` via `group.closest('.cast-search-modal')` check. The modal has its own facet toggle logic.
- **No `<kbd>` hint:** The keyboard shortcut badge was removed from the UI because it was unreadable in both light and dark themes. The shortcut is still functional and advertised via `aria-keyshortcuts`.

**Existing JS in `base.html` to update:**
The current `base.html` contains ~200 lines of filter enhancement JS (`initFilterToggle`, `initFilterPanels`, `initFacetToggles`, `buildOrderingDropdown`). These need to be:
- `initFilterToggle` / `initFilterPanels`: **Remove** — these handle the old inline `<details>` filter panel, which no longer exists
- `initFacetToggles`: **Move into modal JS** (see facet group code above) — still needed for show-more/fewer in facets
- `buildOrderingDropdown`: **Keep or move into modal JS** — if the ordering `<select>` inside the modal should be enhanced into a styled dropdown, this function needs to target the modal's select element

### 6. No-JS Fallback

A `<noscript>` block in `blog_list_of_posts.html` provides a minimal search form when JavaScript is unavailable:

```html
<noscript>
  <div class="cast-noscript-search">
    <form action="{{ page.url }}" method="get">
      <label for="noscript-search">{% translate "Search posts" %}</label>
      <input type="text" id="noscript-search" name="search"
             value="{{ request.GET.search|default:'' }}"
             placeholder="{% translate 'Search posts...' %}">
      <button type="submit">{% translate "Search" %}</button>
    </form>
  </div>
</noscript>
```

This provides basic text search without JS. Date/tag/category facet filtering requires JS (the modal). This is an acceptable trade-off — facet browsing is an enhancement, while basic search is a core need.

### 7. CSS/SCSS Changes

**New classes (in `_components.scss`):**

```scss
// --- Search trigger (navbar) ---
.cast-search-trigger {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.35rem;
  border: none;
  background: none;
  border-radius: var(--cast-border-radius);
  color: var(--cast-text);
  cursor: pointer;
  position: relative;  // for active-dot pseudo-element
}
.cast-search-trigger:hover,
.cast-search-trigger:focus-visible {
  color: var(--cast-accent-hover);
}
// Active filter indicator dot
.cast-search-trigger.has-active-filters::after {
  content: '';
  position: absolute;
  top: 2px;
  right: 2px;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--cast-accent);
}

// --- Search modal overlay ---
.cast-search-overlay {
  position: fixed;
  inset: 0;
  z-index: 1055;  // above Bootstrap modals (1050) to avoid conflict
  background: rgba(0, 0, 0, 0.4);
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding-top: 10vh;
  @media (max-width: 767.98px) { padding-top: 0; }
}
.cast-search-overlay[hidden] { display: none; }

.cast-search-modal {
  width: min(600px, 95vw);
  max-height: 85vh;
  overflow-y: auto;
  background: var(--cast-bg);
  border-radius: var(--cast-border-radius-lg);
  box-shadow: 0 16px 48px rgba(0, 0, 0, 0.2);
  @media (max-width: 767.98px) {
    width: 100%;
    max-height: 85vh;  // consistent with desktop — was 100vh, fixed per review
    border-radius: 0;
  }
}

// --- Modal header (search input) ---
.cast-search-modal-header {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 1rem 1.25rem;
  border-bottom: 1px solid var(--cast-border);
}
.cast-search-modal-header .cast-follow-icon {
  flex-shrink: 0;
  width: 20px;
  height: 20px;
  color: var(--cast-text-muted);
}
.cast-search-modal-header input[type="text"],
.cast-search-modal-header input[type="search"] {
  flex: 1;
  border: none;
  outline: none;
  font-size: 1.1rem;
  background: transparent;
  color: var(--cast-text);
}
.cast-search-modal-close {
  flex-shrink: 0;
  border: 1px solid var(--cast-border);
  border-radius: 4px;
  background: none;
  padding: 0.15rem 0.5rem;
  font-size: 0.75rem;
  color: var(--cast-text-muted);
  cursor: pointer;
}

// --- Modal body (filter panels) ---
.cast-search-modal-body {
  padding: 0.5rem 1.25rem;
}
.cast-modal-filter-panel {
  border-bottom: 1px solid var(--cast-border);
}
.cast-modal-filter-panel > summary {
  padding: 0.75rem 0;
  cursor: pointer;
  font-weight: 500;
  list-style: none;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.cast-modal-filter-panel > summary::after {
  content: '▸';
  transition: transform 0.2s;
}
.cast-modal-filter-panel[open] > summary::after {
  transform: rotate(90deg);
}
.cast-modal-filter-content {
  padding-bottom: 0.75rem;
}

// --- Modal footer (actions) ---
.cast-search-modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
  padding: 0.75rem 1.25rem;
  border-top: 1px solid var(--cast-border);
}

// --- Active filter bar (blog list page) ---
.cast-active-filters {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0;
  margin-bottom: 1rem;
  flex-wrap: wrap;
}
.cast-filter-tags {
  display: flex;
  gap: 0.5rem;
  list-style: none;
  margin: 0;
  padding: 0;
  flex-wrap: wrap;
}
.cast-filter-tag {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.2rem 0.6rem;
  background: var(--cast-surface, #f5f5f5);
  border-radius: 999px;
  font-size: 0.85rem;
  color: var(--cast-text);
}
.cast-filter-tag-remove {
  color: var(--cast-text-muted);
  text-decoration: none;
  font-size: 0.75rem;
}
.cast-filter-tag-remove:hover {
  color: var(--cast-accent-hover);
}
.cast-filter-clear-all {
  font-size: 0.85rem;
  color: var(--cast-text-muted);
  margin-left: auto;
}

// --- No-JS fallback ---
.cast-noscript-search {
  padding: 0.75rem 0;
  margin-bottom: 1rem;
}
.cast-noscript-search form {
  display: flex;
  gap: 0.5rem;
  align-items: center;
}
.cast-noscript-search input {
  flex: 1;
}
```

**Removed CSS:** All `.cast-search-bar`, `.cast-search-row`, `.cast-filter-toggle`, `.cast-filter-panels` inline filter styles from the current implementation. These are replaced by the modal styles above. The `.cast-search-kbd` styles were also removed (kbd element removed from template).

**Existing filter-related CSS to keep:** `.cast-facet-group`, `.cast-facet-toggle`, `.tag-pill`, `.filter-badge`, `.cast-date-facet-item` — these style the facet items *inside* panels and are reused in the modal.

**Accessibility fix:** The search input label (rendered by `as_crispy_field`) uses a visually-hidden pattern instead of `display: none`, so screen readers can still access it:
```scss
.cast-search-modal-header label {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
```

### 8. Styleguide Updates

Add a new section to the styleguide between "Forms" and "Post list":

**Section: "Search & Filters"**

The styleguide should display:
1. The navbar search trigger button (with and without active-filter dot)
2. The search modal in its open state (rendered statically, not hidden)
3. The modal with one filter panel expanded, showing sample facets with "Show all / Show fewer"
4. The active-filter bar with sample filter tags
5. Mobile viewport preview (via CSS container or media query demonstration)

**Implementation:** The styleguide view (`src/cast/views/styleguide.py`) provides a `filterset` context with populated facets. The data builder ensures rich filter data:
- **Date diversity:** Posts are spread across distinct calendar months using `dateutil.relativedelta(months=N)` in `_styleguide_post_date()`, guaranteeing each post lands in a different month regardless of the current day-of-month.
- **Tags:** `_ensure_styleguide_tags_and_categories()` assigns 4 tags (`python`, `django`, `wagtail`, `tutorial`) across posts — first post gets 2 tags, others get 1 each (rotating).
- **Categories:** 2 categories (`Today I Learned`, `WeekNotes`) are assigned alternately across posts.
- **Context variables:** `active_facets` and `has_active_filters` are provided in the styleguide context for the active-filter bar and search trigger.

---

## Files to Change

### cast-bootstrap5 (theme repository)

| File | Change |
|------|--------|
| `templates/cast/bootstrap5/base.html` | Add search trigger button to navbar (inside `{% if filterset %}`). Remove old filter JS (`initFilterToggle`, `initFilterPanels`). Keep/move `initFacetToggles` and `buildOrderingDropdown` into modal JS. |
| `templates/cast/bootstrap5/_search_modal.html` | **New file.** Modal overlay with search form + filter panels (Section 2 markup). |
| `templates/cast/bootstrap5/_filter_form.html` | **Compatibility wrapper** for one release: renders `{% include "./_search_modal.html" %}` with deprecation comment. |
| `templates/cast/bootstrap5/blog_list_of_posts.html` | Replace `{% include "./_filter_form.html" %}` in `{% block filters %}` with `{% include "./_active_filters.html" %}`. Add `{% include "./_search_modal.html" %}`. Add `<noscript>` fallback. |
| `templates/cast/bootstrap5/_active_filters.html` | **New file.** Active filter tag bar (Section 3 markup). |
| `static/cast_bootstrap5/scss/_components.scss` | Remove old `.cast-search-bar` / `.cast-filter-toggle` / `.cast-filter-panels` inline styles. Add new modal + trigger + active-filter styles. Keep `.cast-facet-group`, `.tag-pill` etc. |

### django-cast (core)

| File | Change |
|------|--------|
| `src/cast/filters.py` | Added `get_active_facets()` and `has_active_filters()` helper functions. |
| `src/cast/templatetags/cast_extras.py` (**new**) | New file with `{% remove_filter_url %}` template tag. |
| `src/cast/templatetags/__init__.py` (**new**) | Empty init file for templatetags package. |
| `src/cast/models/index_pages.py` | Added `active_facets` and `has_active_filters` to `Blog.get_context()`. |
| `src/cast/views/styleguide.py` | Added `_styleguide_post_date()` using `relativedelta` for month spreading. Updated `_ensure_posts()` to set diverse `visible_date`s. Added `active_facets` and `has_active_filters` to styleguide context. |
| `tests/templatetags_test.py` (**new**) | Tests for `remove_filter_url` tag, `get_active_facets`, and `has_active_filters`. |
| `tests/styleguide_helpers_test.py` | Added test for stale `visible_date` update branch. |

### Sibling repos (template overrides)

| Repo | Impact |
|------|--------|
| `../homepage` | Check `base.html` override — may need the navbar search trigger added manually since it overrides `base.html`. Check if `blog_list_of_posts.html` is overridden. |
| `../python-podcast` | Check `base.html` override — same as homepage. Check if `blog_list_of_posts.html` is overridden. |

**Important:** Both sibling repos override `base.html`. The navbar search trigger is added to the core `base.html`, but these overrides won't automatically pick it up. The migration checklist must include updating these overrides.

---

## Interaction States Summary

| State | Navbar Icon | Modal | Blog List Page |
|-------|-------------|-------|----------------|
| No filters active | 🔍 icon | Hidden | Clean — no filter UI (only `<noscript>` fallback) |
| User clicks icon / presses Cmd+K | — | Opens, search input focused, filter panels collapsed | Backdrop overlay |
| User expands a filter panel | — | Panel opens with facet options | — |
| User clicks a facet link | — | Closes (page navigates with facet applied) | Shows active-filter bar + filtered posts |
| User types search + presses Enter | — | Closes (page navigates with search query) | Shows active-filter bar + filtered posts |
| Filters active, page loaded | 🔍 icon + orange dot | Hidden (pre-populated if opened) | Active-filter bar with removable tags |
| User opens modal with active filters | — | Opens with active panels auto-expanded, fields pre-filled | — |
| User clicks ✕ on a filter tag | — | — | Page reloads without that filter (pagination reset) |
| User clicks "Clear all" | — | — | Page reloads at clean blog URL |
| JavaScript unavailable | Icon does nothing | Not functional | `<noscript>` search form visible |

---

## Acceptance Criteria

1. **Zero filter UI on blog list page by default** — When no filters are active, nothing appears between the blog header area and the first post (except the invisible `<noscript>` fallback)
2. **Navbar search icon visible** on blog list pages, with keyboard shortcut (Cmd+K / Ctrl+K) advertised via `aria-keyshortcuts`
3. **Modal opens** on icon click and Cmd+K/Ctrl+K (when not focused in an input), with search input autofocused
4. **Modal contains all filters** — search, date facets, tag facets, category facets, ordering — with "Show all / Show fewer" toggles on long facet lists
5. **Modal closes** on Escape, backdrop click, close button, or facet link click (navigation)
6. **Form submits as GET** to blog list URL — same URL structure as current filters, existing bookmarks/links work
7. **Active-filter bar** appears when filters are active, with individually removable filter tags showing human-readable labels
8. **Active-filter dot** on navbar search icon when filters are applied
9. **Mobile responsive** — Modal works on 375px viewport (max-height 85vh), filter panels stack vertically
10. **Accessibility** — Focus trap in modal (robust, handles details open/close), `aria-modal`, Escape to close, screen reader labels
11. **No-JS fallback** — `<noscript>` provides basic search form when JS unavailable
12. **Styleguide updated** — New "Search & Filters" section shows the modal and active-filter bar with sample data including date, tag, and category facets
13. **No backend API changes** — Uses existing `PostFilterset` and form rendering
14. **Old inline filter CSS removed** — No dead CSS left from the inline filter approach
15. **Backward compatible** — `_filter_form.html` kept as compatibility wrapper for one release; `{% block filters %}` preserved; plain theme unchanged
16. **Sibling repo updates documented** — Migration checklist includes `../homepage` and `../python-podcast` base.html overrides

---

## Out of Scope

- Live/instant search results (potential Phase 2)
- Full-text search improvements (relevance ranking, fuzzy matching)
- Search analytics or result highlighting
- Dedicated `/search` page (may add later as "Advanced Search" link from modal)
- Changes to the filterset backend logic or facet calculation
- Date range filter (DateFromToRange) — intentionally dropped in favor of date_facets
- Search on post detail pages

---

## Migration / Backward Compatibility

- **URL structure unchanged** — `?search=django&tag_facets=python&o=-date` still works. No URL changes needed.
- **Existing bookmarks** to filtered blog views continue to work.
- **`{% block filters %}` preserved** — Sites overriding this block in `blog_list_of_posts.html` continue to work. The block now contains the active-filter bar instead of the inline form.
- **`_filter_form.html` compatibility wrapper** — Kept as a functional file that renders the modal include for one release cycle, with a deprecation comment. Sites with `{% include "./_filter_form.html" %}` in template overrides continue to work.
- **Sibling repo checklist:**
  - `../homepage/homepage/templates/cast/bootstrap5/base.html` — Add `{% if filterset %}` search trigger to navbar
  - `../python-podcast/python_podcast/templates/cast/bootstrap5/base.html` — Add `{% if filterset %}` search trigger to navbar
  - Check both repos for `blog_list_of_posts.html` overrides
- **Plain theme fallback:** The `src/cast/templates/cast/plain/_filter_form.html` remains unchanged — the modal approach is bootstrap5-theme-specific.
- **Existing filter JS cleanup:** Remove `initFilterToggle` and `initFilterPanels` from `base.html`. Move facet toggle and ordering dropdown enhancement into modal JS.

---

## Resolved Questions (from review)

1. **SVG icon:** Use Bootstrap Icons `bi-search` path data (inline SVG, no icon font dependency).
2. **Animation:** Start with instant show/hide. Can add a subtle 150ms fade-in as polish later.
3. **"Search" button styling:** Primary (accent color) — it's the main action in the modal.
4. **Filter panel auto-expand:** Yes — panels with active values auto-expand when modal opens (via `{% if field.value %}open{% endif %}` on `<details>`).
5. **`<kbd>` removed:** The keyboard shortcut badge was removed because it was unreadable in both light and dark themes. The shortcut is still functional (Cmd+K on Mac, Ctrl+K elsewhere) and advertised via `aria-keyshortcuts` on the trigger button.
6. **Shortcut conflicts:** Shortcut is suppressed when focus is in input/textarea/select/contenteditable. On Mac, ⌘K has no browser default so it's safe. On Windows/Linux, Ctrl+K overrides Chrome address bar focus — acceptable trade-off for a power-user feature, mitigated by the input-focus guard.
