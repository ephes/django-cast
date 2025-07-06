# Django-Cast Gallery Duplicate Image Bug Analysis

## Problem Description

The gallery component in django-cast has a bug when displaying duplicate images (the same image used multiple times in a gallery). While the gallery shows all 5 images correctly, the prev/next navigation buttons don't work properly after the second image.

**Test URL**: http://localhost:8000/blogs/ephes_blog/asdf/

**Gallery Contents**:
1. "Claas und Nora essen Wassereis" (PK=4031)
2. "Opa und Oma Theine stehen an der Agger am Bootsanleger rum." (PK=4029)
3. "Nora und Claas essen Wassereis." (PK=4030) - Note the period
4. "Nora an der Agger" (PK=4028)
5. "Nora und Claas essen Wassereis." (PK=4030) - Duplicate of #3

## Root Cause Analysis

### 1. Primary Key-Based Navigation
The original implementation used image primary keys (PKs) for navigation:
```html
<img id="img-{{image.pk}}" ... />
```

This caused issues with duplicate images:
- Multiple images had the same ID (e.g., two `id="img-4"`)
- JavaScript's `querySelector("#img-4")` only returns the first element
- Navigation to the second duplicate was impossible

### 2. Image Order Preservation Issue
When fetching images from the database, Django's `filter(pk__in=image_ids)` doesn't preserve the order of the input list:

```python
# Original problematic code
values["gallery"] = list(Image.objects.filter(pk__in=image_ids))
# Returns images ordered by PK, not by input order
```

This caused images to be displayed in PK order (0,1,3,4,4) instead of the intended order (0,1,4,3,4).

### 3. Template vs Python Order Mismatch
The core issue was that `add_prev_next()` processed images in one order, but the template rendered them in a different order:
- Python's `add_prev_next()` received images in the order they were processed
- Templates used `forloop.counter0` which assigned IDs based on iteration order
- This caused prev/next attributes to reference wrong image IDs

## Implementation Details

### Web Component Architecture
- **Bootstrap 4**: Uses `image-gallery-bs4` custom element
- **Bootstrap 5**: Uses `image-gallery-bs5` custom element
- Both share nearly identical TypeScript implementations

### Navigation Logic
The web component uses data attributes for navigation:
```javascript
replaceImage(direction: string): void {
    const which = this.currentImage.getAttribute(direction);
    if (which === "false") return;
    const targetElement = this.querySelector("#" + which);
    if (targetElement) this.setModalImage(targetElement);
}
```

### Key Python Functions

1. **`add_prev_next()`** - Adds navigation attributes to images:
```python
def add_prev_next(images):
    for i, (prev, current, next) in enumerate(previous_and_next(images)):
        current.prev = "false" if prev is None else f"img-{i-1}"
        current.next = "false" if next is None else f"img-{i+1}"
```

2. **`bulk_to_python_from_database()`** - Fetches images from database:
```python
# Fixed version preserves order
images_by_id = {img.pk: img for img in Image.objects.filter(pk__in=image_ids)}
values["gallery"] = [images_by_id[pk] for pk in image_ids if pk in images_by_id]
```

## Final Solution

### Template-Based Navigation (Successful)
Instead of trying to synchronize Python and template ordering, the solution calculates prev/next attributes directly in the template:

```django
<img
  id="img-{{forloop.counter0}}"
  data-prev="{% if forloop.first %}false{% else %}img-{{ forloop.counter0|add:"-1" }}{% endif %}"
  data-next="{% if forloop.last %}false{% else %}img-{{ forloop.counter0|add:"1" }}{% endif %}"
/>
```

This ensures prev/next attributes always match the actual rendering order.

## Implementation Summary

### Changes Required:

1. **Python Changes (minimal)**:
   - Fixed `bulk_to_python_from_database()` to preserve image order
   - No changes needed to `add_prev_next()` function

2. **Template Changes (all galleries)**:
   - Changed IDs from `id="img-{{image.pk}}"` to `id="img-{{forloop.counter0}}"`
   - Calculate prev/next in template instead of using Python attributes
   - Updated HTMX templates to use `forloop.counter0` for `current_image_index`

### Fixed Files:
- `/Users/jochen/projects/django-cast/src/cast/blocks.py` (order preservation only)
- `/Users/jochen/projects/django-cast/src/cast/templates/cast/bootstrap4/gallery.html`
- `/Users/jochen/projects/django-cast/src/cast/templates/cast/bootstrap4/gallery_htmx.html`
- `/Users/jochen/projects/cast-bootstrap5/cast_bootstrap5/templates/cast/bootstrap5/gallery.html`
- `/Users/jochen/projects/cast-bootstrap5/cast_bootstrap5/templates/cast/bootstrap5/gallery_htmx.html`

## Verification Results

### All Features Working:
- ✅ All 5 images display in gallery (including duplicates)
- ✅ Image IDs are sequential (img-0 through img-4)
- ✅ Navigation works through all images (forward and backward)
- ✅ Modal opens correctly
- ✅ Duplicate images are properly accessible
- ✅ HTMX gallery navigation works correctly

### Test Results:
Using Playwright testing confirmed:
1. Navigation from image 0 → 1 → 2 → 3 → 4 works correctly
2. Backward navigation from image 4 → 3 → 2 → 1 → 0 works correctly
3. Duplicate image at position 4 (same as position 2) is properly accessible

## Lessons Learned

1. **Django QuerySet Ordering**: `filter(pk__in=list)` doesn't preserve list order - must manually reconstruct the list
2. **Template-Based Solutions**: Sometimes it's better to calculate values in templates rather than trying to synchronize backend and frontend state
3. **Duplicate Handling**: Using primary keys for element IDs fails with duplicates - position-based IDs are more robust
4. **Minimal Changes**: The simplest fix (template-only for navigation) was more effective than complex Python modifications

## Key Insights

The bug occurred because:
1. Images were assigned `data-prev` and `data-next` attributes in Python based on their processing order
2. Templates assigned element IDs using `forloop.counter0` based on iteration order
3. These two orders didn't match, causing navigation to reference non-existent element IDs

The solution bypasses this synchronization issue entirely by calculating both IDs and navigation attributes in the template using the same `forloop.counter0` variable.
