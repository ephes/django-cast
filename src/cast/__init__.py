"""
Django and Wagtail based blogging / podcasting package
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("django-cast")
except PackageNotFoundError:
    __version__ = "0+unknown"

# Make installation easier by exposing required apps and middleware
from .apps import CAST_APPS, CAST_MIDDLEWARE

__all__ = ["CAST_APPS", "CAST_MIDDLEWARE"]
