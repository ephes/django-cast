import os

from getpass import getpass

from django.core.management.base import BaseCommand

import requests


class Command(BaseCommand):
    help = "Get api token for user providing username/password"

    def handle(self, *args, **options):
        username = os.environ.get("USERNAME", "analytics")
        obtain_token_url = os.environ.get("OBTAIN_TOKEN_URL")

        params = {"username": username, "password": getpass()}
        r = requests.post(obtain_token_url, data=params)
        token = r.json()["token"]
        print("token: ", token)
