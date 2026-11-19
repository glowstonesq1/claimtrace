#!/usr/bin/env python3
"""Build the self-hosted engine bundle for the try page (apps/site/try/pyodide/).

Everything the page runs is served from the site's own origin; nothing is fetched from a CDN at run
time. This script fetches the pinned files at BUILD time, checks each against
apps/site/try/bundle.lock.json (sha256), and writes:

  apps/site/try/pyodide/   Pyodide core (from the npm package), the Pyodide-built wheels ClaimTrace needs
                           (pydantic_core, lxml, ...), pure-Python wheels from PyPI, a ClaimTrace wheel built
                           from this checkout, a trimmed pyodide-lock.json and manifest.json (sizes for the
                           page's download progress).
  apps/site/try/samples/   The four sample documents from examples/documents.

Sources, in order of preference (all checked against the same sha256 in the lockfile):
  core       registry.npmjs.org  pyodide-<ver>.tgz (also checked against the npm sha512 integrity)
  pyodide    cdn.jsdelivr.net/pyodide/v<ver>/full/<wheel>, else the full distribution from the Pyodide
             GitHub release (one ~340 MB download, cached; only the needed wheels are extracted)
  pypi       pip download --only-binary=:all: --platform any, hash-checked (--require-hashes)

Usage:
  python scripts/build_try_bundle.py               build and verify (CI, Pages, `make try-bundle`)
  python scripts/build_try_bundle.py --write-lock  re-pin: resolve the versions below and rewrite the lockfile

The bundle is not committed (about 18 MB of binaries that would sit in git history for ever); CI and
the Pages workflow build it from the lockfile, so every deploy is byte-for-byte the pinned files plus
the ClaimTrace wheel of that commit.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRY = ROOT / "apps" / "site" / "try"
OUT = TRY / "pyodide"
SAMPLES_OUT = TRY / "samples"
LOCK = TRY / "bundle.lock.json"
CACHE = Path(os.environ.get("CLAIMTRACE_BUNDLE_CACHE") or Path.home() / ".cache" / "claimtrace-try-bundle")
SAMPLES = ("msa-v1.md", "amendment-1.md", "audit-report-2026.md", "delivery-record.md")

# --write-lock inputs. The Pyodide version is the latest on npm when re-pinned (`npm view pyodide version`).
PYODIDE_VERSION = "314.0.8"
CORE_FILES = ("pyodide.mjs", "pyodide.asm.mjs", "pyodide.asm.wasm", "python_stdlib.zip")
PYODIDE_PACKAGES = ("pydantic", "pydantic-core", "typing-extensions", "annotated-types", "typing-inspection", "lxml")
PYPI_PACKAGES = {"pypdf": ("7.1.1", ["pypdf"], []),
                 "python-docx": ("1.2.0", ["docx"], ["lxml", "typing-extensions"]),
                 "defusedxml": ("0.7.1", ["defusedxml"], [])}
# The ClaimTrace wheel holds only what the browser path imports (no api/cli/evaluation).
CLAIMTRACE_SUBPACKAGES = ("core", "ingestion", "extraction", "retrieval", "verification", "integrations", "browser")
CLAIMTRACE_DEPENDS = ["pydantic", "pypdf", "python-docx", "defusedxml"]


def log(msg: str) -> None:
    print(f"[try-bundle] {msg}", file=sys.stderr)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch(url: str, timeout: float = 600) -> bytes:
    if not url.startswith("https://"):
        raise ValueError(f"refusing non-https URL {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "claimtrace-bundle-builder"})  # noqa: S310 - https only
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - https only, checked above
        return r.read()


def cached(name: str, url: str) -> bytes:
    path = CACHE / name
    if path.exists():
        return path.read_bytes()
    log(f"fetch {url}")
    data = fetch(url)
    CACHE.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_bytes(data)
    tmp.replace(path)
    return data


# ---- sources -------------------------------------------------------------------------------------
def npm_tarball(version: str) -> bytes:
    return cached(f"pyodide-{version}.tgz", f"https://registry.npmjs.org/pyodide/-/pyodide-{version}.tgz")


def npm_members(tgz: bytes, names: tuple[str, ...]) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(tgz), mode="r:gz") as tf:
        for name in (*names, "pyodide-lock.json"):
            f = tf.extractfile(f"package/{name}")
            if f is None:
                raise SystemExit(f"{name} missing from the npm package")
            out[name] = f.read()
    return out


def pyodide_wheels(version: str, wanted: dict[str, str]) -> dict[str, bytes]:
    """file_name -> bytes for Pyodide-built wheels: per file from jsDelivr, else from the GitHub release."""
    got: dict[str, bytes] = {}
    for fn in wanted:
        if (CACHE / fn).exists():
            got[fn] = (CACHE / fn).read_bytes()
    missing = [fn for fn in wanted if fn not in got]
    try:
        for fn in missing:
            got[fn] = cached(fn, f"https://cdn.jsdelivr.net/pyodide/v{version}/full/{fn}")
    except OSError as e:
        log(f"jsDelivr unreachable ({type(e).__name__}); using the Pyodide release archive instead")
        rel = CACHE / f"pyodide-{version}.tar.bz2"
        if not rel.exists():
            cached(rel.name, f"https://github.com/pyodide/pyodide/releases/download/{version}/pyodide-{version}.tar.bz2")
        with tarfile.open(rel, mode="r:bz2") as tf:
            for member in tf:
                fn = member.name.rsplit("/", 1)[-1]
                if fn in wanted and fn not in got:
                    f = tf.extractfile(member)
                    assert f is not None
                    got[fn] = f.read()
                    (CACHE / fn).write_bytes(got[fn])
    lost = [fn for fn in wanted if fn not in got]
    if lost:
        raise SystemExit(f"could not obtain: {lost}")
    return got


def pypi_wheels(pins: dict[str, tuple[str, str]]) -> dict[str, bytes]:
    """name -> (version, sha256) pinned; returns file_name -> bytes via hash-checked pip download."""
    dest = CACHE / "pypi"
    dest.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as req:
        for name, (ver, digest) in pins.items():
            req.write(f"{name}=={ver} --hash=sha256:{digest}\n")
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "download", "--quiet", "--no-deps", "--only-binary=:all:", "--platform", "any",
             "--python-version", "3.14", "--implementation", "py", "--require-hashes", "-r", req.name, "-d", str(dest)],
            check=True,
        )
    finally:
        os.unlink(req.name)
    out: dict[str, bytes] = {}
    for name, (ver, _) in pins.items():
        stem = name.replace("-", "_")
        matches = [p for p in dest.glob(f"{stem}-{ver}-*.whl")]
        if len(matches) != 1:
            raise SystemExit(f"expected one wheel for {name}=={ver} in {dest}, found {matches}")
        out[matches[0].name] = matches[0].read_bytes()
    return out


def claimtrace_wheel() -> tuple[str, bytes, str]:
    """A reproducible py3-none-any wheel of this checkout's browser-path packages (fixed timestamps)."""
    sys.path.insert(0, str(ROOT))
    version = _version()
    files: list[tuple[str, bytes]] = []
    pkg = ROOT / "packages"
    files.append(("claimtrace/__init__.py", (pkg / "__init__.py").read_bytes()))
    for sub in CLAIMTRACE_SUBPACKAGES:
        for p in sorted((pkg / sub).rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts and p.suffix in (".py", ".sql"):
                files.append((f"claimtrace/{p.relative_to(pkg).as_posix()}", p.read_bytes()))
    di = f"claimtrace-{version}.dist-info"
    meta = "\n".join(["Metadata-Version: 2.1", "Name: claimtrace", f"Version: {version}",
                      "Summary: ClaimTrace engine, browser build (rules only, no server, no network)",
                      "License: Apache-2.0", *[f"Requires-Dist: {d}" for d in CLAIMTRACE_DEPENDS], ""]).encode()
    wheel = b"Wheel-Version: 1.0\nGenerator: claimtrace build_try_bundle\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
    files += [(f"{di}/METADATA", meta), (f"{di}/WHEEL", wheel), (f"{di}/top_level.txt", b"claimtrace\n")]
    record = []
    for name, data in files:
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
        record.append(f"{name},sha256={digest},{len(data)}")
    record.append(f"{di}/RECORD,,")
    files.append((f"{di}/RECORD", ("\n".join(record) + "\n").encode()))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, data)
    fn = f"claimtrace-{version}-py3-none-any.whl"
    return fn, buf.getvalue(), version


def _version() -> str:
    for line in (ROOT / "packages" / "__init__.py").read_text().splitlines():
        if line.startswith("__version__"):
            return line.split("=", 1)[1].strip().strip("\"'")
    raise SystemExit("no __version__ in packages/__init__.py")


# ---- lockfile ------------------------------------------------------------------------------------
def write_lock() -> None:
    v = PYODIDE_VERSION
    tgz = npm_tarball(v)
    meta = json.loads(fetch(f"https://registry.npmjs.org/pyodide/{v}"))
    integrity = meta["dist"]["integrity"]
    _check_integrity(tgz, integrity)
    core = npm_members(tgz, CORE_FILES)
    upstream = json.loads(core["pyodide-lock.json"])
    files: list[dict] = []
    for name in CORE_FILES:
        files.append({"file": name, "source": "npm", "sha256": sha256(core[name]), "size": len(core[name])})
    for name in PYODIDE_PACKAGES:
        e = upstream["packages"][name]
        files.append({"file": e["file_name"], "source": "pyodide", "package": e["name"], "version": e["version"],
                      "imports": e["imports"], "depends": e["depends"], "sha256": e["sha256"]})
    got = pyodide_wheels(v, {f["file"]: f["sha256"] for f in files if f["source"] == "pyodide"})
    for f in files:
        if f["source"] == "pyodide":
            f["size"] = len(got[f["file"]])
            if sha256(got[f["file"]]) != f["sha256"]:
                raise SystemExit(f"{f['file']}: sha256 does not match Pyodide's own lockfile")
    for name, (ver, imports, depends) in PYPI_PACKAGES.items():
        info = json.loads(fetch(f"https://pypi.org/pypi/{name}/{ver}/json"))
        whl = [u for u in info["urls"] if u["packagetype"] == "bdist_wheel" and u["filename"].endswith("-none-any.whl")]
        if len(whl) != 1:
            raise SystemExit(f"{name}=={ver}: expected one pure-Python wheel on PyPI")
        files.append({"file": whl[0]["filename"], "source": "pypi", "package": name, "version": ver, "imports": imports,
                      "depends": depends, "sha256": whl[0]["digests"]["sha256"], "size": whl[0]["size"]})
    lock = {
        "comment": "Every third-party file in the try page's engine bundle, pinned by sha256. Rebuild with "
                   "`make try-bundle`; re-pin with `python scripts/build_try_bundle.py --write-lock`. The ClaimTrace "
                   "wheel is built from the checkout and its hash is recorded in pyodide/manifest.json.",
        "pyodide": {"version": v, "npm_integrity": integrity, "python": upstream["info"]["python"],
                    "abi_version": upstream["info"]["abi_version"], "lock_info": upstream["info"]},
        "files": files,
    }
    LOCK.write_text(json.dumps(lock, indent=2) + "\n")
    log(f"wrote {LOCK.relative_to(ROOT)} ({len(files)} files)")


def _check_integrity(data: bytes, integrity: str) -> None:
    algo, b64 = integrity.split("-", 1)
    if base64.b64encode(hashlib.new(algo, data).digest()).decode() != b64:
        raise SystemExit("npm tarball does not match its registry integrity")


# ---- build ---------------------------------------------------------------------------------------
def build() -> None:
    lock = json.loads(LOCK.read_text())
    v = lock["pyodide"]["version"]
    tgz = npm_tarball(v)
    _check_integrity(tgz, lock["pyodide"]["npm_integrity"])
    entries = lock["files"]
    core = npm_members(tgz, tuple(f["file"] for f in entries if f["source"] == "npm"))
    blobs: dict[str, bytes] = {f["file"]: core[f["file"]] for f in entries if f["source"] == "npm"}
    blobs.update(pyodide_wheels(v, {f["file"]: f["sha256"] for f in entries if f["source"] == "pyodide"}))
    blobs.update(pypi_wheels({f["package"]: (f["version"], f["sha256"]) for f in entries if f["source"] == "pypi"}))
    for f in entries:
        actual = sha256(blobs[f["file"]])
        if actual != f["sha256"]:
            raise SystemExit(f"{f['file']}: sha256 {actual} does not match the lockfile ({f['sha256']})")
    ct_name, ct_data, ct_version = claimtrace_wheel()
    blobs[ct_name] = ct_data

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    for name, data in blobs.items():
        (OUT / name).write_bytes(data)

    packages: dict[str, dict] = {}
    for f in entries:
        if f["source"] == "npm":
            continue
        key = f["package"].lower().replace("_", "-")
        packages[key] = {"name": f["package"], "version": f["version"], "file_name": f["file"], "install_dir": "site",
                         "sha256": f["sha256"], "package_type": "package", "imports": f["imports"],
                         "depends": f["depends"], "unvendored_tests": False, "tool": {}}
    packages["claimtrace"] = {"name": "claimtrace", "version": ct_version, "file_name": ct_name, "install_dir": "site",
                              "sha256": sha256(ct_data), "package_type": "package", "imports": ["claimtrace"],
                              "depends": CLAIMTRACE_DEPENDS, "unvendored_tests": False, "tool": {}}
    plock = {"info": lock["pyodide"]["lock_info"], "packages": packages}
    plock_bytes = (json.dumps(plock, indent=1, sort_keys=True) + "\n").encode()
    (OUT / "pyodide-lock.json").write_bytes(plock_bytes)

    files = [{"file": n, "size": len(d), "sha256": sha256(d)} for n, d in sorted(blobs.items())]
    files.append({"file": "pyodide-lock.json", "size": len(plock_bytes), "sha256": sha256(plock_bytes)})
    manifest = {"pyodide": v, "python": lock["pyodide"]["python"], "claimtrace": ct_version,
                "total_bytes": sum(f["size"] for f in files), "files": files, "load": ["claimtrace"]}
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")

    if SAMPLES_OUT.exists():
        shutil.rmtree(SAMPLES_OUT)
    SAMPLES_OUT.mkdir()
    for name in SAMPLES:
        shutil.copyfile(ROOT / "examples" / "documents" / name, SAMPLES_OUT / name)
    (SAMPLES_OUT / "index.json").write_text(json.dumps(list(SAMPLES)) + "\n")
    log(f"built {OUT.relative_to(ROOT)}: {len(files)} files, {manifest['total_bytes'] / 1e6:.1f} MB")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--write-lock", action="store_true", help="re-pin the third-party files and rewrite the lockfile")
    args = ap.parse_args()
    if args.write_lock:
        write_lock()
    build()
    return 0


if __name__ == "__main__":
    sys.exit(main())
