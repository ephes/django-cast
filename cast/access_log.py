import pytz
# import pandas as pd

from io import StringIO
from datetime import datetime

from .models import Request


def get_last_request_position(access_log_path, last_request):
    """
    Find the last position of a request with ip and timestamp in
    an access logfile. Used to find all requests which are not yet immported.
    There could be multiple requests with the same ip and timestamp, therefore
    we have to collect all of them (candidates) and then return just the
    position of the last one.
    """
    if last_request is None:
        return 0
    strptime = datetime.strptime
    last_ip = last_request.ip
    last_timestamp = last_request.timestamp
    candidates = []
    with open(access_log_path) as f:
        for position, line in enumerate(f):
            if last_ip in line:
                date_str = line.split("[")[1].split("]")[0]
                timestamp = strptime(date_str, "%d/%b/%Y:%H:%M:%S %z")
                if timestamp == last_timestamp:
                    candidates.append((position, line))
                if timestamp > last_timestamp:
                    break
    return candidates[-1][0]


def parse_str(x):
    """
    Returns the string delimited by two characters.

    Example:
        `>>> parse_str('[my string]')`
        `'my string'`
    """
    return x[1:-1] if x is not None else x


def access_log_to_buffer(access_log_path, start_position=0, chunk_size=None):
    """
    Read all lines from access_log_path starting at start_position and append
    them to an empty buffer. Return that buffer.
    """
    log_buffer = StringIO()
    with open(access_log_path) as f:
        line_count = 0
        for position, line in enumerate(f):
            if position > start_position:
                log_buffer.write(line)
                line_count += 1
                if chunk_size is not None and line_count == chunk_size:
                    # read only chunk_size lines if set
                    break
    log_buffer.seek(0)
    return log_buffer


def parse_datetime(x):
    """
    Parses datetime with timezone formatted as:
        `[day/month/year:hour:minute:second zone]`

    Example:
        `>>> parse_datetime('13/Nov/2015:11:45:42 +0000')`
        `datetime.datetime(2015, 11, 3, 11, 45, 4, tzinfo=<UTC>)`

    Due to problems parsing the timezone (`%z`) with `datetime.strptime`, the
    timezone will be obtained using the `pytz` library.
    """
    dt = datetime.strptime(x[1:-7], "%d/%b/%Y:%H:%M:%S")
    dt_tz = int(x[-6:-3]) * 60 + int(x[-3:-1])
    return dt.replace(tzinfo=pytz.FixedOffset(dt_tz))


#def get_dataframe_from_position(access_log_path, start_position=0, chunk_size=None):
#    log_buffer = access_log_to_buffer(
#        access_log_path, start_position=start_position, chunk_size=chunk_size
#    )
#    df = pd.read_csv(
#        log_buffer,
#        sep=r'\s(?=(?:[^"]*"[^"]*")*[^"]*$)(?![^\[]*\])',
#        engine="python",
#        na_values="-",
#        header=None,
#        usecols=[0, 3, 4, 5, 6, 7, 8],
#        names=[
#            "ip",
#            "user",
#            "user1",
#            "timestamp",
#            "request",
#            "status",
#            "size",
#            "referer",
#            "user_agent",
#        ],
#        converters={
#            "timestamp": parse_datetime,
#            "request": parse_str,
#            "status": int,
#            "size": int,
#            "referer": parse_str,
#            "user_agent": parse_str,
#        },
#    )
#    df = df.drop(df[df.ip.str.len() > 100].index)
#    try:
#        # breaks on empty df
#        df[["method", "path", "protocol"]] = df.request.str.split(" ", expand=True)
#    except ValueError:
#        pass
#    df = df.drop("request", axis=1)
#    return df


def pandas_rows_to_dict(rows):
    """
    Takes a row from df.iterrows() and makes it json serializable.
    """
    request_method_lookup = {v: k for k, v in Request.REQUEST_METHOD_CHOICES}
    protocol_lookup = {v: k for k, v in Request.HTTP_PROTOCOL_CHOICES}
    # dunno why this only works on single row
    # values = {"referer": None, "user_agent": None}
    # row_dict = row.fillna(value=values).to_dict()
    aux = []
    for row_dict in rows:
        row_dict["method"] = request_method_lookup[row_dict["method"]]
        row_dict["protocol"] = protocol_lookup[row_dict["protocol"]]
        row_dict["timestamp"] = row_dict["timestamp"].isoformat()
        for attr in ("method", "protocol", "status", "size"):
            row_dict[attr] = str(row_dict[attr])
        aux.append(row_dict)
    return aux
