# Django-Cast Installation Improvement Tasks

## Immediate Tasks (High Priority)

- [ ] Remove empty `example_site/` folder at root level
- [ ] Create `cast.apps.CAST_APPS` constant containing all required apps
- [ ] Create `cast.apps.CAST_MIDDLEWARE` constant for required middleware
- [ ] Update installation.rst to use the new constants

## Documentation Improvements (High Priority)

- [ ] Add Python version requirements to installation docs
- [ ] Add database configuration section
- [ ] Explain each required setting (COMMENTS_APP, MEDIA_ROOT, etc.)
- [ ] Add troubleshooting section for common issues
- [ ] Create "Quick Start" section at the beginning

## Simplification Tasks (Medium Priority)

- [ ] Create `cast.urls.urlpatterns` to simplify URL configuration
- [ ] Add default settings module or mixin
- [ ] Document optional vs required apps
- [ ] Add configuration validation/health check command

## Developer Experience (Medium Priority)

- [ ] Create `django-cast-quickstart` management command
- [ ] Add project template for startproject command
- [ ] Create minimal working example in 20 lines of code
- [ ] Add "Try it in 5 minutes" guide

## Example Project Improvements (Low Priority)

- [ ] Clean up example project structure
- [ ] Add more comments explaining configuration
- [ ] Create separate minimal and full examples
- [ ] Add example with custom templates

## Advanced Features (Low Priority)

- [ ] Create Docker quickstart image
- [ ] Add cookiecutter template
- [ ] Create interactive setup wizard
- [ ] Add migration guide from other blog platforms

## Testing and Validation

- [ ] Test installation process on fresh virtualenv
- [ ] Validate all documentation examples work
- [ ] Create automated test for quickstart process
- [ ] Add CI test for example project