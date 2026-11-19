#!/usr/bin/env python3
"""Check that every internal link in the static site resolves to a file (and an id, for #fragments).

Covers href/src/poster/srcset in every page, absolute URLs on the published origin (canonical, og:image),
and the <loc> entries in sitemap.xml. External links are not fetched. Targets under a top-level folder
listed in --optional (default: try, evidence) are skipped while that folder does not exist yet, because
other workstreams build those pages; once the folder exists its links are checked like any other.
Exits 1 and lists each broken link.
"""

from __future__ import annotations

import argparse
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

DEFAULT_SITE = Path(__file__).resolve().parent.parent / "apps" / "site"
PUBLIC_ORIGIN = "https://glowstonesq1.github.io/claimtrace/"
BASE_PATH = "/claimtrace/"
SKIP_DIRS = {"partials", ".hallmark", "node_modules"}
URL_ATTRS = {"href", "src", "poster"}


class Collector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.urls: list[tuple[int, str]] = []
        self.ids: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        line = self.getpos()[0]
        a = {k: v for k, v in attrs if v is not None}
        if "id" in a:
            self.ids.add(a["id"])
        if tag == "a" and "name" in a:
            self.ids.add(a["name"])
        for key in URL_ATTRS & a.keys():
            self.urls.append((line, a[key]))
        if "srcset" in a:
            for part in a["srcset"].split(","):
                if part.strip():
                    self.urls.append((line, part.strip().split()[0]))
        if tag == "meta" and a.get("property", a.get("name", "")) in {"og:image", "og:url", "twitter:image"}:
            self.urls.append((line, a.get("content", "")))


def parse(path: Path) -> Collector:
    c = Collector()
    c.feed(path.read_text(encoding="utf-8"))
    return c


def resolve(site: Path, page: Path, url: str) -> tuple[Path | None, str]:
    """Map a URL found on `page` to a file in `site` (None when external) and its fragment."""
    if url.startswith(PUBLIC_ORIGIN):
        url = BASE_PATH + url[len(PUBLIC_ORIGIN):]
    parts = urlsplit(url)
    if parts.scheme or parts.netloc or url.startswith(("mailto:", "tel:", "data:", "javascript:")):
        return None, ""
    path = unquote(parts.path)
    if not path:
        target = page
    elif path.startswith(BASE_PATH):
        target = site / path[len(BASE_PATH):]
    elif path.startswith("/"):
        target = site / path.lstrip("/")
    else:
        target = page.parent / path
    if path.endswith("/") or target.is_dir():
        target = target / "index.html"
    return target.resolve(), parts.fragment


def check(site: Path, optional: set[str]) -> list[str]:
    site = site.resolve()
    errors: list[str] = []
    cache: dict[Path, Collector] = {}

    def ids_of(p: Path) -> set[str]:
        if p not in cache:
            cache[p] = parse(p)
        return cache[p].ids

    def verify(origin: str, page: Path, url: str) -> None:
        target, frag = resolve(site, page, url)
        if target is None:
            return
        try:
            rel = target.relative_to(site)
        except ValueError:
            errors.append(f"{origin}: {url} points outside the site")
            return
        top = rel.parts[0] if len(rel.parts) > 1 else ""
        if top in optional and not (site / top).is_dir():
            return
        if not target.is_file():
            errors.append(f"{origin}: {url} -> missing {rel.as_posix()}")
            return
        if frag and target.suffix == ".html" and frag not in ids_of(target):
            errors.append(f"{origin}: {url} -> no id '{frag}' in {rel.as_posix()}")

    for page in sorted(site.rglob("*.html")):
        rel = page.relative_to(site)
        if any(p in SKIP_DIRS for p in rel.parts[:-1]):
            continue
        collected = cache.setdefault(page.resolve(), parse(page))
        for line, url in collected.urls:
            verify(f"{rel.as_posix()}:{line}", page.resolve(), url.strip())

    sitemap = site / "sitemap.xml"
    if sitemap.is_file():
        for loc in re.findall(r"<loc>\s*([^<]+?)\s*</loc>", sitemap.read_text(encoding="utf-8")):
            if not loc.startswith(PUBLIC_ORIGIN):
                errors.append(f"sitemap.xml: {loc} is not on {PUBLIC_ORIGIN}")
            else:
                verify("sitemap.xml", (site / "index.html").resolve(), loc)
    return errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--site", type=Path, default=DEFAULT_SITE)
    ap.add_argument("--optional", default="try,evidence", help="top-level folders skipped while absent")
    args = ap.parse_args(argv)
    errors = check(args.site, {s for s in args.optional.split(",") if s})
    for e in errors:
        print(e)
    print(f"links: {len(errors)} broken" if errors else "links: every internal link resolves")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
