"""Static project site (apps/site): no third-party scripts (GSAP is self-hosted, still SRI-pinned), and a
CSP limits the page to its own origin."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

SITE = Path(__file__).resolve().parents[1] / "apps" / "site"


class _Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.scripts: list[dict[str, str | None]] = []
        self.inline_scripts = 0
        self.links: list[dict[str, str | None]] = []
        self.metas: list[dict[str, str | None]] = []
        self.inline_styles = 0
        self._in_script = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if "style" in a:
            self.inline_styles += 1
        if tag == "script":
            self.scripts.append(a)
            self._in_script = "src" not in a
        elif tag == "link":
            self.links.append(a)
        elif tag == "meta":
            self.metas.append(a)
        elif tag == "style":
            self.inline_styles += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._in_script = False

    def handle_data(self, data: str) -> None:
        if self._in_script and data.strip():
            self.inline_scripts += 1


def _page() -> _Page:
    p = _Page()
    p.feed((SITE / "index.html").read_text())
    return p


def _csp() -> dict[str, list[str]]:
    metas = [m for m in _page().metas if (m.get("http-equiv") or "").lower() == "content-security-policy"]
    assert len(metas) == 1, "index.html needs exactly one CSP meta tag"
    out: dict[str, list[str]] = {}
    for part in (metas[0].get("content") or "").split(";"):
        if part.strip():
            name, *values = part.split()
            out[name] = values
    return out


def test_no_third_party_scripts_and_vendored_gsap_matches_its_sri():
    import base64
    import hashlib

    scripts = [s for s in _page().scripts if s.get("src")]
    assert not [s for s in scripts if re.match(r"(?:https?:)?//", s["src"] or "")], "no third-party scripts"
    gsap = [s for s in scripts if "vendor/gsap/" in (s["src"] or "")]
    assert len(gsap) == 2
    for s in gsap:
        body = (SITE / (s["src"] or "")).read_bytes()
        digest = "sha384-" + base64.b64encode(hashlib.sha384(body).digest()).decode()
        assert s.get("integrity") == digest, s


def test_csp_allows_only_self():
    csp = _csp()
    assert csp["default-src"] == ["'self'"]
    assert csp["script-src"] == ["'self'"]
    assert set(csp["font-src"]) == {"'self'"}  # fonts are self-hosted
    assert csp["object-src"] == ["'none'"]
    assert csp["base-uri"] == ["'self'"]
    for name, values in csp.items():
        assert not {"'unsafe-inline'", "'unsafe-eval'", "*", "https:", "http:"} & set(values), name


def test_page_needs_no_inline_script_or_style_and_no_third_party_fonts():
    page = _page()
    assert page.inline_scripts == 0, "inline scripts are blocked by the CSP; move them to a file"
    assert page.inline_styles == 0
    hrefs = [link.get("href") or "" for link in page.links]
    assert not any("fonts.googleapis.com" in h or "fonts.gstatic.com" in h for h in hrefs)


def test_self_hosted_fonts_exist_and_are_licensed():
    css = (SITE / "fonts.css").read_text()
    urls = re.findall(r"url\(\s*['\"]?([^'\")]+)['\"]?\s*\)", css)
    assert urls
    for u in urls:
        assert not re.match(r"(?:https?:)?//", u) and (SITE / u).is_file(), u
    families = set(re.findall(r"font-family:\s*['\"]([^'\"]+)['\"]", css))
    assert families == {"Bodoni Moda", "Geist", "Geist Mono"}
    assert len(list((SITE / "fonts").glob("OFL-*.txt"))) == 3
