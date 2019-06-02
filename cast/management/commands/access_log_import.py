import os
import time
import requests

from pathlib import Path

from django.core.management.base import BaseCommand

from ...models import Request
from ...access_log import pandas_rows_to_dict
from ...access_log import get_last_request_position
from ...access_log import get_dataframe_from_position


def insert_log_chunk(request_api_url, api_token, access_log_path, chunk_size=1000):
    now = time.time()
    last_request = None
    try:
        last_request = Request.objects.all().order_by("-timestamp")[0]
    except IndexError:
        pass
    last_position = get_last_request_position(access_log_path, last_request)
    print("last_position: ", last_position)
    df = get_dataframe_from_position(
        access_log_path, start_position=last_position, chunk_size=chunk_size
    )
    if df.shape[0] == 0:
        # no more lines
        return None, True
    print("get df: ", time.time() - now)
    raw_rows = df.iloc[:chunk_size].fillna("").to_dict(orient="rows")
    rows = pandas_rows_to_dict(raw_rows)
    print("transform rows: ", time.time() - now)
    headers = {"Authorization": f"Token {api_token}"}
    result = requests.post(request_api_url, json=rows, headers=headers)
    print("total chunk: ", time.time() - now)
    return result, False


class Command(BaseCommand):
    help = "Import requests from an access.log file."

    def handle(self, *args, **options):
        request_api_url = os.environ.get("REQUEST_API_URL")
        access_log_path = Path(os.environ.get("ACCESS_LOG_PATH"))
        api_token = os.environ.get("API_TOKEN")
        print(request_api_url, access_log_path, api_token)
        now = time.time()
        done = False
        while not done:
            result, done = insert_log_chunk(
                request_api_url, api_token, access_log_path, chunk_size=20000
            )
        print("total: ", time.time() - now)
