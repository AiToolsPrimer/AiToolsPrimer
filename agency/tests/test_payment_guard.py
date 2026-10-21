import pytest

from agency.safety.payment_guard import GuardedHTTP, PaymentBlocked, inspect_request, luhn_ok


def test_luhn():
    assert luhn_ok("4242 4242 4242 4242")
    assert not luhn_ok("4242 4242 4242 4241")


@pytest.mark.parametrize("method,url,body", [
    ("GET", "https://checkout.stripe.com/pay/cs_test", None),
    ("POST", "https://www.paypal.com/checkoutnow", None),
    ("POST", "https://x.com/i/premium/upgrade", None),
    ("GET", "https://ads.google.com/aw/campaigns/new", None),
    ("POST", "https://example.com/api/v1/billing", None),
    ("POST", "https://example.com/post", b'{"card_number": "4242424242424242"}'),
    ("POST", "https://example.com/post", "my IBAN is DE89370400440532013000"),
    ("POST", "https://somesite.io/pricing", None),
    ("POST", "https://graph.facebook.com/v21.0/123/promotions/boost-post", None),
])
def test_blocked(method, url, body):
    assert inspect_request(method, url, body)


@pytest.mark.parametrize("method,url,body", [
    ("POST", "https://bsky.social/xrpc/com.atproto.repo.createRecord", b'{"text": "hello"}'),
    ("GET", "https://somesite.io/pricing", None),
    ("GET", "https://html.duckduckgo.com/html/?q=free+platforms", None),
    ("POST", "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable", None),
    ("POST", "https://api.x.com/2/tweets", b'{"text":"Our phone number is 0039 333 1234567"}'),
])
def test_allowed(method, url, body):
    assert inspect_request(method, url, body) is None


def test_guarded_http_raises_and_audits():
    seen = []
    http = GuardedHTTP(audit=seen.append)
    with pytest.raises(PaymentBlocked):
        http.post("https://js.stripe.com/v3/charge")
    assert seen and seen[0]["blocked"] and "stripe" in seen[0]["reason"]
