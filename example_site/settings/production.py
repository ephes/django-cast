from .base import *

DEBUG = False

try:
    from .local import *
except ImportError:
    pass


ADMIN_URL = "hidden_admin/"