#!/usr/bin/env python3
"""Build the ClaimTrace Claude.ai skill zip (and a Claude Code plugin zip) from this repository.

    python scripts/build_skill_zip.py                 # dist/claimtrace-skill.zip and dist/claimtrace-plugin.zip
    python scripts/build_skill_zip.py --wheel-dir W   # use already downloaded wheels (offline)
    python scripts/build_skill_zip.py --vendor-in-place   # also write vendor/ into the plugin's skill dir (gitignored)

What goes in (nothing is hand-copied):
- plugins/claimtrace/skills/claimtrace/ (SKILL.md, scripts/)
- vendor/src/claimtrace/: the engine subpackages, taken from pyproject.toml's setuptools package-dir mapping and
  package-data (packages/ -> claimtrace). The CLI, the evaluation runner and the web API are left out: the skill
  never starts a server and must not import fastapi, uvicorn or httpx.
- vendor/wheels/: pure-Python runtime dependencies (pypdf, python-docx, defusedxml), at the versions pinned in
  requirements.lock, checked against the lockfile's sha256 hashes. Compiled dependencies (pydantic_core, lxml)
  are not bundled; the runner checks for them at start-up.
- vendor/MANIFEST.json: versions, hashes and the git commit the engine came from.

The zip is deterministic: sorted entries, fixed timestamps (SOURCE_DATE_EPOCH, else 1980-01-01).
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "plugins" / "claimtrace"
SKILL = PLUGIN / "skills" / "claimtrace"
SKILL_NAME = "claimtrace"
# subpackages the skill needs (import closure of ingestion + extraction + verification)
EXCLUDE_PACKAGES = {"claimtrace.cli", "claimtrace.evaluation", "claimtrace.api"}
PURE_WHEELS = ["pypdf", "python-docx", "defusedxml"]
ZIP_LIMIT_BYTES = 8 * 1024 * 1024  # stay well under claude.ai's upload limit


def engine_files() -> dict[str, Path]:
    """{'claimtrace/core/store.py': Path(...), ...} from pyproject's setuptools mapping."""
    cfg = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["setuptools"]
    package_dir: dict[str, str] = cfg["package-dir"]
    package_data: dict[str, list[str]] = cfg.get("package-data", {})
    out: dict[str, Path] = {}
    for pkg in cfg["packages"]:
        if pkg in EXCLUDE_PACKAGES:
            continue
        # longest matching prefix in package-dir, as setuptools does
        prefix = max((p for p in package_dir if pkg == p or pkg.startswith(p + ".")), key=len)
        src = ROOT / package_dir[prefix] / Path(*pkg[len(prefix):].lstrip(".").split(".")) if pkg != prefix \
            else ROOT / package_dir[prefix]
        dest = Path(*pkg.split("."))
        for f in sorted(src.glob("*.py")):
            out[(dest / f.name).as_posix()] = f
        for pattern in package_data.get(pkg, []):
            for f in sorted(src.glob(pattern)):
                if f.is_file():
                    out[(dest / f.relative_to(src)).as_posix()] = f
    if "claimtrace/__init__.py" not in out:
        raise SystemExit("pyproject.toml mapping did not yield claimtrace/__init__.py")
    return out


def lock_pins() -> dict[str, tuple[str, set[str]]]:
    """{name: (version, {sha256, ...})} from requirements.lock."""
    text = (ROOT / "requirements.lock").read_text(encoding="utf-8")
    pins: dict[str, tuple[str, set[str]]] = {}
    for m in re.finditer(r"^([A-Za-z0-9_.\-]+)==([^\s\\]+)((?:\s*\\\n\s*--hash=sha256:[0-9a-f]+)+)", text, re.M):
        pins[m.group(1).lower().replace("_", "-")] = (m.group(2), set(re.findall(r"sha256:([0-9a-f]+)", m.group(3))))
    return pins


def get_wheels(wheel_dir: Path | None, cache: Path) -> list[Path]:
    pins = lock_pins()
    wanted = {n: pins[n] for n in PURE_WHEELS}
    src = wheel_dir or cache
    src.mkdir(parents=True, exist_ok=True)

    def find(name: str, version: str) -> Path | None:
        stem = name.replace("-", "_").lower()
        hits = [w for w in src.glob("*.whl") if w.name.lower().startswith(f"{stem}-{version}-") and "-none-any" in w.name]
        return hits[0] if hits else None

    missing = [f"{n}=={v}" for n, (v, _) in wanted.items() if find(n, v) is None]
    if missing:
        if wheel_dir:
            raise SystemExit(f"missing wheels in {wheel_dir}: {', '.join(missing)}")
        subprocess.run([sys.executable, "-m", "pip", "download", "--quiet", "--no-deps", "--only-binary=:all:",
                        "--dest", str(cache), *missing], check=True)
    wheels = []
    for n, (v, hashes) in wanted.items():
        w = find(n, v)
        if w is None:
            raise SystemExit(f"could not get a pure-Python wheel for {n}=={v}")
        digest = hashlib.sha256(w.read_bytes()).hexdigest()
        if digest not in hashes:
            raise SystemExit(f"{w.name}: sha256 {digest} is not in requirements.lock")
        wheels.append(w)
    return wheels


def git_commit() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,  # noqa: S607
                              text=True, check=True).stdout.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


def skill_tree(wheels: list[Path]) -> dict[str, bytes]:
    """Relative path inside the skill folder -> bytes."""
    files: dict[str, bytes] = {}
    for f in sorted(SKILL.rglob("*")):
        rel = f.relative_to(SKILL).as_posix()
        if f.is_file() and not rel.startswith("vendor/") and "__pycache__" not in rel and not f.name.endswith(".pyc"):
            files[rel] = f.read_bytes()
    engine = engine_files()
    for rel, src in engine.items():
        files[f"vendor/src/{rel}"] = src.read_bytes()
    for w in wheels:
        files[f"vendor/wheels/{w.name}"] = w.read_bytes()
    files["LICENSE.txt"] = (ROOT / "LICENSE").read_bytes()
    if (ROOT / "NOTICE.md").is_file():
        files["NOTICE.md"] = (ROOT / "NOTICE.md").read_bytes()
    version = re.search(r'__version__\s*=\s*"([^"]+)"', (ROOT / "packages" / "__init__.py").read_text()).group(1)  # type: ignore[union-attr]
    manifest = {
        "engine": {"name": "claimtrace", "version": version, "git_commit": git_commit(),
                   "files": {rel: hashlib.sha256(src.read_bytes()).hexdigest() for rel, src in engine.items()}},
        "wheels": {w.name: hashlib.sha256(w.read_bytes()).hexdigest() for w in wheels},
        "not_bundled": {"pydantic (+ pydantic_core)": "compiled; expected preinstalled",
                        "lxml": "compiled; needed for .docx only; expected preinstalled"},
    }
    files["vendor/MANIFEST.json"] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    return files


def write_zip(path: Path, entries: dict[str, bytes]) -> None:
    epoch = int(os.environ.get("SOURCE_DATE_EPOCH", "315532800"))
    stamp = time.gmtime(max(epoch, 315532800))[:6]
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name in sorted(entries):
            info = zipfile.ZipInfo(name, date_time=stamp)  # type: ignore[arg-type]
            info.compress_type = zipfile.ZIP_DEFLATED
            mode = 0o755 if name.endswith(".py") and "/scripts/" in f"/{name}" else 0o644
            info.external_attr = (0o100000 | mode) << 16
            z.writestr(info, entries[name])
    path.write_bytes(buf.getvalue())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-dir", default=str(ROOT / "dist"))
    ap.add_argument("--wheel-dir", help="directory with the pinned wheels already downloaded (no network)")
    ap.add_argument("--wheel-cache", default=str(ROOT / "dist" / ".wheel-cache"),
                    help="where downloaded wheels are kept between builds (default: dist/.wheel-cache)")
    ap.add_argument("--vendor-in-place", action="store_true",
                    help="also write vendor/ into plugins/claimtrace/skills/claimtrace (gitignored), for --plugin-dir use")
    ap.add_argument("--no-plugin-zip", action="store_true")
    args = ap.parse_args(argv)
    out = Path(args.out_dir)
    wheels = get_wheels(Path(args.wheel_dir) if args.wheel_dir else None, Path(args.wheel_cache))
    tree = skill_tree(wheels)

    skill_zip = out / "claimtrace-skill.zip"  # claude.ai: one top-level folder holding SKILL.md
    write_zip(skill_zip, {f"{SKILL_NAME}/{k}": v for k, v in tree.items()})
    size = skill_zip.stat().st_size
    if size > ZIP_LIMIT_BYTES:
        raise SystemExit(f"{skill_zip} is {size} bytes, over the {ZIP_LIMIT_BYTES} byte budget")
    print(f"{skill_zip.relative_to(ROOT) if skill_zip.is_relative_to(ROOT) else skill_zip}: {size} bytes, "
          f"{len(tree)} files")

    if not args.no_plugin_zip:  # Claude Code: `claude --plugin-dir claimtrace-plugin.zip`, engine included
        plugin: dict[str, bytes] = {}
        for f in sorted(PLUGIN.rglob("*")):
            rel = f.relative_to(PLUGIN).as_posix()
            if f.is_file() and not rel.startswith("skills/") and "__pycache__" not in rel:
                plugin[rel] = f.read_bytes()
        plugin.update({f"skills/{SKILL_NAME}/{k}": v for k, v in tree.items()})
        plugin_zip = out / "claimtrace-plugin.zip"
        write_zip(plugin_zip, plugin)
        print(f"{plugin_zip.name}: {plugin_zip.stat().st_size} bytes, {len(plugin)} files")

    if args.vendor_in_place:
        vendor = SKILL / "vendor"
        shutil.rmtree(vendor, ignore_errors=True)
        with tempfile.TemporaryDirectory() as tmp:
            for rel, data in tree.items():
                if rel.startswith("vendor/"):
                    p = Path(tmp) / rel
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_bytes(data)
            shutil.copytree(Path(tmp) / "vendor", vendor)
        print(f"wrote {vendor.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
