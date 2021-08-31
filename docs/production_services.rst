Useful third party services for production
==========================================

There are some services that might be useful or even required when you run a website. Being
able to send mail for example is quite useful if you want to send newly registered users
a confirmation link.

Mailgun
-------

If you use mailgun_ as an email service you have to register a mailgun account and set up your
dns records accordingly. One caveat: If you use the eu region you have to change your base api
url in "config/settings/production.py" to:

.. code-block:: python

    "MAILGUN_API_URL": env("MAILGUN_API_URL", default="https://api.eu.mailgun.net/v3"),

Sentry
------

This is the place where tracebacks that occured on the production system get recorded.
You'll need to signup for an account.

Amazon S3
---------

You'll probably use S3 for storing uploaded files and for your MEDIA_ROOT.
.. _`mailgun`: https://mailgun.com
