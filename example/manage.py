#!/usr/bin/env python

import os
import sys


if __name__ == "__main__":
    # handle DJANGO_SETTINGS_MODULE
    # os.environ.setdefault("DJANGO_SETTINGS_MODULE", "example_site.settings.dev")
    os.environ["DJANGO_SETTINGS_MODULE"] = "example_site.settings.dev"

    # Are we starting a notebook server? -> DJANGO_ALLOW_ASYNC_UNSAFE=true
    # chdir to notebooks
    if "--notebook" in set(sys.argv):
        os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
        print("starting a notebook server")
        os.chdir("notebooks")

    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)
