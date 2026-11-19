#!/usr/bin/env python3
"""Inject the shared nav and footer into every page of the static site (no build step needed).

How a page opts in: put the two marker comments where the chrome belongs.

    <body>
    <!-- nav --><!-- /nav -->
    <main id="main"> ... </main>
    <!-- footer --><!-- /footer -->

Everything between a marker and its closing marker is replaced with apps/site/partials/nav.html or
footer.html, so running this twice changes nothing (idempotent). A lone opening marker (no closing one)
is also accepted and gets the closing marker added. In the partials:

- ``{{root}}`` becomes the relative path back to the site root ("./" at the top, "../" one folder down),
  so links work on GitHub Pages under /claimtrace/ and on ``python -m http.server`` alike. 404.html is
  served at any depth, so it gets the absolute base path (``--base-path``, default /claimtrace/).
- the nav link whose ``data-nav`` matches the page's top folder (try, evidence, get, docs) gets
  ``aria-current="page"``.

The page must also contain ``<main id="main">`` for the skip link. Pages without markers are listed and
left alone. The Pages workflow runs this before upload; ``--check`` exits 1 if any page is out of date.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

DEFAULT_SITE = Path(__file__).resolve().parent.parent / "apps" / "site"
SKIP_DIRS = {"partials", "vendor", ".hallmark", "node_modules"}
ABSOLUTE_ROOT_PAGES = {"404.html"}
PARTS = ("nav", "footer")


def site_pages(site: Path) -> list[Path]:
    pages = []
    for path in sorted(site.rglob("*.html")):
        rel = path.relative_to(site)
        if any(part in SKIP_DIRS for part in rel.parts[:-1]):
            continue
        pages.append(path)
    return pages


def root_for(rel: Path, base_path: str) -> str:
    if rel.as_posix() in ABSOLUTE_ROOT_PAGES:
        return base_path
    depth = len(rel.parts) - 1
    return "./" if depth == 0 else "../" * depth


def section_for(rel: Path) -> str | None:
    return rel.parts[0] if len(rel.parts) > 1 else None


def render(template: str, root: str, section: str | None) -> str:
    out = template.strip("\n").replace("{{root}}", root)
    if section:
        out = re.sub(
            rf'(<a\b[^>]*\bdata-nav="{re.escape(section)}")',
            r'\1 aria-current="page"',
            out,
            count=1,
        )
    return out


def inject(html: str, partials: dict[str, str], root: str, section: str | None) -> tuple[str, list[str]]:
    """Return the page with each marked region filled, and the names of the markers found."""
    found = []
    for name in PARTS:
        block = render(partials[name], root, section)
        filled = f"<!-- {name} -->\n{block}\n<!-- /{name} -->"
        paired = re.compile(rf"<!-- {name} -->.*?<!-- /{name} -->", re.S)
        if paired.search(html):
            html = paired.sub(lambda _m, f=filled: f, html, count=1)
            found.append(name)
            continue
        lone = re.compile(rf"<!-- {name} -->")
        if lone.search(html):
            html = lone.sub(lambda _m, f=filled: f, html, count=1)
            found.append(name)
    return html, found


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--site", type=Path, default=DEFAULT_SITE)
    ap.add_argument("--base-path", default="/claimtrace/", help="absolute site root, used for 404.html")
    ap.add_argument("--check", action="store_true", help="change nothing; exit 1 if a page is out of date")
    args = ap.parse_args(argv)

    site: Path = args.site
    partials = {name: (site / "partials" / f"{name}.html").read_text(encoding="utf-8") for name in PARTS}
    stale, unmarked = [], []
    for page in site_pages(site):
        rel = page.relative_to(site)
        before = page.read_text(encoding="utf-8")
        after, found = inject(before, partials, root_for(rel, args.base_path), section_for(rel))
        if not found:
            unmarked.append(rel.as_posix())
            continue
        if after != before:
            stale.append(rel.as_posix())
            if not args.check:
                page.write_text(after, encoding="utf-8")
    for rel in unmarked:
        print(f"no <!-- nav --> or <!-- footer --> marker, left alone: {rel}")
    verb = "out of date" if args.check else "updated"
    for rel in stale:
        print(f"{verb}: {rel}")
    if not stale:
        print("partials: every marked page is up to date")
    return 1 if (args.check and stale) else 0


if __name__ == "__main__":
    sys.exit(main())
