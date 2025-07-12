# Django Cast Documentation Tasks

## Overview
This file tracks the documentation improvement plan for Django Cast. The goal is to address major documentation gaps identified through analysis of the codebase vs existing docs.

## Current Documentation Gaps
- No architectural overview
- Missing REST API documentation
- Incomplete model documentation (only 2 of 15+ models documented)
- No StreamField blocks documentation
- Missing advanced features (spam filtering, repository pattern, media handling)
- No performance optimization guide
- Missing frontend/JavaScript documentation

## Implementation Plan

### Phase 1: Foundation (High Priority)
- [ ] Create ARCHITECTURE.rst with high-level overview
  - Page hierarchy and inheritance model
  - Repository pattern explanation
  - Performance architecture
  - Media handling pipeline
  - Frontend/backend integration
- [ ] Create api.rst documenting REST API and Wagtail API
  - Endpoint documentation
  - Authentication and permissions
  - Example requests/responses
- [ ] Enhance models.rst to document all 15+ models
  - Complete model reference
  - Model relationships
  - Custom managers and methods

### Phase 2: Core Features (Medium Priority)
- [ ] Create streamfield.rst documenting all block types
  - Available blocks (CodeBlock, ImageChooserBlock, etc.)
  - Creating custom blocks
  - Overview vs Detail sections
- [ ] Create media.rst for image/audio/video handling
  - Renditions and responsive images
  - Audio/video processing
  - Storage backends
- [ ] Update settings.rst with missing settings
  - CAST_GALLERY_IMAGE_SLOT_DIMENSIONS
  - Repository configuration options
  - All other undocumented settings

### Phase 3: Developer Experience
- [ ] Enhance development.rst
  - Add testing documentation
  - JavaScript development workflow
  - Build system details (uv_build)
- [ ] Create customization.rst
  - Template customization
  - Creating custom themes
  - Overriding default behavior
- [ ] Create performance.rst
  - Database query optimization
  - Caching strategies
  - Bulk operations

### Phase 4: Operations
- [ ] Create deployment.rst
  - Production deployment checklist
  - Environment variables
  - Security best practices
- [ ] Document management commands
  - media_backup, media_restore
  - sync_renditions
  - recalc_video_posters
- [ ] Add troubleshooting guides

### Phase 5: Final Updates
- [ ] Update index.rst table of contents
- [ ] Cross-reference all documentation
- [ ] Add code examples throughout
- [ ] Review and polish all docs

## Progress Tracking
_Updated: 2025-07-11_

### Completed
- [x] Create ARCHITECTURE.rst with high-level overview
- [x] Update index.rst table of contents (added Architecture section)
- [x] Create api.rst documenting REST API and Wagtail API
- [x] Enhance models.rst to document all 15+ models
- [x] Create streamfield.rst documenting all block types
- [x] Create media.rst for image/audio/video handling

### In Progress
- Documentation Restructuring (see plan below)

### Notes
- Starting with ARCHITECTURE.rst provides the best foundation
- Each completed task should be marked with [x] and moved to Completed section

## Documentation Restructuring Plan

### Goal
Reorganize documentation for better discoverability and logical flow while preserving ALL existing content.

### Principles
1. **NO CONTENT DELETION** - All existing documentation must be preserved
2. **Merge related content** - Combine small related files into coherent sections
3. **Improve navigation** - Clear progression from beginner to advanced
4. **Better grouping** - Related topics should be together

### Phase 1: Content Inventory and Analysis
- [x] List all files in docs/ directory (33 RST files total)
- [x] Identify which files can be merged
- [x] Map current location → new location for each file
- [x] Ensure no content will be lost

**Findings**:
- All feature docs are in main docs/ directory (no features/ subdirectory)
- Existing feature files (image.rst, audio.rst, etc.) are brief user guides
- New comprehensive docs (media.rst, models.rst, etc.) are technical references
- Both types of content are valuable and should be preserved

### Phase 2: Create New Structure
- [ ] Update index.rst with new organization
- [ ] Create new section files that will contain merged content
- [ ] Add proper cross-references between related topics

### Phase 3: Content Migration (NO DELETION)

#### Getting Started Section
- [x] Merge quickstart.rst and integrate.rst into installation.rst
- [x] Create tutorial.rst (replaced placeholder howto/first-cast.rst)
- [ ] Create index_new.rst with new structure

#### Content Management Section
- [x] Merge blog.rst + post.rst → content/blogs-and-posts.rst
- [ ] Merge podcast.rst + episode.rst → content/podcasts-and-episodes.rst
- [ ] Move streamfield.rst → content/streamfield.rst
- [ ] Create content/organization.rst from tags.rst

#### Media Section
- [ ] Keep media.rst as media/overview.rst
- [ ] Merge image.rst + gallery.rst + responsive-images.rst → media/images-and-galleries.rst
- [ ] Merge audio.rst + transcript.rst → media/audio-and-transcripts.rst
- [ ] Move video.rst → media/video.rst

#### Features Section
- [ ] Move comments.rst → features/comments.rst
- [ ] Move themes.rst → features/themes.rst
- [ ] Move social-media.rst → features/social-media.rst
- [ ] Move frontend.rst → features/frontend.rst
- [ ] Move feeds.rst → features/feeds.rst
- [ ] Move performance.rst → features/performance.rst

#### API & Configuration Section
- [ ] Move api.rst → reference/api.rst
- [ ] Move models.rst → reference/models.rst
- [ ] Move settings.rst → reference/settings.rst
- [ ] Move context-processors.rst → reference/context-processors.rst
- [ ] Move django-admin.rst → reference/django-admin.rst

#### Operations Section
- [ ] Move backup.rst → operations/backup.rst
- [ ] Move management-commands.rst → operations/management-commands.rst
- [ ] Extract migration content from howto/index.rst → operations/migrations.rst

### Phase 4: Verification
- [ ] Check all original files are accounted for
- [ ] Verify no content was deleted
- [ ] Test all internal links still work
- [ ] Build docs and check for warnings

### Files to Process from features/

Based on features.rst toctree:
1. audio.rst - Merge with transcript.rst
2. blog.rst - Merge with post.rst
3. backup.rst - Move to operations
4. categories.rst - Merge with tags.rst
5. chaptermarks.rst - Include in audio section
6. comments.rst - Move to features
7. custom_homepage.rst - Move to features
8. django-admin.rst - Move to reference
9. episode.rst - Merge with podcast.rst
10. external-comments.rst - Include in comments.rst
11. faceted-search.rst - Move to features
12. feeds.rst - Move to features
13. first-cast.rst - Move to tutorial
14. frontend.rst - Move to features
15. gallery.rst - Merge with image.rst
16. image.rst - Merge with gallery.rst and responsive-images.rst
17. management-commands.rst - Move to operations
18. models.rst - Already enhanced, move to reference
19. performance.rst - Move to features
20. podcast.rst - Merge with episode.rst
21. post.rst - Merge with blog.rst
22. responsive-images.rst - Merge with image.rst
23. social-media.rst - Move to features
24. tags.rst - Merge with categories.rst
25. themes.rst - Move to features
26. transcript.rst - Merge with audio.rst
27. video.rst - Move to media section

### Migration Strategy
1. Create new directory structure first
2. Copy (not move) content to new locations
3. Merge content where appropriate
4. Update all cross-references
5. Only after verification, remove old files
- Add specific PR numbers or commits when tasks are completed
