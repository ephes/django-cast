# Django Cast Documentation Inventory

## Directory Structure
- **Main docs directory**: `/docs/`
- **No separate features/ directory** - feature files are in the main docs directory
- **Howto directory**: `/docs/howto/` with 3 files

## Files in features.rst toctree (17 files)
1. **responsive-images.rst** (41 lines) - Responsive image handling with srcset/sizes
2. **frontend.rst** (12 lines) - Frontend features
3. **django-admin.rst** (11 lines) - Admin interface customizations
4. **social-media.rst** (16 lines) - Social media integration
5. **comments.rst** (35 lines) - Comment system features
6. **blog.rst** (68 lines) - Blog functionality
7. **post.rst** (86 lines) - Post/article features
8. **podcast.rst** (14 lines) - Podcast-specific features
9. **episode.rst** (48 lines) - Podcast episode features
10. **tags.rst** (32 lines) - Tagging system
11. **image.rst** (10 lines) - Image handling
12. **gallery.rst** (10 lines) - Image gallery features
13. **video.rst** (13 lines) - Video support
14. **audio.rst** (35 lines) - Audio file handling
15. **transcript.rst** (22 lines) - Audio/video transcripts
16. **themes.rst** (146 lines) - Theming system
17. **management-commands.rst** (20 lines) - Django management commands

## Files NOT in features.rst (10 files)
1. **api.rst** (331 lines) - REST API documentation
2. **architecture.rst** (247 lines) - System architecture overview
3. **backup.rst** (40 lines) - Backup/restore procedures
4. **context-processors.rst** (47 lines) - Django context processors
5. **development.rst** (391 lines) - Development setup and workflow
6. **integrate.rst** (228 lines) - Integration guide for existing projects
7. **media.rst** (499 lines) - Comprehensive media handling documentation
8. **models.rst** (557 lines) - Django model reference
9. **settings.rst** (181 lines) - Configuration settings reference
10. **streamfield.rst** (479 lines) - StreamField blocks documentation

## Howto Directory Files (3 files)
1. **howto/index.rst** (109 lines) - Contains substantial content about database migrations
2. **howto/first-cast.rst** (6 lines) - Placeholder file
3. **howto/integrate-cast.rst** (6 lines) - Placeholder file

## Key Observations

### Content Overlap
- **media.rst** (499 lines) appears to be a comprehensive overview that covers content from:
  - image.rst (10 lines)
  - gallery.rst (10 lines)
  - video.rst (13 lines)
  - audio.rst (35 lines)
- **integrate.rst** and **howto/integrate-cast.rst** seem to cover similar topics

### Missing from features.rst but Important
- **api.rst** - Substantial API documentation
- **streamfield.rst** - Core content editing feature
- **media.rst** - Comprehensive media guide
- **models.rst** - Complete model reference
- **settings.rst** - Configuration reference

### Cross-References Found
- comments.rst → settings.rst (`:ref:`cast_comments_enabled`)
- development.rst → contributing.rst, release.rst
- episode.rst → podcast.rst, post.rst, blog.rst
- gallery.rst → responsive-images.rst
- image.rst → responsive-images.rst
- integrate.rst → quickstart.rst
- podcast.rst → blog.rst
- post.rst → blog.rst, image.rst, gallery.rst, video.rst, audio.rst
- quickstart.rst → integrate.rst
- responsive-images.rst → settings.rst
- themes.rst → context-processors.rst

### File Size Categories
**Large files (>200 lines):**
- models.rst (557 lines)
- media.rst (499 lines)
- streamfield.rst (479 lines)
- development.rst (391 lines)
- api.rst (331 lines)
- architecture.rst (247 lines)
- integrate.rst (228 lines)

**Medium files (50-200 lines):**
- settings.rst (181 lines)
- themes.rst (146 lines)
- howto/index.rst (109 lines)
- quickstart.rst (107 lines)
- post.rst (86 lines)
- blog.rst (68 lines)

**Small files (<50 lines):**
- Most feature documentation files
- Placeholder howto files

### Recommendations for Restructuring
1. **Create actual features/ directory** with subcategories
2. **Consolidate overlapping content** (e.g., individual media files into media.rst)
3. **Move substantial content from howto/index.rst** to appropriate guides
4. **Add missing important files to features.rst** (api, streamfield, models, settings)
5. **Create proper howto guides** to replace placeholder files
