"""Tests for the static-site helpers: partial injection (idempotent) and the internal link checker."""

from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


inject_partials = _load("inject_partials")
check_links = _load("check_links")

NAV = '<header><a href="{{root}}">Home</a> <a href="{{root}}try/" data-nav="try">Try</a>' \
      ' <a href="{{root}}get/" data-nav="get">Get</a></header>\n'
FOOT = '<footer><a href="{{root}}docs/">Docs</a></footer>\n'
PAGE = "<!doctype html><body>\n<!-- nav --><!-- /nav -->\n<main id=\"main\">{body}</main>\n<!-- footer -->\n</body>"


@pytest.fixture
def site(tmp_path: Path) -> Path:
    (tmp_path / "partials").mkdir()
    (tmp_path / "partials" / "nav.html").write_text(NAV)
    (tmp_path / "partials" / "footer.html").write_text(FOOT)
    (tmp_path / "index.html").write_text(PAGE.format(body='<a href="get/#claude">Claude</a>'))
    (tmp_path / "get").mkdir()
    (tmp_path / "get" / "index.html").write_text(PAGE.format(body='<h2 id="claude">Claude</h2>'))
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "index.html").write_text(PAGE.format(body="docs"))
    (tmp_path / "404.html").write_text(PAGE.format(body="missing"))
    (tmp_path / "plain.html").write_text("<p>no markers</p>")
    return tmp_path


def test_inject_fills_markers_with_relative_roots_and_current_page(site: Path) -> None:
    assert inject_partials.main(["--site", str(site)]) == 0
    home = (site / "index.html").read_text()
    get = (site / "get" / "index.html").read_text()
    missing = (site / "404.html").read_text()
    assert '<a href="./try/" data-nav="try">' in home
    assert '<a href="../get/" data-nav="get" aria-current="page">' in get
    assert 'aria-current' not in home
    assert '<a href="/claimtrace/docs/">' in missing
    assert get.count("<!-- /nav -->") == 1 and get.count("<!-- /footer -->") == 1
    assert (site / "plain.html").read_text() == "<p>no markers</p>"


def test_inject_is_idempotent_and_check_mode_detects_drift(site: Path) -> None:
    inject_partials.main(["--site", str(site)])
    first = {p: p.read_text() for p in site.rglob("*.html")}
    assert inject_partials.main(["--site", str(site), "--check"]) == 0
    inject_partials.main(["--site", str(site)])
    assert {p: p.read_text() for p in site.rglob("*.html")} == first

    (site / "partials" / "footer.html").write_text("<footer>changed</footer>\n")
    assert inject_partials.main(["--site", str(site), "--check"]) == 1
    assert (site / "index.html").read_text() == first[site / "index.html"]  # --check writes nothing


def test_link_checker_passes_a_good_site_and_skips_absent_optional_folders(site: Path) -> None:
    inject_partials.main(["--site", str(site)])
    # try/ does not exist yet: links to it are skipped, everything else resolves
    assert check_links.check(site, {"try", "evidence"}) == []


def test_link_checker_reports_missing_files_fragments_and_present_optional_folders(site: Path) -> None:
    inject_partials.main(["--site", str(site)])
    (site / "docs" / "index.html").write_text(
        '<a href="../nope.html">x</a><a href="../get/#absent">y</a><img src="../img/missing.png">'
        '<a href="https://example.com/">external</a><a href="#main">self</a>'
    )
    (site / "try").mkdir()  # once the folder exists, its index must too
    errors = check_links.check(site, {"try", "evidence"})
    joined = "\n".join(errors)
    assert "missing nope.html" in joined
    assert "no id 'absent' in get/index.html" in joined
    assert "missing img/missing.png" in joined
    assert "example.com" not in joined
    assert "missing try/index.html" in joined
    assert "no id 'main' in docs/index.html" in joined


def test_link_checker_maps_public_urls_and_checks_the_sitemap(site: Path) -> None:
    (site / "sitemap.xml").write_text(
        "<urlset><url><loc>https://glowstonesq1.github.io/claimtrace/get/</loc></url>"
        "<url><loc>https://glowstonesq1.github.io/claimtrace/gone/</loc></url></urlset>"
    )
    (site / "get" / "index.html").write_text(
        '<link rel="canonical" href="https://glowstonesq1.github.io/claimtrace/get/">'
        '<meta property="og:image" content="https://glowstonesq1.github.io/claimtrace/media/x.jpg">'
    )
    errors = "\n".join(check_links.check(site, set()))
    assert "sitemap.xml" in errors and "gone/index.html" in errors
    assert "media/x.jpg" in errors
    assert "get/index.html: https://glowstonesq1.github.io/claimtrace/get/" not in errors


def test_the_real_site_links_resolve_after_injection(tmp_path: Path) -> None:
    """What the Pages workflow does: inject the partials, then check every internal link."""
    site = tmp_path / "site"
    shutil.copytree(ROOT / "apps" / "site", site, ignore=shutil.ignore_patterns("*.mp4", ".hallmark"))
    (site / "media" / "claimtrace-film.mp4").write_bytes(b"")
    assert inject_partials.main(["--site", str(site)]) == 0
    assert inject_partials.main(["--site", str(site), "--check"]) == 0
    assert check_links.check(site, {"try", "evidence"}) == []


# ------------------------------------------------------------------------------------------- workflows

WORKFLOWS = ROOT / ".github" / "workflows"


def test_only_release_workflow_uploads_release_assets() -> None:
    """ci.yml (on release) and release.yml (on tags) both uploaded the zips with --clobber and raced."""
    assert "gh release upload" not in (WORKFLOWS / "ci.yml").read_text()
    assert "gh release upload" in (WORKFLOWS / "release.yml").read_text()


def test_pages_rebuilds_when_its_inputs_change() -> None:
    text = (WORKFLOWS / "pages.yml").read_text()
    paths = text.split("paths:", 1)[1].split("workflow_dispatch", 1)[0]
    for needed in ('"examples/documents/**"', '"pyproject.toml"'):
        assert needed in paths, f"pages.yml path filter misses {needed}"


def test_pages_checks_links_after_building_the_try_bundle() -> None:
    text = (WORKFLOWS / "pages.yml").read_text()
    assert text.index("run: python scripts/build_try_bundle.py") < text.index("run: python scripts/check_links.py")


def test_check_links_follows_json_manifests_fetched_by_scripts(tmp_path: Path) -> None:
    site = tmp_path / "site"
    (site / "try" / "samples").mkdir(parents=True)
    (site / "try" / "index.html").write_text('<script type="module" src="try.js"></script>')
    (site / "try" / "try.js").write_text("const names = await (await fetch('samples/index.json')).json();\n"
                                         "await fetch('missing.json');\n")
    (site / "try" / "samples" / "index.json").write_text('["a.md", "gone.md"]')
    (site / "try" / "samples" / "a.md").write_text("# A")
    errors = "\n".join(check_links.check(site, set(), require_built=True))
    assert "gone.md" in errors and "a.md -> " not in errors
    assert "missing.json" in errors
