#!/usr/bin/env python3
"""Explore the KNHB match data API from the command line (no Home Assistant needed).

    python3 tools/probe.py /clubs
    python3 tools/probe.py /clubs/<club_id>
    python3 tools/probe.py /poules/<poule_id>/teams/<team_id>

Prints the JSON response. The device UUID and token are kept in ~/.cache/knhb-hockey-probe.json
so repeated runs reuse one registration. See docs/api.md.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

BASE_URL = "https://app.hockeyweerelt.nl"
API_VERSION = "8"
STATE = os.path.expanduser("~/.cache/knhb-hockey-probe.json")


def signature(timestamp: str, path_and_query: str, device_uuid: str) -> str:
    """sha1(timestamp + cleaned path + cleaned query + reversed uuid), see docs/api.md."""
    parts = urllib.parse.urlsplit(path_and_query)
    path = re.sub(r"[^a-zA-Z0-9\-/]+", "", parts.path)
    query = "".join(
        re.sub(r"[^a-zA-Z0-9\-/=]+", "", k) + "=" + re.sub(r"[^a-zA-Z0-9\-/=]+", "", v)
        for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
        if k
    )
    return hashlib.sha1(f"{timestamp}{path}{query}{device_uuid[::-1]}".encode()).hexdigest()


class Probe:
    def __init__(self) -> None:
        try:
            with open(STATE) as f:
                state = json.load(f)
            self.uuid, self.token = state["uuid"], state["token"]
        except (OSError, ValueError, KeyError):
            self.uuid, self.token = str(uuid.uuid4()), None

    def _request(self, method: str, path: str, body: dict | None = None, signed: bool = True):
        headers = {"Accept": "application/json", "Content-Type": "application/json",
                   "X-Requested-With": "XMLHttpRequest", "User-Agent": "knhb-hockey-probe"}
        if signed:
            ts = str(int(time.time()))
            headers |= {"X-HAPI-Authorization": self.token or "", "X-HAPI-Timestamp": ts,
                        "X-HAPI-Signature": signature(ts, path, self.uuid), "X-HAPI-Version": API_VERSION}
        req = urllib.request.Request(BASE_URL + path, method=method, headers=headers,
                                     data=json.dumps(body).encode() if body else None)
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)

    def register(self) -> None:
        self.token = self._request("POST", "/device/register", {"uuid": self.uuid, "os": "Web"}, signed=False)["token"]
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        with open(STATE, "w") as f:
            json.dump({"uuid": self.uuid, "token": self.token}, f)

    def get(self, path: str):
        if not self.token:
            self.register()
        try:
            return self._request("GET", path)
        except urllib.error.HTTPError as err:
            if err.code != 401:
                raise
            self.register()
            return self._request("GET", path)


if __name__ == "__main__":
    if len(sys.argv) != 2 or not sys.argv[1].startswith("/"):
        sys.exit(__doc__)
    print(json.dumps(Probe().get(sys.argv[1]), ensure_ascii=False, indent=2))
