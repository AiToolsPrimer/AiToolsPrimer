"""Hard block on anything that could cost money.

Every outbound HTTP request the agency makes goes through ``GuardedHTTP``.  The
guard refuses, before the request leaves the machine:

* any host belonging to a payment processor or app store billing endpoint;
* any request to a URL whose path or query looks like checkout, billing,
  subscription, upgrade, top-up, purchase or donation;
* any request whose body carries a card number (Luhn-valid 13-19 digits), a CVV
  field, an IBAN, or a crypto wallet address;
* any write (POST/PUT/PATCH) to a URL mentioning "pricing", "plan" or "credits"
  unless it is an official API host on the allowlist.

Reads of pricing pages are allowed: the scout must be able to *see* that a
platform is free.  Nothing can be paid for through this process.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable
from urllib.parse import urlsplit

import httpx

PROCESSOR_HOSTS = (
    "stripe.com", "checkout.stripe.com", "js.stripe.com", "paypal.com", "paypalobjects.com", "braintreegateway.com",
    "adyen.com", "squareup.com", "square.com", "klarna.com", "afterpay.com", "affirm.com", "mollie.com", "payu.com",
    "2checkout.com", "paddle.com", "lemonsqueezy.com", "gumroad.com", "fastspring.com", "chargebee.com",
    "recurly.com", "authorize.net", "worldpay.com", "checkout.com", "wise.com", "revolut.com", "coinbase.com",
    "binance.com", "buy.itunes.apple.com", "play.google.com/store/account", "pay.google.com", "apple.com/shop",
    "ads.google.com", "business.facebook.com/ads", "ads.twitter.com", "ads.tiktok.com", "ads.linkedin.com",
    "ads.reddit.com", "ads.pinterest.com", "ads.microsoft.com", "advertising.amazon.com", "ko-fi.com",
    "buymeacoffee.com", "patreon.com/join", "opencollective.com",
)

PAYMENT_PATH = re.compile(
    r"(checkout|billing|payment|payments|pay\b|purchase|buy\b|order\b|subscribe|subscription|upgrade|"
    r"top-?up|add-?funds|credits/(buy|add)|donate|donation|invoice|cart\b|premium/(buy|upgrade)|"
    r"ads?/(create|campaign)|boost(ed)?-?post|promote)",
    re.I,
)
WRITE_SENSITIVE_PATH = re.compile(r"(pricing|plans?\b|credits|wallet|budget)", re.I)

CARD_RE = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
CVV_KEY_RE = re.compile(r'"?(cvv|cvc|cvv2|card_?number|cardnumber|cc_?number|exp(iry|_month|_year)|security_?code)"?\s*[:=]', re.I)
IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")
CRYPTO_RE = re.compile(r"\b(0x[a-fA-F0-9]{40}|bc1[a-z0-9]{25,62}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})\b")

# Official API hosts where a POST with the word "plan"/"credits" in the path is still not money
API_ALLOWLIST = (
    "api.bsky.app", "bsky.social", "mastodon.social", "api.twitter.com", "api.x.com", "upload.twitter.com",
    "graph.facebook.com", "graph.threads.net", "www.googleapis.com", "youtube.googleapis.com",
    "oauth2.googleapis.com", "oauth.reddit.com", "www.reddit.com", "api.telegram.org", "api.linkedin.com",
    "open.tiktokapis.com", "api.pinterest.com", "dev.to", "gql.hashnode.com", "api.tumblr.com",
    "127.0.0.1", "localhost",
)


class PaymentBlocked(PermissionError):
    pass


def luhn_ok(number: str) -> bool:
    digits = [int(c) for c in number if c.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _host_matches(host: str, patterns: Iterable[str], path: str = "") -> bool:
    host = host.lower()
    for p in patterns:
        if "/" in p:
            h, _, pth = p.partition("/")
            if (host == h or host.endswith("." + h)) and path.lower().startswith("/" + pth):
                return True
        elif host == p or host.endswith("." + p):
            return True
    return False


def inspect_request(method: str, url: str, body: bytes | str | None = None) -> str | None:
    """Return a human-readable reason to block, or None if the request is fine."""
    parts = urlsplit(url)
    host, path, query = parts.hostname or "", parts.path or "/", parts.query or ""
    method = method.upper()
    if _host_matches(host, PROCESSOR_HOSTS, path):
        return f"payment processor or ads/billing host: {host}{path}"
    if PAYMENT_PATH.search(path) or PAYMENT_PATH.search(query):
        return f"payment-looking URL: {path}"
    if method in {"POST", "PUT", "PATCH"} and WRITE_SENSITIVE_PATH.search(path) and not _host_matches(host, API_ALLOWLIST):
        return f"write to a pricing/plan/credits endpoint on a non-API host: {host}{path}"
    if body:
        text = body.decode("utf-8", "ignore") if isinstance(body, bytes) else body
        if CVV_KEY_RE.search(text):
            return "request body contains card fields"
        for m in CARD_RE.finditer(text):
            if luhn_ok(m.group(0)):
                return "request body contains a card number"
        if IBAN_RE.search(text):
            return "request body contains an IBAN"
        if CRYPTO_RE.search(text) and method != "GET":
            return "request body contains a crypto wallet address"
    return None


@dataclass
class GuardedHTTP:
    """httpx wrapper every agent and connector uses. ``audit`` receives every decision."""

    audit: Callable[[dict[str, Any]], None] | None = None
    timeout: float = 60.0
    user_agent: str = "AiToolsPrimerAgency/0.1 (+https://aitoolsprimer.com)"
    transport: httpx.BaseTransport | None = None
    _client: httpx.Client = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._client = httpx.Client(timeout=self.timeout, follow_redirects=True, headers={"User-Agent": self.user_agent}, transport=self.transport)

    def request(self, method: str, url: str, **kw: Any) -> httpx.Response:
        body: bytes | str | None = None
        if "json" in kw and kw["json"] is not None:
            body = json.dumps(kw["json"])
        elif "data" in kw and kw["data"] is not None:
            body = json.dumps(kw["data"]) if isinstance(kw["data"], dict) else kw["data"]
        elif "content" in kw and kw["content"] is not None:
            body = kw["content"]
        reason = inspect_request(method, url, body if isinstance(body, (bytes, str)) else None)
        if self.audit:
            self.audit({"method": method, "url": url, "blocked": bool(reason), "reason": reason})
        if reason:
            raise PaymentBlocked(f"blocked by payment guard: {reason}")
        return self._client.request(method, url, **kw)

    def get(self, url: str, **kw: Any) -> httpx.Response:
        return self.request("GET", url, **kw)

    def post(self, url: str, **kw: Any) -> httpx.Response:
        return self.request("POST", url, **kw)

    def put(self, url: str, **kw: Any) -> httpx.Response:
        return self.request("PUT", url, **kw)

    def delete(self, url: str, **kw: Any) -> httpx.Response:
        return self.request("DELETE", url, **kw)

    def close(self) -> None:
        self._client.close()
