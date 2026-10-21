"""Domain authority from the Tranco list (research-grade top-1M ranking, free).
Downloaded once a month into the store; unknown domains count as not authoritative."""
from __future__ import annotations

import csv
import datetime as dt
import io
import zipfile
from urllib.parse import urlsplit

from agency.memory.store import Store
from agency.safety.payment_guard import GuardedHTTP

TRANCO_URL = "https://tranco-list.eu/top-1m.csv.zip"


class Authority:
    def __init__(self, store: Store, http: GuardedHTTP, threshold: int = 50_000, dry_run: bool = False):
        self.store, self.http, self.threshold, self.dry_run = store, http, threshold, dry_run

    @staticmethod
    def domain(url: str) -> str:
        host = (urlsplit(url if "://" in url else "https://" + url).hostname or "").lower()
        return host[4:] if host.startswith("www.") else host

    def rank(self, url: str) -> int | None:
        d = self.domain(url)
        r = self.store.authority_rank(d)
        if r is None and d.count(".") > 1:
            r = self.store.authority_rank(".".join(d.split(".")[-2:]))
        return r

    def is_authoritative(self, url: str) -> bool:
        r = self.rank(url)
        return r is not None and r <= self.threshold

    def refresh(self, max_rows: int = 1_000_000, force: bool = False) -> int:
        """Download the Tranco list (about 20 MB) if older than 30 days."""
        age = self.store.authority_age_days()
        if age is not None and age < 30 and not force:
            return 0
        if self.dry_run:
            return 0
        r = self.http.get(TRANCO_URL, timeout=300)
        if r.status_code != 200:
            return 0
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            name = z.namelist()[0]
            rows = []
            with z.open(name) as f:
                for i, line in enumerate(csv.reader(io.TextIOWrapper(f, encoding="utf-8"))):
                    if len(line) < 2:
                        continue
                    rows.append((line[1].strip().lower(), int(line[0])))
                    if i + 1 >= max_rows:
                        break
        self.store.replace_authority(rows)
        return len(rows)
