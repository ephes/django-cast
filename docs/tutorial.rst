########
Tutorial
########

This tutorial will guide you through creating your first blog and podcast with Django Cast.

*******************
Your First Blog
*******************

After completing the :doc:`installation`, let's create your first blog.

Creating a Blog
===============

1. **Access the Wagtail Admin**

   Navigate to http://localhost:8000/cms/ and log in with your credentials.

2. **Navigate to Pages**

   Click on "Pages" in the sidebar. You'll see the page tree with your site's root.

3. **Add a Blog**

   - Click "Add child page" next to the root page
   - Select "Blog" from the page type options
   - Fill in the required fields:

     - **Title**: Your blog's name (e.g., "My Tech Blog")
     - **Slug**: URL-friendly version (e.g., "tech-blog")
     - **Author**: Your name
     - **Email**: Contact email
     - **Description**: Brief description of your blog

4. **Configure Blog Settings**

   - **Comments enabled**: Configure via Django Admin (http://localhost:8000/admin/)
   - **Template base dir**: Choose from pre-installed themes ("bootstrap4" or "plain")

5. **Publish**

   - Click "Publish" to make your blog live
   - Your blog is now accessible at http://localhost:8000/tech-blog/

Creating Your First Post
========================

1. **Navigate to Your Blog**

   In the page tree, find your blog and click on it.

2. **Add a Post**

   - Click "Add child page"
   - Select "Post" from the page type options

3. **Fill in Post Details**

   - **Title**: Your post title
   - **Slug**: URL slug (auto-generated from title)
   - **Categories**: Select or create categories
   - **Tags**: Add relevant tags

4. **Add Content**

   The body field has two sections:

   **Overview Section**
     Brief summary that appears on the blog index page

   **Detail Section**
     Full article content that appears on the post page

   For each section, you can add:

   - **Heading**: Section headers
   - **Paragraph**: Rich text content
   - **Image**: Single responsive image
   - **Gallery**: Multiple images with lightbox
   - **Code**: Syntax-highlighted code blocks
   - **Video**: Embedded video files
   - **Audio**: Embedded audio with player
   - **Embed**: External content (YouTube, etc.)

5. **Add Media**

   To add an image:

   - Click the "+" button in a content section
   - Choose "Image"
   - Upload or select an existing image
   - Add alt text for accessibility

6. **Preview and Publish**

   - Use "Preview" to see how your post looks
   - Click "Publish" when ready
   - Your post is now live!

***********************
Your First Podcast
***********************

Django Cast makes it easy to create a podcast with full iTunes support.

Creating a Podcast
==================

1. **Add a Podcast Page**

   - From the root page, click "Add child page"
   - Select "Podcast" from page types

2. **Configure Podcast Settings**

   Basic Information:

   - **Title**: Your podcast name
   - **Slug**: URL slug for the podcast
   - **Author**: Podcast host name
   - **Email**: Contact email
   - **Description**: Podcast description

   iTunes Settings:

   - **iTunes Artwork**: Upload 3000x3000px image

3. **Publish Your Podcast**

   Click "Publish" to create your podcast page.

Creating Your First Episode
===========================

1. **Navigate to Your Podcast**

   Find your podcast in the page tree.

2. **Add an Episode**

   - Click "Add child page"
   - Select "Episode" from page types

3. **Episode Details**

   - **Title**: Episode title
   - **Podcast Audio**: Upload your audio file (required)
   - **Keywords**: Episode-specific keywords
   - **Explicit**: Episode content rating:
     - **Yes**: Content is suitable for the age group it's rated for
     - **No**: Content does not contain anything explicit and is safe for general audiences
     - **Explicit**: Contains adult content or strong language, not recommended for younger audiences
   - **Block**: Check to prevent iTunes distribution

4. **Add Show Notes**

   Use the body field to add:

   - Episode description (overview)
   - Detailed show notes (detail)
   - Links and resources
   - Embedded images or code

5. **Upload Audio**

   - Click "Choose audio" in Podcast Audio field
   - Upload your audio file (MP3, M4A, OGG, or OPUS)
   - The system will automatically extract duration
   - Each audio object can have multiple files in different formats

6. **Add Chapters (Optional)**

   After publishing, you can add chapter marks:

   - Go to Settings → Audio in admin
   - Find your audio file
   - Add chapter marks with timestamps

7. **Publish Episode**

   - Review all settings
   - Click "Publish"
   - Episode appears on podcast page and in RSS feed

********************
RSS Feed Setup
********************

Your podcast RSS feeds are automatically generated for each audio format:

- **MP3 Feed**: ``/feed/podcast/mp3/rss.xml``
- **M4A Feed**: ``/feed/podcast/m4a/rss.xml``
- **OGG Feed**: ``/feed/podcast/oga/rss.xml``
- **OPUS Feed**: ``/feed/podcast/opus/rss.xml``

Each feed contains episodes with audio files in the corresponding format. Submit your preferred feed URL to podcast directories like Apple Podcasts, Spotify, etc.

********************
Working with Media
********************

Images
======

- **Supported formats**: JPEG, PNG, AVIF, WebP
- **Automatic optimization**: Responsive images using picture element
- **Organization**: Create collections for better management

Galleries
=========

1. Click "+" and select "Gallery"
2. Select multiple images
3. Choose layout:

   - **Default**: Web component with client-side lightbox
   - **HTMX**: Server-side rendered lightbox

Audio
=====

- **Formats**: Upload in any format, provide multiple for compatibility
- **Player**: Podlove Web Player with chapters and speed control
- **Transcripts**: Add VTT or JSON transcripts for accessibility

Video
=====

- **Upload**: Browser-compatible formats (MP4, WebM)
- **No conversion**: Upload videos in formats browsers can play
- **Embedding**: Use video block in content

*****************
Tips and Tricks
*****************

Content Organization
====================

- **Categories**: Use for major topic areas
- **Tags**: Use for specific topics
- **Series**: Create related post series

Theme Customization
===================

- Choose from pre-installed themes ("bootstrap4", "plain")
- Install new themes via PyPI
- Select theme in blog's "Template base dir" setting

*************
Next Steps
*************

- Explore :doc:`content/streamfield` for advanced content
- Learn about :doc:`features/themes` for customization
- Set up :doc:`features/comments` for engagement
- Configure :doc:`features/social-media` integration
- Deploy to production (see :doc:`operations/deployment`)
