---
name: playwright
description: Use Playwright for browser automation and end-to-end testing. Invoke when writing e2e tests, browser automation, or testing web UI interactions.
allowed-tools: Bash(uv:*, npx:*, pytest:*), Read, Write, Edit, Glob, Grep
---

# Playwright Usage Guide

## Installation

For this Python project, use pytest-playwright:

```bash
# Add to dev dependencies
uv add --dev pytest-playwright

# Install browsers
uv run playwright install
```

## Running Tests

```bash
# Run all e2e tests
uv run pytest tests/e2e/

# Run with browser visible (headed mode)
uv run pytest tests/e2e/ --headed

# Run specific test
uv run pytest tests/e2e/test_blog.py::test_homepage -v

# Run with slow motion for debugging
uv run pytest tests/e2e/ --headed --slowmo=500

# Generate test report
uv run pytest tests/e2e/ --html=report.html
```

## Test Structure

Create e2e tests in `tests/e2e/` directory:

```python
# tests/e2e/conftest.py
import pytest
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from playwright.sync_api import Page


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    return {
        **browser_context_args,
        "viewport": {"width": 1280, "height": 720},
    }


@pytest.fixture
def live_server(live_server):
    """Provide Django live server for e2e tests."""
    return live_server
```

```python
# tests/e2e/test_blog.py
import pytest
from playwright.sync_api import Page, expect


def test_homepage_loads(page: Page, live_server):
    page.goto(live_server.url)
    expect(page).to_have_title("...")


def test_blog_navigation(page: Page, live_server):
    page.goto(f"{live_server.url}/blog/")
    page.click("text=Read more")
    expect(page.locator("h1")).to_be_visible()
```

## Common Patterns

### Page Object Model

```python
# tests/e2e/pages/blog_page.py
class BlogPage:
    def __init__(self, page: Page):
        self.page = page
        self.post_links = page.locator(".post-link")
        self.search_input = page.locator("[data-testid=search]")

    def navigate(self, base_url: str):
        self.page.goto(f"{base_url}/blog/")

    def search(self, query: str):
        self.search_input.fill(query)
        self.search_input.press("Enter")
```

### Screenshots and Tracing

```python
def test_with_screenshot(page: Page, live_server):
    page.goto(live_server.url)
    page.screenshot(path="screenshot.png")

# Enable tracing in conftest.py
@pytest.fixture(scope="function")
def page(context):
    context.tracing.start(screenshots=True, snapshots=True)
    page = context.new_page()
    yield page
    context.tracing.stop(path="trace.zip")
```

### Waiting for Elements

```python
# Wait for element to be visible
page.wait_for_selector(".loading", state="hidden")

# Wait for navigation
with page.expect_navigation():
    page.click("a.nav-link")

# Wait for network idle
page.wait_for_load_state("networkidle")
```

## Debugging

```bash
# Record test actions (codegen)
uv run playwright codegen http://localhost:8000

# Debug mode with inspector
PWDEBUG=1 uv run pytest tests/e2e/test_blog.py -v

# View trace
uv run playwright show-trace trace.zip
```

## Configuration

Add to `pyproject.toml`:

```toml
[tool.pytest.ini_options]
# ... existing config ...
markers = [
    "e2e: end-to-end tests (require browser)",
]
```

Run e2e tests separately:

```bash
uv run pytest -m e2e
```
