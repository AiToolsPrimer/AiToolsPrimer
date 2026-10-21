"""Minimal OAuth 1.0a HMAC-SHA1 signer (X API v2 user context, Tumblr). No extra deps."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from urllib.parse import quote, urlsplit, parse_qsl


def _pct(s: str) -> str:
    return quote(s, safe="~")


def sign(method: str, url: str, params: dict[str, str], consumer_key: str, consumer_secret: str, token: str, token_secret: str, *, nonce: str | None = None, timestamp: str | None = None) -> str:
    """Return the value for the ``Authorization`` header."""
    oauth = {
        "oauth_consumer_key": consumer_key,
        "oauth_nonce": nonce or secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": timestamp or str(int(time.time())),
        "oauth_token": token,
        "oauth_version": "1.0",
    }
    parts = urlsplit(url)
    base_url = f"{parts.scheme}://{parts.netloc}{parts.path}"
    all_params = dict(parse_qsl(parts.query, keep_blank_values=True))
    all_params.update(params)
    all_params.update(oauth)
    norm = "&".join(f"{k}={v}" for k, v in sorted((_pct(k), _pct(v)) for k, v in all_params.items()))
    base = "&".join([method.upper(), _pct(base_url), _pct(norm)])
    key = f"{_pct(consumer_secret)}&{_pct(token_secret)}"
    digest = hmac.new(key.encode(), base.encode(), hashlib.sha1).digest()
    oauth["oauth_signature"] = base64.b64encode(digest).decode()
    return "OAuth " + ", ".join(f'{_pct(k)}="{_pct(v)}"' for k, v in sorted(oauth.items()))
