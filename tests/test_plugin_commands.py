"""The shell commands the plugin's slash commands and SKILL.md tell Claude to run must not let the user's words or
paths be interpreted by the shell. Each test runs the exact documented command form through `bash -c`."""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "plugins" / "claimtrace"
SKILL = PLUGIN / "skills" / "claimtrace"
EXAMPLES = ROOT / "examples" / "documents"
QUESTION = "Is the cap $1,000,000? `whoami` $(id)"
CANARY_QUESTION = "Was it delivered? $(touch {canary}) `touch {canary}` ${{X:=$(touch {canary})}}\" ' \\ !!"

PATHS = re.compile(r"<(?:paths|folder or files|files or folders?\.\.\.)>")


def _block(doc: Path, command: str) -> str:
    """The fenced bash block in `doc` that runs the runner's `command`."""
    blocks = re.findall(r"```bash\n(.*?)```", doc.read_text(encoding="utf-8"), re.S)
    found = [b for b in blocks if re.search(rf"claimtrace_run\.py\"? {command}\b", b)]
    assert found, f"{doc.name}: no bash block runs `claimtrace_run.py {command}`"
    return found[0]


def _env(tmp_path: Path) -> dict[str, str]:
    """`python3` on PATH is this test's interpreter (it can import the engine from the source checkout)."""
    shim = tmp_path / "bin"
    shim.mkdir(exist_ok=True)
    (shim / "python3").unlink(missing_ok=True)
    (shim / "python3").symlink_to(sys.executable)
    return {"PATH": f"{shim}:/usr/bin:/bin", "HOME": str(tmp_path), "CLAUDE_PLUGIN_ROOT": str(PLUGIN),
            "CLAIMTRACE_ENGINE": "bundled"}


def _bash(script: str, tmp_path: Path) -> dict:
    proc = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=_env(tmp_path), cwd=tmp_path,
                          check=False, timeout=300)
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        pytest.fail(f"runner did not print JSON (exit {proc.returncode}):\n{proc.stdout}\n{proc.stderr}")


def _ask_script(doc: Path, question: str, paths: list[Path]) -> str:
    block = _block(doc, "ask")
    assert "<question>" in block and PATHS.search(block), f"{doc.name}: placeholders changed"
    block = block.replace("<skill-folder>", str(SKILL))
    block = PATHS.sub(lambda _m: " ".join(shlex.quote(str(p)) for p in paths), block)
    return block.replace("<question>", question)


@pytest.mark.parametrize("doc", [PLUGIN / "commands" / "claimtrace-ask.md", SKILL / "SKILL.md"], ids=lambda p: p.name)
def test_ask_question_reaches_the_runner_byte_for_byte(doc: Path, tmp_path: Path) -> None:
    out = _bash(_ask_script(doc, QUESTION, [EXAMPLES / "msa-v1.md"]), tmp_path)
    assert out.get("ok"), out
    assert out["answer"]["question"] == QUESTION


@pytest.mark.parametrize("doc", [PLUGIN / "commands" / "claimtrace-ask.md", SKILL / "SKILL.md"], ids=lambda p: p.name)
def test_ask_question_runs_nothing(doc: Path, tmp_path: Path) -> None:
    canary = tmp_path / "canary"
    question = CANARY_QUESTION.format(canary=canary)
    out = _bash(_ask_script(doc, question, [EXAMPLES / "msa-v1.md"]), tmp_path)
    assert not canary.exists(), "a shell expansion in the question ran"
    assert out.get("ok"), out
    assert out["answer"]["question"] == question


def test_runner_reads_the_question_from_stdin(tmp_path: Path) -> None:
    runner = SKILL / "scripts" / "claimtrace_run.py"
    proc = subprocess.run([sys.executable, str(runner), "--engine", "bundled", "ask", "--question-file", "-",
                           str(EXAMPLES / "msa-v1.md")], input=QUESTION + "\n", capture_output=True, text=True,
                          env={**os.environ, "HOME": str(tmp_path)}, check=False, timeout=300)
    out = json.loads(proc.stdout)
    assert proc.returncode == 0, out
    assert out["answer"]["question"] == QUESTION


def _check_script(doc: Path, paths: list[Path]) -> str:
    """The analyze command as Claude would run it for these paths. A literal `$ARGUMENTS` in the block is replaced
    with the raw argument text, as Claude Code does; a `<paths>` placeholder is filled per the doc's quoting rule
    (each path in single quotes), which the doc must state."""
    text = doc.read_text(encoding="utf-8")
    block = _block(doc, "analyze").replace("<skill-folder>", str(SKILL))
    if "$ARGUMENTS" in block:
        return block.replace("$ARGUMENTS", " ".join(str(p) for p in paths))
    assert "single quotes" in text, f"{doc.name}: must tell Claude to single-quote each path"
    return PATHS.sub(lambda _m: " ".join(shlex.quote(str(p)) for p in paths), block)


@pytest.mark.parametrize("doc", [PLUGIN / "commands" / "claimtrace-check.md", SKILL / "SKILL.md"], ids=lambda p: p.name)
def test_check_command_keeps_a_folder_with_spaces_whole(doc: Path, tmp_path: Path) -> None:
    folder = tmp_path / "My Contracts"
    folder.mkdir()
    (folder / "msa v1.md").write_bytes((EXAMPLES / "msa-v1.md").read_bytes())
    out = _bash(_check_script(doc, [folder]), tmp_path)
    assert out.get("ok"), out
    assert [d["file"] for d in out["documents"]] == ["msa v1.md"] and out["skipped_files"] == []
