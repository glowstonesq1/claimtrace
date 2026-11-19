"""The Claude.ai skill zip and the Claude Code plugin (W3, v0.3).

End to end: build dist/claimtrace-skill.zip, unzip it, and run its runner in a fresh virtual environment that has
only pydantic (+ pydantic_core and its pure-Python helpers) and lxml, as claude.ai's sandbox is assumed to have, with
ClaimTrace NOT installed and every socket and subprocess blocked. Building needs the pinned pure-Python wheels;
they are downloaded once into dist/.wheel-cache (set CLAIMTRACE_OFFLINE=1 to skip when there is no network and no
cache).
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import venv
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples" / "documents"
DOCS = [EXAMPLES / n for n in ("msa-v1.md", "amendment-1.md", "audit-report-2026.md", "delivery-record.md")]
PLUGIN = ROOT / "plugins" / "claimtrace"
NOT_FOUND = "I could not find support for this in the uploaded documents."

# Imported by the runner before the engine; patches the network and process APIs so any use is recorded and fails.
GUARD = r'''
import os, runpy, socket, subprocess, sys
LOG = os.environ["GUARD_LOG"]
def _record(what):
    with open(LOG, "a") as fh:
        fh.write(what + "\n")
def _deny(what):
    def f(*a, **k):
        _record(what)
        raise OSError(f"blocked by test: {what}")
    return f
class _NoSocket(socket.socket):
    def __init__(self, *a, **k):
        _record("socket")
        raise OSError("blocked by test: socket")
socket.socket = _NoSocket
socket.create_connection = _deny("create_connection")
socket.getaddrinfo = _deny("getaddrinfo")
socket.gethostbyname = _deny("gethostbyname")
subprocess.Popen = _deny("subprocess")
os.system = _deny("os.system")
sys.argv = sys.argv[1:]
runpy.run_path(sys.argv[0], run_name="__main__")
'''


def _build(out: Path) -> Path:
    cache = ROOT / "dist" / ".wheel-cache"
    if os.environ.get("CLAIMTRACE_OFFLINE") and not any(cache.glob("*.whl")):
        pytest.skip("CLAIMTRACE_OFFLINE set and no cached wheels")
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_skill_zip.py"), "--out-dir", str(out)],
                          capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return out / "claimtrace-skill.zip"


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> dict:
    tmp = tmp_path_factory.mktemp("skill")
    zpath = _build(tmp / "dist")
    skill_root = tmp / "unzipped"
    with zipfile.ZipFile(zpath) as z:
        z.extractall(skill_root)
    return {"zip": zpath, "dir": tmp / "dist", "skill": skill_root / "claimtrace", "tmp": tmp}


def _site_packages(env_dir: Path) -> Path:
    found = list(env_dir.glob("lib/python3*/site-packages")) or list(env_dir.glob("Lib/site-packages"))
    assert found, env_dir
    return found[0]


def _python(env_dir: Path) -> Path:
    return env_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _copy_module(name: str, dest: Path) -> None:
    spec = importlib.util.find_spec(name)
    assert spec and spec.origin, f"{name} must be installed in the test environment"
    src = Path(spec.origin)
    if spec.submodule_search_locations:
        shutil.copytree(src.parent, dest / src.parent.name, ignore=shutil.ignore_patterns("__pycache__"))
    else:
        shutil.copy2(src, dest / src.name)


@pytest.fixture(scope="module")
def sandbox_python(built: dict) -> Path:
    """A fresh venv with only pydantic, pydantic_core (and pydantic's own pure deps) and lxml: no claimtrace,
    no httpx, no pypdf, no python-docx, no defusedxml."""
    env_dir = built["tmp"] / "venv"
    venv.EnvBuilder(with_pip=False, system_site_packages=False, clear=True).create(env_dir)
    site = _site_packages(env_dir)
    for mod in ("pydantic", "pydantic_core", "annotated_types", "typing_inspection", "typing_extensions", "lxml"):
        _copy_module(mod, site)
    py = _python(env_dir)
    for absent in ("claimtrace", "httpx", "fastapi", "uvicorn", "pypdf", "docx", "defusedxml"):
        r = subprocess.run([py, "-c", f"import {absent}"], capture_output=True, check=False)
        assert r.returncode != 0, f"{absent} must not be importable in the simulated sandbox"
    return py


def _run(py: Path, built: dict, *args: str, guard: bool = True) -> tuple[int, dict, list[str]]:
    log = built["tmp"] / "guard.log"
    log.unlink(missing_ok=True)
    runner = built["skill"] / "scripts" / "claimtrace_run.py"
    gfile = built["tmp"] / "guard_main.py"
    gfile.write_text(GUARD)
    cmd = [str(py), str(gfile), str(runner), *args] if guard else [str(py), str(runner), *args]
    env = {"PATH": str(py.parent), "GUARD_LOG": str(log), "HOME": str(built["tmp"]), "PYTHONHASHSEED": "0"}
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=built["tmp"], check=False, timeout=300)
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError:
        pytest.fail(f"runner did not print JSON (exit {proc.returncode}):\n{proc.stdout}\n{proc.stderr}")
    attempts = log.read_text().split() if log.exists() else []
    return proc.returncode, out, attempts


def _text(name: str) -> str:
    return (EXAMPLES / name).read_text(encoding="utf-8")


# ------------------------------------------------------------------------------------------------- zip

def test_zip_layout_and_size(built: dict) -> None:
    with zipfile.ZipFile(built["zip"]) as z:
        names = z.namelist()
    assert {n.split("/")[0] for n in names} == {"claimtrace"}, "claude.ai expects one top-level skill folder"
    for required in ("claimtrace/SKILL.md", "claimtrace/scripts/claimtrace_run.py", "claimtrace/vendor/MANIFEST.json",
                     "claimtrace/vendor/src/claimtrace/__init__.py",
                     "claimtrace/vendor/src/claimtrace/core/migrations/001_init.sql", "claimtrace/LICENSE.txt"):
        assert required in names
    wheels = sorted(n.rsplit("/", 1)[1].split("-")[0] for n in names if n.endswith(".whl"))
    assert wheels == ["defusedxml", "pypdf", "python_docx"]
    assert all(n.endswith("-none-any.whl") for n in names if n.endswith(".whl")), "only pure-Python wheels"
    for banned in ("/cli/", "/evaluation/", "/api/", "__pycache__", ".pyc", "fastapi", "uvicorn", "httpx"):
        assert not [n for n in names if banned in n], banned
    assert built["zip"].stat().st_size < 8 * 1024 * 1024


def test_zip_engine_is_built_from_packages(built: dict) -> None:
    manifest = json.loads((built["skill"] / "vendor" / "MANIFEST.json").read_text())
    for rel in manifest["engine"]["files"]:
        src = ROOT / "packages" / Path(rel).relative_to("claimtrace")
        assert (built["skill"] / "vendor" / "src" / rel).read_bytes() == src.read_bytes(), rel


def test_zip_is_reproducible(built: dict, tmp_path: Path) -> None:
    again = _build(tmp_path / "dist")
    assert again.read_bytes() == built["zip"].read_bytes()


def test_skill_frontmatter() -> None:
    text = (PLUGIN / "skills" / "claimtrace" / "SKILL.md").read_text(encoding="utf-8")
    m = re.match(r"\A---\n(.*?)\n---\n", text, re.S)
    assert m
    meta = dict(line.split(": ", 1) for line in m.group(1).splitlines() if ": " in line)
    assert meta["name"] == "claimtrace"
    assert re.fullmatch(r"[a-z0-9-]{1,64}", meta["name"])
    assert len(meta["description"]) <= 1024
    for trigger in ("check this contract", "what are the obligations", "did the amendment change"):
        assert trigger in meta["description"]
    body = text[m.end():]
    for rule in (NOT_FOUND, "0.60", "Never paraphrase a quote", "not legal advice", "processed by Anthropic",
                 "keep documents on your", "quote_verified"):
        assert rule in body, rule


# ------------------------------------------------------------------------------------------------- end to end

def test_analyze_register_and_contradiction_no_network(built: dict, sandbox_python: Path) -> None:
    code, out, attempts = _run(sandbox_python, built, "analyze", *map(str, DOCS))
    assert code == 0, out
    assert attempts == [], f"network or subprocess use: {attempts}"
    assert out["engine"]["source"] == "bundled" and out["engine"]["in_process_parse"] is True
    docs = {d["file"]: d for d in out["documents"]}
    assert docs["amendment-1.md"]["amends"] == "Master Services Agreement"

    reg = out["register"]
    assert reg and all(r["quote_verified"] for r in reg)
    msa = _text("msa-v1.md")
    amd = _text("amendment-1.md")
    for r in reg:  # every register quote is verbatim in its source file
        assert r["quote"] in {"msa-v1.md": msa, "amendment-1.md": amd}.get(r["file"], r["quote"]), r["quote"]
    delivery = [r for r in reg if r["who"] == "Vendor" and r["owes"].startswith("deliver the Phase 1 System")]
    current = [r for r in delivery if r["current"]]
    replaced = [r for r in delivery if not r["current"]]
    assert current and current[0]["by"]["date"] == "2026-05-15" and current[0]["section"] == "1.1"
    assert replaced and "March 31, 2026" in replaced[0]["quote"] and replaced[0]["section"] == "2.1"
    assert current[0]["to"] == "Customer"

    pairs = {(p["mode"], p["other"]): p for p in out["cross_document"]}
    audit = next(p for (mode, other), p in pairs.items() if mode == "evidence" and other.startswith("Vendor Security"))
    contra = [f for f in audit["findings"] if f["verdict"] == "contradicted"
              and any("Dublin" in c["quote"] for c in f["conflicting"])]
    assert contra, audit["findings"]
    f = contra[0]
    assert f["subject"]["quote_verified"] and all(c["quote_verified"] for c in f["conflicting"])
    assert f["subject"]["section"] == "5.2" and "United Kingdom" in f["subject"]["quote"]
    assert f["conflicting"][0]["quote"] in _text("audit-report-2026.md")
    amendment = next(p for (mode, _), p in pairs.items() if mode == "amendment")
    assert amendment["needs_human_check"] and all("0.60" in x["accuracy_note"] for x in amendment["findings"])
    assert "0.60" in out["notice"]["amendment_results"]


def test_ask_answers_with_verified_quote(built: dict, sandbox_python: Path) -> None:
    code, out, attempts = _run(sandbox_python, built, "ask", "Is customer data kept in the UK?", *map(str, DOCS))
    assert code == 0 and attempts == []
    a = out["answer"]
    assert a["found"] and a["status"] == "contradicted"
    sup = [c for c in a["citations"] if c["role"] == "supports"]
    assert sup and sup[0]["quote_verified"] and sup[0]["section"] == "5.2"
    assert sup[0]["quote"] in _text("msa-v1.md")
    assert any("Dublin" in c["quote"] for c in a["citations"] if c["role"] == "conflicts")


def test_ask_not_found(built: dict, sandbox_python: Path) -> None:
    code, out, attempts = _run(sandbox_python, built, "ask", "What is the liability cap?", *map(str, DOCS))
    assert code == 0 and attempts == []
    assert out["answer"]["found"] is False and out["answer"]["answer"] == NOT_FOUND


def test_verify_pair(built: dict, sandbox_python: Path) -> None:
    code, out, attempts = _run(sandbox_python, built, "verify", str(DOCS[0]), str(DOCS[3]))
    assert code == 0 and attempts == []
    v = out["verification"]
    assert v["mode"] == "evidence"
    late = [f for f in v["findings"] if f["verdict"] == "contradicted"]
    assert late and any("May 22, 2026" in c["quote"] for f in late for c in f["conflicting"])


def test_pdf_and_docx_with_vendored_wheels(built: dict, sandbox_python: Path, tmp_path: Path) -> None:
    import docx
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    d = docx.Document()
    d.add_heading("2. Delivery", level=1)
    d.add_paragraph("2.1 The Supplier shall deliver the training manual to the Customer by 15 May 2026.")
    d.save(tmp_path / "agreement.docx")
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.drawString(50, 800, "3. Payment")
    c.drawString(50, 780, "3.1 The Customer shall pay each invoice within 30 days of receipt.")
    c.save()
    (tmp_path / "terms.pdf").write_bytes(buf.getvalue())
    code, out, attempts = _run(sandbox_python, built, "analyze", str(tmp_path / "agreement.docx"),
                               str(tmp_path / "terms.pdf"))
    assert code == 0 and attempts == [], out
    quotes = {r["file"]: r["quote"] for r in out["register"]}
    assert "training manual" in quotes["agreement.docx"]
    assert "within 30 days of receipt" in quotes["terms.pdf"]


def test_claude_code_prefers_installed_cli(built: dict, tmp_path: Path) -> None:
    """With a working `claimtrace` command on PATH, the runner re-runs itself under that command's Python."""
    pytest.importorskip("claimtrace")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    cli = bindir / "claimtrace"
    cli.write_text(f"#!{sys.executable}\nimport sys\nfrom claimtrace.cli.main import main\nsys.exit(main())\n")
    cli.chmod(0o755)
    runner = built["skill"] / "scripts" / "claimtrace_run.py"
    env = {"PATH": f"{bindir}{os.pathsep}{Path(sys.executable).parent}", "HOME": str(tmp_path)}
    proc = subprocess.run([sys.executable, str(runner), "ask", "What is the liability cap?", *map(str, DOCS)],
                          capture_output=True, text=True, env=env, check=False, timeout=300)
    out = json.loads(proc.stdout)
    assert proc.returncode == 0, proc.stderr
    assert out["engine"]["source"] == "installed" and out["engine"]["in_process_parse"] is False
    assert out["answer"]["answer"] == NOT_FOUND


def test_missing_pydantic_gives_clear_message(built: dict) -> None:
    bare = built["tmp"] / "bare"
    venv.EnvBuilder(with_pip=False, clear=True).create(bare)
    code, out, _ = _run(_python(bare), built, "analyze", str(DOCS[0]), guard=False)
    assert code == 3 and out["ok"] is False and out["error"] == "missing_dependency"
    assert "pydantic" in out["message"] and "pip install" in out["message"]


# ------------------------------------------------------------------------------------------------- plugin

def test_plugin_and_marketplace_manifests() -> None:
    plugin = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())
    assert plugin["name"] == "claimtrace" and plugin["version"] == "0.3.0"
    assert plugin["author"] == {"name": "ClaimTrace Maintainers"} and plugin["license"] == "Apache-2.0"
    assert plugin["repository"] == "https://github.com/glowstonesq1/claimtrace"
    market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
    assert market["name"] == "claimtrace" and market["owner"]["name"]
    entry = next(p for p in market["plugins"] if p["name"] == "claimtrace")
    assert (ROOT / entry["source"] / ".claude-plugin" / "plugin.json").resolve() == \
        (PLUGIN / ".claude-plugin" / "plugin.json").resolve()
    assert entry.get("version", plugin["version"]) == plugin["version"]
    for cmd in ("claimtrace-check", "claimtrace-ask"):
        text = (PLUGIN / "commands" / f"{cmd}.md").read_text()
        assert text.startswith("---\ndescription: ") and "claimtrace_run.py" in text and "$ARGUMENTS" in text


@pytest.mark.skipif(shutil.which("claude") is None, reason="Claude Code CLI not installed")
def test_claude_plugin_validate() -> None:
    for target in (PLUGIN, ROOT):
        r = subprocess.run(["claude", "plugin", "validate", str(target)], capture_output=True, text=True, check=False)
        assert r.returncode == 0, r.stdout + r.stderr
