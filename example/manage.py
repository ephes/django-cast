#!/usr/bin/env python

import os
import sys


def prepare_notebook_environment():
    from pathlib import Path

    os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
    os.chdir("notebooks")
    example_project_path = Path(__file__).resolve().parent
    os.environ["PYTHONPATH"] = str(example_project_path)


if __name__ == "__main__":
    # handle DJANGO_SETTINGS_MODULE
    # os.environ.setdefault("DJANGO_SETTINGS_MODULE", "example_site.settings.dev")
    os.environ["DJANGO_SETTINGS_MODULE"] = "example_site.settings.dev"

    # Are we starting a notebook server? -> DJANGO_ALLOW_ASYNC_UNSAFE=true
    # chdir to notebooks and add example project to pythonpath
    if "--notebook" in set(sys.argv):
        prepare_notebook_environment()

    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)
