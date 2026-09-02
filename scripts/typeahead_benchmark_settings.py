"""Isolated settings for the typeahead performance spike.

Select the database with ``CAST_BENCHMARK_DB_ENGINE=sqlite|postgresql``. The
PostgreSQL settings deliberately use explicit environment variables so the
benchmark never guesses or connects to a consumer/production database.
"""

import os

from tests.settings import *  # noqa: F403

_engine = os.environ.get("CAST_BENCHMARK_DB_ENGINE", "sqlite")

if _engine == "postgresql":
    DATABASES = {  # noqa: F405
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("CAST_BENCHMARK_DB_NAME", "cast_typeahead_benchmark"),
            "USER": os.environ.get("CAST_BENCHMARK_DB_USER", ""),
            "PASSWORD": os.environ.get("CAST_BENCHMARK_DB_PASSWORD", ""),
            "HOST": os.environ.get("CAST_BENCHMARK_DB_HOST", "/tmp"),
            "PORT": os.environ.get("CAST_BENCHMARK_DB_PORT", "55432"),
        }
    }
elif _engine == "sqlite":
    DATABASES = {  # noqa: F405
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": os.environ.get("CAST_BENCHMARK_DB_NAME", "/tmp/cast-typeahead-benchmark.sqlite3"),
        }
    }
else:
    raise ValueError(f"Unsupported CAST_BENCHMARK_DB_ENGINE: {_engine}")
