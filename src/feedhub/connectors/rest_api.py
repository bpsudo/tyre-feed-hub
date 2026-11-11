import json
import os
import time

import requests

from feedhub.connectors import local_file

TIMEOUT_SECONDS = 10
MAX_RETRIES = 3
MAX_WAIT_SECONDS = 30


class RateLimitError(RuntimeError):
    pass


def api_settings(source):
    url = os.environ.get(source["url_env"], "")
    if not url:
        return None
    return {"url": url.rstrip("/"), "key": os.environ.get(source["key_env"], "")}


def describe(source):
    settings = api_settings(source)
    if settings is None:
        return f"{source['url_env']} not set, {local_file.describe(source)}"
    return settings["url"] + source["exports_endpoint"]


def wait_seconds(response):
    try:
        return min(float(response.headers.get("Retry-After", "1")), MAX_WAIT_SECONDS)
    # Retry-After can also be an HTTP date: wait one second in that case.
    except ValueError:
        return 1


def get_json(session, url, params=None):
    """GET a JSON resource, waiting and trying again while the server answers HTTP 429."""
    for attempt in range(MAX_RETRIES + 1):
        response = session.get(url, params=params, timeout=TIMEOUT_SECONDS)
        if response.status_code != 429:
            response.raise_for_status()
            return response.json()
        if attempt < MAX_RETRIES:
            time.sleep(wait_seconds(response))
    raise RateLimitError(f"still HTTP 429 after {MAX_RETRIES} retries: {url}")


def download_items(session, url, items_key, per_page):
    items = []
    page = 1
    while True:
        data = get_json(session, url, {"page": page, "per_page": per_page})
        items += data[items_key]
        # A page shorter than per_page is the last one.
        if len(data[items_key]) < per_page:
            return items
        page += 1


def fetch_files(source, skip_names=()):
    """Download the new daily exports from the API, or read the local folder when no URL is set."""
    settings = api_settings(source)
    if settings is None:
        return local_file.fetch_files(source, skip_names)

    files = []
    with requests.Session() as session:
        session.headers[source["key_header"]] = settings["key"]
        exports = get_json(session, settings["url"] + source["exports_endpoint"])["exports"]
        for export_date in sorted(exports):
            name = source["file_name"].format(date=export_date.replace("-", ""))
            if name in skip_names:
                continue
            url = settings["url"] + source["items_endpoint"].format(date=export_date)
            items = download_items(session, url, source["items_key"], source.get("per_page", 100))
            # Same layout as the file of the local folder, so one mapping reads both.
            content = {"datum": export_date, source["items_key"]: items}
            files.append((name, json.dumps(content, ensure_ascii=False).encode("utf-8")))
    return files
