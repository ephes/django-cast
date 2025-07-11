# Django-Cast Installation Analysis

## Current State

### Pain Points

1. **Overwhelming INSTALLED_APPS List**
   - Users must add 26 third-party apps manually
   - Easy to miss one or get the order wrong
   - No explanation of what each app does or why it's needed

2. **Confusing Example Folders**
   - Two folders: `example/` (active) and `example_site/` (empty leftover)
   - Not clear which to use or why both exist
   - Requires checking out the entire repository

3. **Minimal Configuration Guidance**
   - COMMENTS_APP setting not explained
   - MEDIA_ROOT/MEDIA_URL required but minimal explanation
   - No mention of static files configuration
   - No database configuration guidance

4. **Complex URL Configuration**
   - Uses custom `cast_and_wagtail_urls` import
   - Media/static file serving only shown for DEBUG mode
   - No explanation of what URLs are actually included

5. **Missing Essential Information**
   - No mention of required Python version
   - No guidance on database choice
   - No information about optional features
   - ffmpeg mentioned as afterthought

## Comparison with Other Django Packages

### Django CMS
- Provides `djangocms` command that creates a project
- Interactive setup wizard
- Automatically configures settings

### Wagtail
- Has `wagtail start` command similar to `django-admin startproject`
- Creates project with sensible defaults
- Provides project templates

### Django-Oscar
- Provides sandbox sites for quick testing
- Has detailed "Start Here" guide
- Uses app registry pattern for easier customization

## Proposed Solutions

### Solution 1: Management Command (Recommended)
Create a `django-cast-quickstart` command that:
- Creates a new Django project with all settings configured
- Includes minimal but working templates
- Sets up media/static files correctly
- Creates initial database

**Pros:**
- Single command to get started
- No manual configuration needed
- Can include best practices

**Cons:**
- Requires maintaining project template
- May conflict with existing projects

### Solution 2: App Registry Pattern
Create a `CAST_APPS` constant that includes all required apps:

```python
from cast import CAST_APPS

INSTALLED_APPS = [
    ...
] + CAST_APPS
```

**Pros:**
- Simpler than listing all apps
- Can manage app order internally
- Easy to update dependencies

**Cons:**
- Still requires manual settings configuration
- Less flexible for advanced users

### Solution 3: Settings Module
Provide a base settings module to inherit from:

```python
from cast.conf import CastSettings

class Settings(CastSettings):
    DEBUG = True
    SECRET_KEY = 'your-secret-key'
```

**Pros:**
- All configuration in one place
- Can provide sensible defaults
- Easy to override

**Cons:**
- May conflict with existing settings structure
- Less transparent about what's configured

### Solution 4: Docker/Docker Compose
Provide a ready-to-run Docker setup:

```bash
docker run -p 8000:8000 django-cast/quickstart
```

**Pros:**
- Zero installation needed
- Includes all dependencies (ffmpeg, etc.)
- Good for evaluation

**Cons:**
- Requires Docker knowledge
- Not suitable for production
- Harder to customize

## Recommendations

1. **Immediate Improvements:**
   - Remove empty `example_site/` folder
   - Create `cast.apps.CAST_APPS` constant for easier installation
   - Add detailed comments to installation docs

2. **Short Term:**
   - Create quickstart management command
   - Write "Getting Started in 5 Minutes" guide
   - Add troubleshooting section

3. **Long Term:**
   - Provide project templates
   - Create interactive setup wizard
   - Add health check command

## Implementation Priority

1. **Clean up example folders** (remove empty one)
2. **Create CAST_APPS constant** (backward compatible)
3. **Rewrite installation docs** with:
   - Quick start section
   - Detailed configuration section
   - Troubleshooting guide
4. **Create quickstart command**
5. **Add Docker option** for evaluation