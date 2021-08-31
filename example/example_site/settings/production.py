from .base import *  # noqa


DEBUG = False

try:
    from .local import *  # noqa
except ImportError:
    pass


ADMIN_URL = "hidden_admin/"
