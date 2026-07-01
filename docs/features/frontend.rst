.. _frontend:

********
Frontend
********

Django Cast ships a small JavaScript layer that powers interactive features:
an audio player, an image gallery modal, and AJAX-based comments. Assets are
built with `Vite <https://vite.dev/>`_ and integrated into Django templates
via `django-vite <https://github.com/MrBin99/django-vite>`_. Page-level
interactivity (pagination, gallery navigation) uses
`HTMX <https://htmx.org/>`_.

.. _frontend_architecture:

Architecture Overview
=====================

The JavaScript source lives in ``javascript/src/`` and is organized into three
independent entry points:

``src/gallery/image-gallery-bs4.ts``
    A custom element (``<image-gallery-bs4>``) that provides Bootstrap-modal
    gallery navigation with keyboard support. Used by the **bootstrap4** theme.

``src/audio/podlove-player.ts``
    A custom element (``<podlove-player>``) that lazy-loads the
    `Podlove Web Player 5 <https://podlove.org/podlove-web-player/>`_ for
    audio playback. Used by all themes.

``src/comments/ajaxcomments.ts``
    An IIFE script that intercepts comment form submissions and posts them via
    ``fetch``, with preview support, threaded replies, and error display. Loaded
    on post detail pages when comments are enabled.

The **plain** theme does not use the ``<image-gallery-bs4>`` web component for
galleries. Instead, it renders a pure HTMX-driven gallery modal (see
:ref:`htmx_gallery_modal`).

.. _frontend_pagination:

Pagination
==========

The blog index page comes with pagination support. You can set the
number of posts per page using the ``POST_LIST_PAGINATION`` setting.

If there are more than 3 pages, there will be a "..." in the pagination.
If there are more than 10 pages, there will be two "..." in the pagination.

.. _frontend_web_components:

Web Components
==============

.. _podlove_player_component:

``<podlove-player>``
--------------------

A custom HTML element that wraps the Podlove Web Player 5. It handles lazy
loading, dark mode detection, and an optional click-to-load facade.

Template Usage
^^^^^^^^^^^^^^

The element is rendered by the shared template
``cast/audio/audio.html``:

.. code-block:: html+django

   <podlove-player
     id="audio_{{ value.pk }}"
     data-variant="xl"
     data-url="{% url 'cast:api:audio_podlove_detail' pk=value.pk post_id=page.pk %}"
     data-embed="{% static 'cast/js/web-player/embed.5.js' %}"
     data-config="{% url 'cast:api:player_config' %}"
     {% if podlove_load_mode == "facade" %}
       data-load-mode="facade"
     {% elif podlove_load_mode == "click" %}
       data-load-mode="click"
     {% endif %}
   >
     {% if podlove_load_mode == "facade" %}
       <!-- server-rendered facade: cover art, title, play button -->
     {% endif %}
   </podlove-player>

Data Attributes
^^^^^^^^^^^^^^^

``data-url`` (required)
    The API endpoint returning the Podlove episode JSON for this audio file.

``data-config``
    URL for the player configuration (theme colors, fonts). Defaults to
    ``/api/audios/player_config/``. You can customize the theme per template
    base directory using the ``CAST_PODLOVE_PLAYER_THEMES`` setting.

``data-embed``
    URL of the Podlove Web Player embed script. This is required; missing
    values fail closed and do not load a third-party fallback script. Django
    Cast ships a local copy at ``cast/js/web-player/embed.5.js``.

``data-template``
    Optional Podlove template name passed through to the player initialization.

``data-load-mode``
    Controls how the player is initialized. Two values are supported:

    - ``"click"`` — displays a "Load player" button; the player loads only
      when clicked. Used on **list pages** to avoid loading multiple heavy
      player instances at once.
    - ``"facade"`` — the server renders a static preview (cover art, title,
      play button) inside the element. The player auto-initializes via
      ``IntersectionObserver`` and is injected into the existing container.
      Used on **post detail pages**.

    If omitted, the player auto-initializes with a plain placeholder.

Initialization Behavior
^^^^^^^^^^^^^^^^^^^^^^^

**Auto-init** (no ``data-load-mode``, or ``data-load-mode="facade"``):

1. The element waits for the page ``load`` event.
2. A shared ``IntersectionObserver`` (with a 200 px root margin) watches the
   element.
3. When the element enters the viewport, initialization is scheduled via
   ``requestIdleCallback``.
4. The embed script is loaded (once, shared across all players on the page),
   then the Podlove player is created inside the element.

In facade mode, the server-rendered preview (cover art, title, decorative play
button and progress bar) is visible while the player loads. The JS skips
creating its own placeholder when it detects a ``.podlove-player-container``
already present inside the element. The player ``<div>`` is appended into
the existing container; the facade markup remains in the DOM unless hidden
by CSS or overwritten by the player iframe.

**Click-to-load** (``data-load-mode="click"``):

1. A placeholder container with a "Load player" button is rendered immediately.
2. Clicking the button bypasses the page-load wait and IntersectionObserver
   steps — it directly schedules initialization via ``requestIdleCallback``,
   then loads the embed script and creates the player.
3. On failure, an error message is shown and the button text changes to
   "Try again".

Dark Mode
^^^^^^^^^

The player automatically detects dark mode by checking (in order):

1. ``data-bs-theme`` on ``<html>``
2. ``data-theme`` on ``<html>``
3. ``data-bs-theme`` on ``<body>``
4. ``data-theme`` on ``<body>``
5. ``prefers-color-scheme: dark`` media query

When dark mode is detected, ``?color_scheme=dark`` is appended to the config
URL so the server can return appropriate theme tokens.

.. _image_gallery_component:

``<image-gallery-bs4>``
-----------------------

A custom HTML element that manages Bootstrap-modal image galleries with
keyboard navigation. Used by the **bootstrap4** theme.

Template Usage
^^^^^^^^^^^^^^

The element wraps gallery thumbnails and an associated Bootstrap modal. Each
thumbnail is an ``<a>`` tag with a nested ``<picture>`` and ``<img>``. The
``<img>`` carries data attributes that define the modal-size image sources and
navigation links.

.. code-block:: html+django

   <image-gallery-bs4 id="gallery-{{ block.id }}">
     <div class="cast-gallery-container">
       <a class="cast-gallery-modal"
          data-toggle="modal" data-target="#galleryModal-{{ block.id }}"
          data-full="{{ image.modal.src.jpeg }}">
         <picture>
           <source srcset="{{ image.thumbnail.srcset.avif }}" type="image/avif"
                   sizes="{{ image.thumbnail.sizes }}"
                   data-modal-src="{{ image.modal.src.avif }}"
                   data-modal-srcset="{{ image.modal.srcset.avif }}"
                   data-modal-sizes="{{ image.modal.sizes }}">
           <img id="img-{{ block.id }}-0"
                class="cast-gallery-thumbnail"
                alt="{{ image.default_alt_text }}"
                src="{{ image.thumbnail.src.jpeg }}"
                srcset="{{ image.thumbnail.srcset.jpeg }}"
                sizes="{{ image.thumbnail.sizes }}"
                width="{{ image.thumbnail.width }}"
                height="{{ image.thumbnail.height }}"
                data-modal-src="{{ image.modal.src.jpeg }}"
                data-modal-srcset="{{ image.modal.srcset.jpeg }}"
                data-modal-sizes="{{ image.modal.sizes }}"
                data-modal-width="{{ image.modal.width }}"
                data-modal-height="{{ image.modal.height }}"
                data-prev="false"
                data-next="img-{{ block.id }}-1"
                loading="lazy" />
         </picture>
       </a>
       <!-- more thumbnails -->

       <div class="modal fade" id="galleryModal-{{ block.id }}"
            tabindex="-1" role="dialog" aria-hidden="true">
         <!-- Bootstrap modal with placeholder image -->
       </div>
     </div>
   </image-gallery-bs4>

Data Attributes
^^^^^^^^^^^^^^^

On ``<source>`` (AVIF variant for the modal):

``data-modal-src``, ``data-modal-srcset``, ``data-modal-sizes``
    The AVIF image sources to use in the modal ``<source>`` element.

On ``<img>`` (JPEG fallback and navigation):

``data-fullsrc``
    The JPEG URL for the modal ``<img>`` ``src``. Note: the current template
    sets ``data-modal-src`` on ``<img>`` instead; the JS reads ``data-fullsrc``,
    so the modal ``src`` falls back to the placeholder while ``srcset`` (from
    ``data-modal-srcset``) provides the actual image.

``data-modal-srcset``, ``data-modal-sizes``
    The JPEG srcset and sizes for the modal ``<img>``.

``data-modal-width``, ``data-modal-height``
    Used to set the ``aspect-ratio`` CSS property on the modal image, preventing
    layout shift while the full-size image loads.

``data-prev``, ``data-next``
    The ``id`` of the previous/next thumbnail ``<img>`` element, or ``"false"``
    if at the boundary. These drive the Prev/Next navigation.

``data-full``
    On the parent ``<a>`` tag. The original full-resolution image URL, used as
    the ``href`` on the modal image link.

Keyboard Navigation
^^^^^^^^^^^^^^^^^^^

When the modal is open:

- **ArrowLeft** navigates to the previous image
- **ArrowRight** navigates to the next image
- **Escape** closes the modal

Loading States
^^^^^^^^^^^^^^

When navigating between images, a spinner overlay is shown while the new
full-size image loads. A sequence counter ensures that only the most recent
navigation request updates the display, preventing race conditions with
slow-loading images.

Bootstrap Compatibility
^^^^^^^^^^^^^^^^^^^^^^^

The component supports three Bootstrap modal APIs, tried in order:

1. **jQuery plugin** (``$(modal).modal("show")``) — legacy Bootstrap 4 with
   jQuery
2. **Bootstrap JS global** (``new bootstrap.Modal(el)``) — Bootstrap 4.6.2
   UMD build
3. **CSS-only fallback** — manually toggles ``show`` class and ``display``
   style when no Bootstrap JS is available

.. _ajax_comments_component:

AJAX Comments
-------------

The comments script (``ajaxcomments.ts``) provides client-side comment posting
without full page reloads. It is built as a standalone IIFE and loaded via a
``<script>`` tag on post detail pages when comments are enabled.

How It Works
^^^^^^^^^^^^

1. On ``DOMContentLoaded``, the script finds all ``form.js-comments-form``
   elements and wraps them in position-tracking containers.
2. Form submissions are intercepted via a delegated ``submit`` event listener
   on ``document``.
3. The form data is sent via ``fetch`` with ``X-Requested-With: XMLHttpRequest``
   to the form's ``data-ajax-action`` or ``action`` URL.
4. On success, the new comment HTML is inserted into the DOM and the page
   scrolls to it.
5. On error, field-level error messages are displayed using Bootstrap
   ``has-error`` / ``error`` classes.

Features
^^^^^^^^

- **Preview**: Clicking a button with ``name="preview"`` shows a preview of the
  comment without posting it.
- **Threaded replies**: Clicking a ``.comment-reply-link`` moves the form under
  the target comment and sets the ``parent`` field.
- **Cancel reply**: Clicking ``.comment-cancel-reply-link`` resets the form
  back to its original position.
- **Moderation message**: If the comment requires moderation, a temporary
  message is shown for 4 seconds.
- **Error event**: On network failure, a ``cast:comments:error`` custom event
  is dispatched on ``window``. If no listener calls ``preventDefault()``, a
  fallback ``alert()`` is shown.

Template Integration
^^^^^^^^^^^^^^^^^^^^

Comments are loaded conditionally in post templates:

.. code-block:: html+django

   {% if comments_are_enabled %}
     <link rel="stylesheet" href="{% static 'fluent_comments/css/ajaxcomments.css' %}" />
     <script defer src="{% static 'fluent_comments/js/ajaxcomments.js' %}"></script>
   {% endif %}

The script works on HTMX-navigated pages because it re-wraps forms on each
submit, reply, and cancel interaction (not via HTMX lifecycle events). This
means forms inserted after the initial page load are handled correctly.

.. _frontend_vite_build:

Vite Build Setup
================

JavaScript assets are built with Vite. There are two separate build
configurations in the ``javascript/`` directory.

Main Build (Gallery + Audio Players)
------------------------------------

Configuration file: ``javascript/vite.config.ts``

.. code-block:: text

   Entry points:
     src/gallery/image-gallery-bs4.ts  ->  main-<hash>.js
     src/audio/podlove-player.ts       ->  podlovePlayer-<hash>.js
     src/audio/custom-player.ts        ->  customPlayer-<hash>.js (+ CSS sidecar)

   Output:  javascript/dist/
   Format:  ES modules (default Vite/Rolldown output)
   Target:  ES2015

``npm run build`` writes to ``javascript/dist/``. The ``just js-build-vite``
command handles the full pipeline: it runs the Vite build, moves the manifest
file from the ``.vite/`` subdirectory, and copies the output to
``src/cast/static/cast/vite/`` where Django's static files system can serve it.

Templates include these assets using ``django-vite`` template tags:

.. code-block:: html+django

   {% load django_vite %}
   {% vite_hmr_client app="cast" %}
   {% vite_asset 'src/gallery/image-gallery-bs4.ts' app="cast" %}
   {% vite_asset 'src/audio/podlove-player.ts' app="cast" %}
   {% vite_asset 'src/audio/custom-player.ts' app="cast" %}

In development (``DJANGO_VITE["cast"]["dev_mode"] = True``), the template tags
point to the Vite dev server on port 5173. In production, they resolve asset
paths from the manifest file.

Comments Build
--------------

Configuration file: ``javascript/vite.comments.config.ts``

.. code-block:: text

   Entry point:
     src/comments/ajaxcomments.ts  →  ajaxcomments.js

   Output:  src/cast/static/fluent_comments/js/
   Format:  IIFE (immediately invoked function expression)
   Target:  ES2015

The comments build outputs directly into the static files directory. It uses
IIFE format (not ES modules) so it works as a simple ``<script>`` tag without
module loading. Minification is disabled so the output remains readable for
debugging.

Build Commands
--------------

Run from the ``javascript/`` directory:

.. code-block:: bash

   npm run build           # Main build (gallery + player)
   npm run build:comments  # Comments build
   npm run build:all       # Both builds
   npm run dev             # Vite dev server for HMR

Or from the project root using the justfile:

.. code-block:: bash

   just js-build-vite      # Main build + copy to static
   just js-build-comments  # Comments build
   just js-build-all       # Both builds
   just js-bundles         # Show shipped bundle sizes

.. note::

   ``just js-build-vite`` handles the full pipeline: builds with Vite, moves
   the manifest file, and copies the output to
   ``src/cast/static/cast/vite/``.

Use ``just js-bundles`` to inspect the JavaScript and CSS bundles currently
shipped from ``src/cast/static/cast/vite/`` plus the built comments script. The
report shows raw and gzip KiB per entry (with a bar comparing gzip sizes) and
totals for the built JavaScript, rendered as colored tables. Add
``--include-static-js`` to also list vendored/static JavaScript files such as
``htmx.min.js`` and the Podlove embed, or ``--plain`` for uncolored aligned-text
output (also used automatically when ``rich`` is unavailable).

Testing
-------

JavaScript tests use `Vitest <https://vitest.dev/>`_ with a jsdom environment:

.. code-block:: bash

   cd javascript
   npm test             # Run tests once
   npm run test:watch   # Watch mode
   npm run coverage     # With coverage report

.. _frontend_htmx:

HTMX Integration
================

Django Cast uses HTMX for two main features: gallery modal navigation and
pagination with view transitions.

CSRF Token Handling
-------------------

The bootstrap4 base template sets a global HTMX CSRF header on the
``<body>`` tag:

.. code-block:: html+django

   <body data-hx-headers='{"X-CSRFToken": "{{ csrf_token }}"}'>

This ensures all HTMX requests automatically include the CSRF token without
additional configuration.

.. note::

   The **plain** theme does not set this header because its HTMX interactions
   (gallery modals, pagination) only use GET requests. If you add HTMX-driven
   POST requests to a plain-theme template, add ``data-hx-headers`` to your
   base template or individual elements.

.. _htmx_gallery_modal:

Gallery Modal Navigation
------------------------

The **plain** theme (and the bootstrap4 theme as a secondary approach) uses
HTMX to load gallery modal content from the server. When a thumbnail is
clicked, HTMX fetches the modal content from the ``gallery-modal`` view.

Thumbnail links use these HTMX attributes:

.. code-block:: html+django

   <a data-hx-get="{% url 'cast:gallery-modal' template_base_dir=... %}?image_pks=...&current_image_index=0&block_id=..."
      data-hx-trigger="click"
      data-hx-target="#imageGalleryModal-BLOCK_ID"
      data-hx-swap="innerHTML">

The modal container is an empty ``<div>`` that receives the server-rendered
content:

.. code-block:: html

   <div id="imageGalleryModal-BLOCK_ID"
        class="cast-gallery-modal"
        data-hx-on-click="this.innerHTML = ''"
        data-hx-on-htmx-afterSwap="this.focus()"
        data-hx-on-keyup="if (event.key === 'Escape') this.innerHTML = ''">
   </div>

The server-rendered modal content includes Prev/Next links that also use HTMX:

.. code-block:: html

   <a data-hx-get="...?current_image_index=PREV_INDEX..."
      data-hx-trigger="click, keyup[key=='ArrowLeft'] from:#imageGalleryModal-BLOCK_ID"
      data-hx-target="#imageGalleryModal-BLOCK_ID"
      data-hx-swap="innerHTML">
     Prev
   </a>

This allows keyboard navigation (ArrowLeft/ArrowRight) within the modal,
handled entirely by HTMX trigger filters. Pressing Escape clears the modal
content via the ``data-hx-on-keyup`` handler on the container.

The backing view (``cast.views.gallery.gallery_modal``) receives the image
primary keys, current index, and block ID as query parameters. It prefetches
the current, previous, and next images with their renditions and returns
the rendered modal template.

Pagination with View Transitions
---------------------------------

Pagination links use HTMX to swap page content without a full page reload.
The ``data-hx-swap`` attribute includes ``transition:true`` to enable CSS
view transitions:

.. code-block:: html

   <a data-hx-get="?page=2"
      data-hx-target="#paging-area"
      data-hx-swap="innerHTML show:window:top transition:true"
      data-hx-sync="#paging-area:replace"
      data-hx-push-url="true"
      href="?page=2">

Key attributes:

``data-hx-target="#paging-area"``
    Swaps the content of the ``#paging-area`` container, which wraps the post
    list and pagination controls.

``data-hx-swap="innerHTML show:window:top transition:true"``
    Replaces the inner HTML, scrolls to the top of the window, and uses CSS
    view transitions for a smooth visual effect.

``data-hx-sync="#paging-area:replace"``
    If a new pagination request arrives while one is in-flight, the old request
    is cancelled.

``data-hx-push-url="true"``
    Updates the browser URL so the Back button works as expected.

A small companion script (``paging-view-transition-fix.js``) listens for
``htmx:beforeTransition`` events targeting the ``#paging-area`` element and
scrolls to the top of the page before the view transition snapshot is taken,
ensuring a clean transition. Other HTMX transitions are not affected.
