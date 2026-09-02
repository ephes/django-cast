StreamField Blocks
==================

Django Cast uses Wagtail's StreamField to provide flexible content editing. Posts and Episodes have a ``body`` field with two sections: ``overview`` (summary) and ``detail`` (full content). Both sections support the same built-in content blocks, and projects can append custom blocks with ``CAST_POST_BODY_BLOCKS``.

Overview
--------

The StreamField structure allows authors to create dynamic content layouts by combining different block types. Each block is rendered with its own template and can be customized per theme.

.. code-block:: python

    body = StreamField([
        ("overview", ContentBlock(section="overview")),
        ("detail", ContentBlock(section="detail")),
    ])

Content Sections
----------------

**Overview Section**
  Displayed on index pages and in feeds. Typically contains a summary or introduction.

**Detail Section**
  Additional content shown only on the full post page. Contains the main article body.

Available Blocks
----------------

Headings in Rich Text
~~~~~~~~~~~~~~~~~~~~~

Django Cast no longer provides a standalone ``heading`` StreamField block.
Author headings inside the ``paragraph`` rich-text block instead. Wagtail's
rich text supports ``h2``, ``h3``, and ``h4`` headings, so authors can choose
the appropriate level for the document outline.

Existing stored ``heading`` blocks are converted automatically by the upgrade
migration to ``paragraph`` blocks containing ``<h2>…</h2>`` rich text.

Paragraph Block
~~~~~~~~~~~~~~~

Rich text content with formatting options, including headings.

**Type**: ``paragraph``

**Usage**:

.. code-block:: python

    ("paragraph", blocks.RichTextBlock())

**Features**:

- Headings (``h2``, ``h3``, ``h4``)
- Bold, italic, links
- Lists (ordered/unordered)
- Standard Wagtail rich text features
- No embedded images (use Image block instead)

Code Block
~~~~~~~~~~

Syntax-highlighted code snippets.

**Type**: ``code``

**Structure**:

.. code-block:: python

    class CodeBlock(blocks.StructBlock):
        language = blocks.CharBlock()
        source = blocks.TextBlock()

**Features**:

- Pygments syntax highlighting
- Support for 100+ programming languages
- Automatic language detection
- Falls back to plain text if language unknown

**Example Usage**:

.. code-block:: json

    {
        "type": "code",
        "value": {
            "language": "python",
            "source": "def hello():\n    print('Hello, World!')"
        }
    }

Image Block
~~~~~~~~~~~

Responsive images with automatic optimization.

**Type**: ``image``

**Class**: ``CastImageChooserBlock``

**Features**:

- Automatic responsive image generation
- AVIF and JPEG format support
- Multiple renditions for different screen sizes
- Links to full-size image
- Lazy loading support

**Generated Renditions**:

The system automatically creates renditions based on
``CAST_REGULAR_IMAGE_SLOT_DIMENSIONS``.
Each tuple defines a target layout slot, not a single output file. For every
slot, django-cast generates the appropriate rendition widths for multiple pixel
densities and exposes them via ``srcset``:

.. code-block:: python

    # Default dimensions
    [
        (1110, 740),
    ]

**HTML Output Example**:

.. code-block:: html

    <picture>
        <source type="image/avif" srcset="...">
        <img src="..." srcset="..." sizes="..." alt="..." loading="lazy">
    </picture>

Gallery Block
~~~~~~~~~~~~~

Multiple images with lightbox functionality.

**Type**: ``gallery``

**Structure**:

.. code-block:: python

    class GalleryBlockWithLayout(blocks.StructBlock):
        gallery = GalleryBlock()
        layout = blocks.ChoiceBlock(choices=[
            ("default", "Web Component"),
            ("htmx", "HTMX")
        ])

**Features**:

- Modal lightbox with navigation
- Two layout options:

  - **Web Component**: Client-side modal (default)
  - **HTMX**: Server-side modal rendering

- Responsive thumbnail grid
- Keyboard navigation in modal
- Touch/swipe support

**Gallery Renditions**:

Configured via ``CAST_GALLERY_IMAGE_SLOT_DIMENSIONS``. As with regular images,
these are slot dimensions. django-cast then derives multiple responsive
renditions per slot for use in ``srcset``:

.. code-block:: python

    # Default gallery dimensions
    [
        (1110, 740),  # Modal image
        (120, 80),    # Thumbnail
    ]

Embed Block
~~~~~~~~~~~

External content embedding via oEmbed.

**Type**: ``embed``

**Features**:

- YouTube videos
- Twitter/X posts
- Vimeo videos
- Any oEmbed-compatible service
- Responsive embed containers

**Example Usage**:

.. code-block:: text

    https://www.youtube.com/watch?v=dQw4w9WgXcQ

Video Block
~~~~~~~~~~~

User-uploaded video files.

**Type**: ``video``

**Class**: ``VideoChooserBlock``

**Features**:

- HTML5 video player
- Multiple format support (MP4, WebM, etc.)
- Optional poster images
- Responsive video sizing
- User access control

**HTML Output**:

.. code-block:: html

    <video controls poster="...">
        <source src="..." type="video/mp4">
    </video>

Audio Block
~~~~~~~~~~~

Podcast-ready audio with advanced features.

**Type**: ``audio``

**Class**: ``AudioChooserBlock``

**Features**:

- Podlove Web Player integration
- Multiple format support (MP3, M4A, OGG, OPUS)
- Chapter marks navigation
- Transcript display
- Configurable player themes
- Download options

**Player Features**:

- Playback speed control
- Chapter navigation
- Keyboard shortcuts
- Share functionality
- Embed code generation

Block Templates
---------------

Each block type has a default template that can be overridden:

.. code-block:: text

    templates/
    └── cast/
        ├── blocks/
        │   ├── paragraph.html
        │   └── code.html
        ├── image/
        │   └── image.html
        ├── gallery.html
        ├── gallery_htmx.html
        ├── video/
        │   └── video.html
        └── audio/
            └── audio.html

Theme Override
~~~~~~~~~~~~~~

Templates can be customized per theme:

.. code-block:: text

    templates/
    └── my-theme/
        └── cast/
            └── blocks/
                └── code.html  # Override code block template

Performance Optimization
------------------------

Repository Pattern
~~~~~~~~~~~~~~~~~~

Media blocks use repositories to avoid N+1 queries:

.. code-block:: python

    # Bad: Multiple queries
    for block in post.body:
        if block.block_type == 'image':
            image = Image.objects.get(pk=block.value)

    # Good: Single query via repository
    repository = PostDetailContext(post)
    # All images prefetched

Rendition Prefetching
~~~~~~~~~~~~~~~~~~~~~

Image renditions are prefetched to avoid per-image queries:

.. code-block:: python

    # Automatic prefetching for all images in post
    renditions = RenditionsForPosts.get_renditions(posts)

Context Passing
~~~~~~~~~~~~~~~

The rendering context includes prefetched data:

.. code-block:: python

    context = {
        'self': block_value,
        'image_by_id': repository.image_by_id,
        'video_by_id': repository.video_by_id,
        'audio_by_id': repository.audio_by_id,
        'value': lazy_loaded_value,
    }

Custom Block Development
------------------------

Creating a Custom Block
~~~~~~~~~~~~~~~~~~~~~~~

Example custom quote block:

.. code-block:: python

    from wagtail import blocks

    class QuoteBlock(blocks.StructBlock):
        quote = blocks.TextBlock()
        author = blocks.CharBlock(required=False)

        class Meta:
            template = 'cast/blocks/quote.html'
            icon = 'quote'

Registering Custom Blocks
~~~~~~~~~~~~~~~~~~~~~~~~~

Projects append custom blocks with ``CAST_POST_BODY_BLOCKS``. Do not edit
django-cast's ``ContentBlock`` class directly; that makes migrations and
upgrades harder to keep stable.

The setting maps the ``overview`` and ``detail`` sections to dotted factory
paths. Each factory must return a ``(name, block)`` tuple, where ``name`` is the
stable StreamField block type and ``block`` is a Wagtail ``Block`` instance.

.. code-block:: python

    CAST_POST_BODY_BLOCKS = {
        "overview": [],
        "detail": [
            "myproject.blocks.quote_block",
        ],
    }

.. code-block:: python

    # myproject/blocks.py
    def quote_block():
        return "quote", QuoteBlock()

Configured blocks are appended after django-cast's built-in blocks. The two
sections are independent, so a block registered for ``detail`` is not available
in ``overview`` unless it is also listed there.

Block names are content schema. Keep them stable after content has been saved:
renaming or removing a custom block can make existing StreamField content
uneditable or unrenderable until it is migrated or the block is restored.

Custom Template
~~~~~~~~~~~~~~~

``templates/cast/blocks/quote.html``:

.. code-block:: html

    <blockquote class="cast-quote">
        <p>{{ value.quote }}</p>
        {% if value.author %}
            <cite>— {{ value.author }}</cite>
        {% endif %}
    </blockquote>

Custom block templates are rendered in post detail pages, index/list previews,
feeds, API HTML fields, and Wagtail previews through the normal
``{% include_block %}`` path. If a block needs different output in feeds, check
the ``render_for_feed`` context value and avoid markup that is unsafe or
unhelpful in RSS/Atom descriptions.

Media Sync Limits
~~~~~~~~~~~~~~~~~

The first custom-block extension point does not add media extraction hooks.
``cast.post_media.prepare_post_media()`` and the compatibility
``Post.sync_media_ids()`` adapter sync only django-cast's built-in ``image``,
``gallery``, ``video``, and ``audio`` blocks to the post media relationships.
Custom blocks can render chooser values normally, but their media references are
not added to ``Post.images``, ``Post.galleries``, ``Post.videos``, or
``Post.audios`` automatically.

Media Selection
---------------

When editing content, media blocks use Wagtail's chooser interface:

1. **Images**: Filtered by user ownership
2. **Videos**: User's uploaded videos only
3. **Audio**: User's audio files only
4. **Galleries**: Reusable gallery collections

This ensures users only see and can select their own media files.

Best Practices
--------------

Content Structure
~~~~~~~~~~~~~~~~~

1. Use **overview** for summaries that appear in feeds
2. Place main content in **detail** section
3. Use rich-text headings to organize long content
4. Prefer native media blocks over embeds when possible

Performance
~~~~~~~~~~~

1. Avoid too many high-resolution images in one post
2. Use galleries for multiple related images
3. Let the system handle image optimization
4. Don't embed raw HTML with images

Accessibility
~~~~~~~~~~~~~

1. Always provide alt text for images
2. Use semantic headings properly
3. Include transcripts for audio content
4. Ensure embedded content is accessible

Migration and Import
--------------------

When importing content:

.. code-block:: python

    from wagtail.blocks import StreamValue

    post.body = StreamValue(
        post.body.stream_block,
        [
            ("overview", {
                "paragraph": "<h2>Welcome</h2><p>Introduction text</p>"
            }),
            ("detail", {
                "paragraph": "<p>Main content</p>",
                "image": image.pk,
                "code": {
                    "language": "python",
                    "source": "print('Hello')"
                }
            })
        ]
    )

API Representation
------------------

StreamField content is available via the API as structured JSON:

.. code-block:: json

    {
        "body": [
            {
                "type": "overview",
                "value": [
                    {
                        "type": "paragraph",
                        "value": "<h2>My Post Title</h2><p>Summary text...</p>"
                    }
                ]
            }
        ]
    }

This enables headless CMS usage and content portability.
