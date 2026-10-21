"""IndexNow: tell Bing, Yandex, Naver, Seznam (and partners) about new or changed site URLs.
Google has no ping endpoint any more: submit the sitemap once in Search Console."""
from __future__ import annotations

import re
import secrets
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from agency.safety.payment_guard import GuardedHTTP


class IndexNow:
    def __init__(self, http: GuardedHTTP, site: str, key: str = "", key_dir: Path | None = None, dry_run: bool = True):
        self.http, self.site, self.dry_run = http, site.rstrip("/"), dry_run
        self.host = urlsplit(self.site).hostname or ""
        self.key_dir = key_dir
        self.key = key or self._load_or_make_key()

    def _load_or_make_key(self) -> str:
        if not self.key_dir:
            return secrets.token_hex(16)
        self.key_dir.mkdir(parents=True, exist_ok=True)
        f = self.key_dir / "indexnow.key"
        if f.exists():
            return f.read_text().strip()
        k = secrets.token_hex(16)
        f.write_text(k)
        (self.key_dir / f"{k}.txt").write_text(k)
        return k

    @property
    def key_file_url(self) -> str:
        return f"{self.site}/{self.key}.txt"

    def submit(self, urls: list[str]) -> dict[str, Any]:
        urls = [u for u in urls if u.startswith(self.site)]
        if not urls:
            return {"submitted": 0}
        if self.dry_run:
            return {"submitted": len(urls), "dry_run": True}
        r = self.http.post("https://api.indexnow.org/indexnow", json={"host": self.host, "key": self.key, "keyLocation": self.key_file_url, "urlList": urls[:10000]}, headers={"Content-Type": "application/json; charset=utf-8"})
        return {"submitted": len(urls), "status": r.status_code}

    @staticmethod
    def urls_from_sitemap(xml: str) -> list[str]:
        return re.findall(r"<loc>(.*?)</loc>", xml)
