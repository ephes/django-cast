StreamField Blocks
==================

Django Cast uses Wagtail's StreamField to provide flexible content editing. Posts and Episodes have a ``body`` field with two sections: ``overview`` (summary) and ``detail`` (full content). Both sections support the same rich set of content blocks.

Overview
--------

The StreamField structure allows authors to create dynamic content layouts by combining different block types. Each block is rendered with its own template and can be customized per theme.

.. code-block:: python

    body = StreamField([
        ("overview", ContentBlock()),
        ("detail", ContentBlock()),
    ])

Content Sections
----------------

**Overview Section**
  Displayed on index pages and in feeds. Typically contains a summary or introduction.

**Detail Section**
  Additional content shown only on the full post page. Contains the main article body.

Available Blocks
----------------

Heading Block
~~~~~~~~~~~~~

Simple section headings for organizing content.

**Type**: ``heading``

**Usage**:

.. code-block:: python

    ("heading", blocks.CharBlock(classname="full title"))

**Features**:

- Plain text headings
- Full-width display
- Useful for section breaks

Paragraph Block
~~~~~~~~~~~~~~~

Rich text content with formatting options.

**Type**: ``paragraph``

**Usage**:

.. code-block:: python

    ("paragraph", blocks.RichTextBlock())

**Features**:

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

The system automatically creates renditions based on ``CAST_IMAGE_SLOT_DIMENSIONS`` setting:

.. code-block:: python

    # Default dimensions
    {
        "150": "150",
        "300": "300",
        "450": "450",
        "600": "600",
        "750": "750",
        "900": "900",
        "1050": "1050",
        "1200": "1200",
        "1350": "1350",
        "1500": "1500",
    }

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

Configured via ``CAST_GALLERY_IMAGE_SLOT_DIMENSIONS``:

.. code-block:: python

    # Default gallery dimensions
    {
        "150": "150x150",  # Thumbnails
        "300": "300x300",
        "600": "600x600",
    }

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
        │   ├── heading.html
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
    repository = PostDetailRepository(post)
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

Adding to ContentBlock
~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    class ContentBlock(blocks.StreamBlock):
        heading = blocks.CharBlock(classname="full title")
        paragraph = blocks.RichTextBlock()
        quote = QuoteBlock()  # Add custom block
        # ... other blocks

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
3. Use headings to organize long content
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
                "heading": "Welcome",
                "paragraph": "<p>Introduction text</p>"
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
                        "type": "heading",
                        "value": "My Post Title"
                    },
                    {
                        "type": "paragraph",
                        "value": "<p>Summary text...</p>"
                    }
                ]
            }
        ]
    }

This enables headless CMS usage and content portability.
