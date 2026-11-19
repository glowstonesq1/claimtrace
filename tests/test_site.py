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
    assert [s["src"] for s in gsap] == ["vendor/gsap/gsap.min.js"]  # ScrollTrigger was never used
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
    assert families == {"Instrument Sans", "Figtree", "JetBrains Mono"}
    licences = {p.name for p in (SITE / "fonts").glob("OFL-*.txt")}
    assert licences == {"OFL-instrument-sans.txt", "OFL-figtree.txt", "OFL-jetbrains-mono.txt"}
    for name in licences:
        assert "SIL Open Font License" in (SITE / "fonts" / name).read_text(encoding="utf-8"), name
    # every woff2 on disk is used, and both subsets of each face are present
    files = {p.name for p in (SITE / "fonts").glob("*.woff2")}
    assert files == {u.split("/")[-1] for u in urls}
    assert all(f.replace("-latin-", "-latin-ext-") in files for f in files if "-latin-ext-" not in f)


def test_old_fonts_are_gone_everywhere() -> None:
    """v0.4 dropped Bodoni Moda and Geist: no file, preload or font-family may still name them."""
    assert not list((SITE / "fonts").glob("bodoni*")) and not list((SITE / "fonts").glob("geist*"))
    for p in SITE.rglob("*"):
        if p.suffix in (".html", ".css", ".js", ".mjs") and "pyodide" not in p.parts and "vendor" not in p.parts:
            text = p.read_text(encoding="utf-8").lower()
            assert "bodoni" not in text and "geist" not in text, p.relative_to(SITE)


def test_every_page_preloads_fonts_that_exist() -> None:
    for page in [SITE / "index.html", *sorted(SITE.glob("*/index.html"))]:
        for href in re.findall(r'<link rel="preload" href="([^"]+)" as="font"', page.read_text(encoding="utf-8")):
            assert (page.parent / href).resolve().is_file(), (page.relative_to(SITE), href)


def _plugin_zip_text(text: str) -> str:
    """The part of a page or doc that describes claimtrace-plugin.zip: the paragraph that names it."""
    paras = [p for p in re.split(r"\n\s*\n|</p>", text) if "claimtrace-plugin.zip" in p and "plugin-dir" in p]
    assert paras, "no paragraph describes claimtrace-plugin.zip"
    return re.sub(r"\s+", " ", " ".join(re.sub(r"<[^>]+>", "", p) for p in paras))


def test_plugin_zip_requirements_are_stated_from_one_source() -> None:
    """The zip bundles the engine and its pure-Python wheels, not the compiled packages; the get page and
    docs/claude.md must say so, using the list scripts/build_skill_zip.py builds the zip's manifest from."""
    import importlib.util

    root = SITE.parents[1]
    spec = importlib.util.spec_from_file_location("build_skill_zip", root / "scripts" / "build_skill_zip.py")
    assert spec and spec.loader
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    for source in (SITE / "get" / "index.html", root / "docs" / "claude.md"):
        text = _plugin_zip_text(source.read_text(encoding="utf-8"))
        assert "no install at all" not in text.lower(), f"{source.name}: false 'no install' claim"
        for name in builder.NOT_BUNDLED:
            assert name in text, f"{source.name}: does not say {name} must already be installed"
        for name in builder.PURE_WHEELS:
            assert name in text, f"{source.name}: does not say the zip bundles {name}"
        assert "exit code 3" in text or "exits with code 3" in text, f"{source.name}: missing-dependency behaviour"
        assert "install --yes" in text or "asks" in text, f"{source.name}: the install path is not described"


def test_no_scored_once_claims() -> None:
    """docs/evaluation.md records that both sealed sets were re-scored after the review fixes (v2-postfix, identical
    numbers) and that the holdout was also scored at v0.1, so "scored once" is false wherever it appears."""
    root = SITE.parents[1]
    files = [root / "README.md", *sorted((root / "docs").glob("*.md")), root / "scripts" / "build_site_data.py",
             *[p for p in SITE.rglob("*") if p.suffix in (".html", ".js", ".json") and "pyodide" not in p.parts
               and "vendor" not in p.parts]]
    claim = re.compile(r"(?<!re-)scored\s+(?:exactly\s+)?once|\bone\s+scoring\b|\bonly\s+scored\s+once", re.I)
    found = [f"{p.relative_to(root)}: {m.group(0)}" for p in files for m in claim.finditer(p.read_text(encoding="utf-8"))]
    assert not found, found


def test_home_limits_say_scans_need_the_ocr_extra_and_the_browser_flags_them() -> None:
    page = (SITE / "index.html").read_text(encoding="utf-8")
    limits = page.split('<div class="limits">')[1].split("</dl>")[0]
    row = next(r for r in re.findall(r'<div class="row[^"]*">(.*?)</div>', limits) if "scanned" in r.lower())
    text = re.sub(r"<[^>]+>", " ", row)
    assert "OCR extra" in text and "self-host" in text.lower(), text
    assert "browser" in text.lower() and "flag" in text.lower(), text


def test_unused_scripts_are_gone() -> None:
    """slots.js (image slots) and ScrollTrigger had no users: neither is on disk or loaded by any page."""
    assert not (SITE / "slots.js").exists() and not (SITE / "vendor" / "gsap" / "ScrollTrigger.min.js").exists()
    for p in SITE.rglob("*.html"):
        if "pyodide" not in p.parts:
            text = p.read_text(encoding="utf-8")
            assert "slots.js" not in text and "ScrollTrigger" not in text, p.relative_to(SITE)


def test_og_image_alt_describes_the_film_poster() -> None:
    """Pages that share the film poster describe it with the same words as the film's fallback image."""
    home = (SITE / "index.html").read_text(encoding="utf-8")
    poster_alt = re.search(r'<img class="film__fallback"[^>]*?\s(?:data-)?alt="([^"]+)"', home, re.S)
    assert poster_alt, "the film fallback image needs its alt text in the markup"
    pages = 0
    for page in [SITE / "index.html", *sorted(SITE.glob("*/index.html"))]:
        text = page.read_text(encoding="utf-8")
        if "claimtrace-film-poster.jpg" in (re.search(r'og:image" content="([^"]+)"', text) or [""])[0]:
            pages += 1
            alt = re.search(r'og:image:alt" content="([^"]+)"', text)
            assert alt and alt.group(1) == poster_alt.group(1), page.relative_to(SITE)
    assert pages >= 3


def test_film_fallback_is_hidden_until_the_film_is_missing() -> None:
    """The poster image sits behind a working video, so it has no alt and is aria-hidden; site.js gives it its
    description back (and unhides it) when the frame is marked .is-missing."""
    home = (SITE / "index.html").read_text(encoding="utf-8")
    img = re.search(r'<img class="film__fallback"[^>]*>', home, re.S)
    assert img
    tag = img.group(0)
    assert re.search(r'\salt=""', tag) and 'aria-hidden="true"' in tag and re.search(r'data-alt="[^"]{20,}"', tag)
    script = (SITE / "site.js").read_text(encoding="utf-8")
    missing = script.split("var missing = function () {")[1].split("};")[0]
    assert "dataset.alt" in missing and "removeAttribute('aria-hidden')" in missing


def test_command_code_is_not_shrunk_below_14px() -> None:
    """.cmd pre is set at --text-xs (0.875rem = 14px); code inside a pre must inherit that size, not take the
    0.9em that inline code gets (which made /get's commands 12.6px)."""
    base = (SITE / "base.css").read_text(encoding="utf-8")
    chrome = (SITE / "chrome.css").read_text(encoding="utf-8")
    tokens = (SITE / "tokens.css").read_text(encoding="utf-8")
    assert re.search(r"--text-xs:\s*0\.875rem", tokens)
    assert re.search(r"\.cmd pre \{[^}]*font: 400 var\(--text-xs\)", chrome)
    assert re.search(r"(?m)^pre code \{[^}]*font-size: inherit;", base)
