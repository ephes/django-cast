#!/usr/bin/env python

import os
import shutil
import sys

from pathlib import Path

import django

from django.conf import settings
from django.test.utils import get_runner


def run_tests(*test_args):
    if not test_args:
        test_args = ["tests"]

    os.environ["DJANGO_SETTINGS_MODULE"] = "tests.settings"
    django.setup()
    TestRunner = get_runner(settings)
    test_runner = TestRunner()
    failures = test_runner.run_tests(test_args)
    media_root = Path(settings.MEDIA_ROOT)
    try:
        shutil.rmtree(media_root)  # FIXME move cleanup to tests
    except FileNotFoundError:
        pass
    sys.exit(bool(failures))


if __name__ == "__main__":
    run_tests(*sys.argv[1:])
