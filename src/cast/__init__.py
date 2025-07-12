"""
Django and Wagtail based blogging / podcasting package
"""

__version__ = "0.2.47"

# Make installation easier by exposing required apps and middleware
from .apps import CAST_APPS, CAST_MIDDLEWARE

__all__ = ["CAST_APPS", "CAST_MIDDLEWARE"]
