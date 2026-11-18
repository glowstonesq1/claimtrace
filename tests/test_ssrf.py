import httpx
import pytest

from claimtrace.ingestion import IngestError
from claimtrace.ingestion.url import fetch_url, validate_url

PUBLIC = "93.184.216.34"


def resolver(mapping):
    return lambda host: mapping[host]


@pytest.mark.parametrize("url,ips", [
    ("http://internal.example/", ["10.0.0.5"]),
    ("http://meta.example/", ["169.254.169.254"]),
    ("http://local.example/", ["127.0.0.1"]),
    ("http://v6.example/", ["::1"]),
    ("http://mapped.example/", ["::ffff:127.0.0.1"]),
    ("http://mixed.example/", [PUBLIC, "192.168.1.1"]),
])
def test_private_addresses_blocked(url, ips):
    host = url.split("/")[2]
    with pytest.raises(IngestError) as e:
        validate_url(url, resolver({host: ips}))
    assert e.value.code == "url_blocked"


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://x.example/a", "http://user:pw@x.example/",
                                 "http://x.example:8080/", "http://127.0.0.1/", "http://[::1]/"])
def test_bad_schemes_ports_literals(url):
    with pytest.raises(IngestError):
        validate_url(url, resolver({"x.example": [PUBLIC]}))


def test_connection_is_pinned_to_validated_ip_and_redirects_rechecked():
    seen = []
    answers = iter([[PUBLIC], ["127.0.0.1"]])  # DNS rebinding: second lookup turns private

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.host, request.headers["host"]))
        return httpx.Response(302, headers={"location": "http://evil.example/next"})

    with pytest.raises(IngestError) as e:
        fetch_url("http://good.example/doc.pdf", resolve=lambda h: next(answers),
                  transport=httpx.MockTransport(handler))
    assert seen == [(PUBLIC, "good.example")]  # we connected to the IP we checked, not a fresh lookup
    assert e.value.code == "url_blocked"


def test_successful_fetch_with_type_check():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/markdown"}, content=b"# Hello")

    name, data = fetch_url("https://good.example/a", resolve=lambda h: [PUBLIC], transport=httpx.MockTransport(handler))
    assert name.endswith(".md") and data == b"# Hello"


def test_html_responses_rejected():
    def handler(request):
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"<html>")

    with pytest.raises(IngestError):
        fetch_url("https://good.example/", resolve=lambda h: [PUBLIC], transport=httpx.MockTransport(handler))
