from .base import *  # noqa


# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = "fi6y_c!w#4+16srq_%z+(dj=7d8&5+reik+_171*=e8(0(157x"

# SECURITY WARNING: define the correct hosts in production!
ALLOWED_HOSTS = ["*"]

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

INSTALLED_APPS.extend(  # noqa
    [
        "django_extensions",
    ]
)


try:
    from .local import *  # noqa
except ImportError:
    pass
