#!/usr/bin/env python3
"""Comprehensive tests for ledger.py — covering previously uncovered paths."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


LEDGER_PATH = Path(__file__).resolve().parents[1] / "scripts" / "ledger.py"
spec = importlib.util.spec_from_file_location("ledger", LEDGER_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Cannot load {LEDGER_PATH}")
ledger = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ledger)


def run_cli(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(LEDGER_PATH), *args],
        cwd=cwd,
        check=check,
        text=True,
        capture_output=True,
    )


def write_body(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def problem_body(path: Path, title: str) -> Path:
    return write_body(path, f"# {title}\n\n## Problem\n\nSolve {title}.\n\n## Success Criteria\n\n- done\n")


def ticket_body(path: Path, title: str) -> Path:
    return write_body(path, f"# {title}\n\n## Problem Definition\n\nDefine.\n\n## Proposed Solution\n\nExecute.\n\n## Acceptance Criteria\n\n- done\n\n## Verification Plan\n\nVerify.\n\n## Risks\n\n- none\n\n## Assumptions\n\n- none\n")


def result_body(path: Path, title: str) -> Path:
    return write_body(path, f"# {title}\n\n## Summary\n\nDone.\n\n## Done\n\n- done\n\n## Verification\n\n- verified\n\n## Known Gaps\n\n- none\n\n## Artifacts\n\n- none\n")


def check_success_body(path: Path, title: str, result_id: str = "R000") -> Path:
    return write_body(path, f"# {title}\n\n## Summary\n\nSuccess.\n\n## Evidence\n\n- verified\n\n## Criteria Map\n\n- done -> verified\n\n## Execution Map\n\n- result executed\n\n## Stress Test\n\n- no failure mode\n\n## Residual Risk\n\n- none\n\n## Result IDs\n\n- {result_id}\n")


def check_not_success_body(path: Path, title: str, result_id: str = "R000") -> Path:
    return write_body(path, f"# {title}\n\n## Summary\n\nNot solved.\n\n## Blocking Gaps\n\n- gap exists\n\n## Result IDs\n\n- {result_id}\n")


# ─── check not_success + followup flow ───

def test_check_not_success_creates_followup(tmp_path: Path) -> None:
    root = problem_body(tmp_path / "root.md", "Root")
    run_cli(tmp_path, "init", "--from-file", str(root))
    run_cli(tmp_path, "create-ticket", "--problem", "P000", "--from-file", str(ticket_body(tmp_path / "t.md", "Ticket")))
    run_cli(tmp_path, "classify-ticket", "T000", "--classification", "one_go", "--reason", "small")
    run_cli(tmp_path, "set-status", "problem", "P000", "doing")
    run_cli(tmp_path, "set-status", "ticket", "T000", "executing")
    run_cli(tmp_path, "result", "--ticket", "T000", "--from-file", str(result_body(tmp_path / "r.md", "Result")))

    followup = problem_body(tmp_path / "followup.md", "Fix the gap")
    check = check_not_success_body(tmp_path / "check.md", "Not success", "R000")
    run_cli(tmp_path, "check", "--problem", "P000", "--status", "not_success", "--result", "R000",
            "--from-file", str(check), "--followup-from-file", str(followup))

    nxt = run_cli(tmp_path, "next")
    assert "P001" in nxt.stdout
    assert "create-solution-ticket" in nxt.stdout


def test_followup_then_success_closes_problem(tmp_path: Path) -> None:
    root = problem_body(tmp_path / "root.md", "Root")
    run_cli(tmp_path, "init", "--from-file", str(root))
    run_cli(tmp_path, "create-ticket", "--problem", "P000", "--from-file", str(ticket_body(tmp_path / "t.md", "T")))
    run_cli(tmp_path, "classify-ticket", "T000", "--classification", "one_go", "--reason", "ok")
    run_cli(tmp_path, "set-status", "problem", "P000", "doing")
    run_cli(tmp_path, "set-status", "ticket", "T000", "executing")
    run_cli(tmp_path, "result", "--ticket", "T000", "--from-file", str(result_body(tmp_path / "r.md", "R")))

    followup = problem_body(tmp_path / "followup.md", "Followup")
    check_ns = check_not_success_body(tmp_path / "cns.md", "NS", "R000")
    run_cli(tmp_path, "check", "--problem", "P000", "--status", "not_success", "--result", "R000",
            "--from-file", str(check_ns), "--followup-from-file", str(followup))

    run_cli(tmp_path, "create-ticket", "--problem", "P001", "--from-file", str(ticket_body(tmp_path / "t1.md", "T1")))
    run_cli(tmp_path, "classify-ticket", "T001", "--classification", "one_go", "--reason", "ok")
    run_cli(tmp_path, "set-status", "problem", "P001", "doing")
    run_cli(tmp_path, "set-status", "ticket", "T001", "executing")
    run_cli(tmp_path, "result", "--ticket", "T001", "--from-file", str(result_body(tmp_path / "r1.md", "R1")))
    cs1 = check_success_body(tmp_path / "cs1.md", "S1", "R001")
    run_cli(tmp_path, "check", "--problem", "P001", "--status", "success", "--result", "R001", "--from-file", str(cs1))

    cs0 = check_success_body(tmp_path / "cs0.md", "S0", "R000")
    run_cli(tmp_path, "check", "--problem", "P000", "--status", "success", "--result", "R000", "--from-file", str(cs0))

    nxt = run_cli(tmp_path, "next")
    assert "none" in nxt.stdout


# ─── validate error detection ───

def test_validate_catches_bad_schema_version(tmp_path: Path) -> None:
    root = problem_body(tmp_path / "root.md", "Root")
    run_cli(tmp_path, "init", "--from-file", str(root))
    state_path = list((tmp_path / ".complex-problems").iterdir())[0] / "state.json"
    state = json.loads(state_path.read_text())
    state["schema_version"] = 99
    state_path.write_text(json.dumps(state))
    errors = ledger.validate(state_path.parent, state)
    assert any("schema_version" in e for e in errors)


def test_validate_catches_invalid_problem_status(tmp_path: Path) -> None:
    root = problem_body(tmp_path / "root.md", "Root")
    run_cli(tmp_path, "init", "--from-file", str(root))
    state_path = list((tmp_path / ".complex-problems").iterdir())[0] / "state.json"
    state = json.loads(state_path.read_text())
    state["problems"]["P000"]["status"] = "invalid_status"
    errors = ledger.validate(state_path.parent, state)
    assert any("invalid status" in e for e in errors)


def test_validate_catches_missing_body_file(tmp_path: Path) -> None:
    root = problem_body(tmp_path / "root.md", "Root")
    run_cli(tmp_path, "init", "--from-file", str(root))
    ledger_dir = list((tmp_path / ".complex-problems").iterdir())[0]
    state_path = ledger_dir / "state.json"
    state = json.loads(state_path.read_text())
    body_path = state["problems"]["P000"]["body_path"]
    (ledger_dir / body_path).unlink()
    errors = ledger.validate(ledger_dir, state)
    assert any("missing body file" in e for e in errors)


def test_validate_catches_counter_inconsistency(tmp_path: Path) -> None:
    root = problem_body(tmp_path / "root.md", "Root")
    run_cli(tmp_path, "init", "--from-file", str(root))
    state_path = list((tmp_path / ".complex-problems").iterdir())[0] / "state.json"
    state = json.loads(state_path.read_text())
    state["counters"]["problem"] = 0
    errors = ledger.validate(state_path.parent, state)
    assert any("Counter" in e and "problem" in e for e in errors)


# ─── split complete flow ───

def test_split_creates_children_and_summarizes(tmp_path: Path) -> None:
    root = problem_body(tmp_path / "root.md", "Root")
    run_cli(tmp_path, "init", "--from-file", str(root))
    run_cli(tmp_path, "create-ticket", "--problem", "P000", "--from-file", str(ticket_body(tmp_path / "t.md", "Split ticket")))
    run_cli(tmp_path, "classify-ticket", "T000", "--classification", "split", "--reason", "multi-part")
    run_cli(tmp_path, "set-status", "ticket", "T000", "splitting")

    child1 = problem_body(tmp_path / "c1.md", "Child 1")
    child2 = problem_body(tmp_path / "c2.md", "Child 2")
    run_cli(tmp_path, "create-problem", "--parent", "P000", "--from-ticket", "T000", "--mode", "split", "--from-file", str(child1))
    run_cli(tmp_path, "create-problem", "--parent", "P000", "--from-ticket", "T000", "--mode", "split", "--from-file", str(child2))

    for pid, tid, rid in [("P001", "T001", "R000"), ("P002", "T002", "R001")]:
        run_cli(tmp_path, "create-ticket", "--problem", pid, "--from-file", str(ticket_body(tmp_path / f"t_{pid}.md", f"T for {pid}")))
        run_cli(tmp_path, "classify-ticket", tid, "--classification", "one_go", "--reason", "simple")
        run_cli(tmp_path, "set-status", "problem", pid, "doing")
        run_cli(tmp_path, "set-status", "ticket", tid, "executing")
        run_cli(tmp_path, "result", "--ticket", tid, "--from-file", str(result_body(tmp_path / f"r_{pid}.md", f"R for {pid}")))
        cs = check_success_body(tmp_path / f"cs_{pid}.md", f"Check {pid}", rid)
        run_cli(tmp_path, "check", "--problem", pid, "--status", "success", "--result", rid, "--from-file", str(cs))

    run_cli(tmp_path, "set-status", "problem", "P000", "doing")
    run_cli(tmp_path, "result", "--ticket", "T000", "--from-file", str(result_body(tmp_path / "r_parent.md", "Parent summary")))
    cs_parent = check_success_body(tmp_path / "cs_parent.md", "Parent check", "R002")
    run_cli(tmp_path, "check", "--problem", "P000", "--status", "success", "--result", "R002", "--from-file", str(cs_parent))

    nxt = run_cli(tmp_path, "next")
    assert "none" in nxt.stdout

    val = run_cli(tmp_path, "validate")
    assert "valid" in val.stdout.lower()


# ─── set-status permission rejection ───

def test_set_status_rejects_problem_to_done(tmp_path: Path) -> None:
    root = problem_body(tmp_path / "root.md", "Root")
    run_cli(tmp_path, "init", "--from-file", str(root))
    result = run_cli(tmp_path, "set-status", "problem", "P000", "done", check=False)
    assert result.returncode != 0
    assert "only allows doing" in result.stderr.lower() or "set-status" in result.stderr.lower()


def test_set_status_rejects_ticket_to_done(tmp_path: Path) -> None:
    root = problem_body(tmp_path / "root.md", "Root")
    run_cli(tmp_path, "init", "--from-file", str(root))
    run_cli(tmp_path, "create-ticket", "--problem", "P000", "--from-file", str(ticket_body(tmp_path / "t.md", "T")))
    result = run_cli(tmp_path, "set-status", "ticket", "T000", "done", check=False)
    assert result.returncode != 0
    assert "only allows" in result.stderr.lower()


# ─── list/use commands ───

def test_list_shows_ledger(tmp_path: Path) -> None:
    root = problem_body(tmp_path / "root.md", "Root")
    run_cli(tmp_path, "init", "--from-file", str(root))
    result = run_cli(tmp_path, "list")
    assert "L" in result.stdout
    assert "Root" in result.stdout


def test_use_sets_active_ledger(tmp_path: Path) -> None:
    root = problem_body(tmp_path / "root.md", "Root")
    init_result = run_cli(tmp_path, "init", "--from-file", str(root))
    ledger_path = init_result.stdout.strip()
    ledger_id_value = Path(ledger_path).name
    run_cli(tmp_path, "use", ledger_id_value)
    idx = json.loads((tmp_path / ".complex-problems" / "INDEX.json").read_text())
    assert idx["active_ledger_id"] == ledger_id_value


def test_use_unknown_ledger_fails(tmp_path: Path) -> None:
    (tmp_path / ".complex-problems").mkdir()
    result = run_cli(tmp_path, "use", "L_nonexistent", check=False)
    assert result.returncode != 0


# ─── create-problem illegal parameters ───

def test_create_problem_rejects_wrong_mode_for_split(tmp_path: Path) -> None:
    root = problem_body(tmp_path / "root.md", "Root")
    run_cli(tmp_path, "init", "--from-file", str(root))
    run_cli(tmp_path, "create-ticket", "--problem", "P000", "--from-file", str(ticket_body(tmp_path / "t.md", "T")))
    run_cli(tmp_path, "classify-ticket", "T000", "--classification", "one_go", "--reason", "ok")
    run_cli(tmp_path, "set-status", "problem", "P000", "doing")
    run_cli(tmp_path, "set-status", "ticket", "T000", "executing")
    child = problem_body(tmp_path / "child.md", "Child")
    result = run_cli(tmp_path, "create-problem", "--parent", "P000", "--from-ticket", "T000", "--mode", "split", "--from-file", str(child), check=False)
    assert result.returncode != 0


# ─── new commands ───

def test_batch_next_returns_all_runnable(tmp_path: Path) -> None:
    root = problem_body(tmp_path / "root.md", "Root")
    run_cli(tmp_path, "init", "--from-file", str(root))
    run_cli(tmp_path, "create-ticket", "--problem", "P000", "--from-file", str(ticket_body(tmp_path / "t.md", "T")))
    run_cli(tmp_path, "classify-ticket", "T000", "--classification", "split", "--reason", "multi")
    run_cli(tmp_path, "set-status", "ticket", "T000", "splitting")
    child1 = problem_body(tmp_path / "c1.md", "Child 1")
    child2 = problem_body(tmp_path / "c2.md", "Child 2")
    run_cli(tmp_path, "create-problem", "--parent", "P000", "--from-ticket", "T000", "--mode", "split", "--from-file", str(child1))
    run_cli(tmp_path, "create-problem", "--parent", "P000", "--from-ticket", "T000", "--mode", "split", "--from-file", str(child2))

    result = run_cli(tmp_path, "batch-next", "--json")
    items = json.loads(result.stdout)
    assert len(items) == 2
    pids = {item["problem_id"] for item in items}
    assert pids == {"P001", "P002"}


def test_set_effort_changes_effort(tmp_path: Path) -> None:
    root = problem_body(tmp_path / "root.md", "Root")
    run_cli(tmp_path, "init", "--from-file", str(root))
    result = run_cli(tmp_path, "set-effort", "high")
    assert "high" in result.stdout

    ledger_dir = list((tmp_path / ".complex-problems").iterdir())[0]
    state = json.loads((ledger_dir / "state.json").read_text())
    assert state["effort"] == "high"


def test_purge_events_clears_events(tmp_path: Path) -> None:
    root = problem_body(tmp_path / "root.md", "Root")
    run_cli(tmp_path, "init", "--from-file", str(root))
    result = run_cli(tmp_path, "purge-events", "--keep", "0")
    assert "purged" in result.stdout


# ─── slugify with CJK extensions ───

def test_slugify_handles_japanese_kana() -> None:
    result = ledger.slugify("テスト問題")
    assert "テスト問題" in result


def test_slugify_handles_korean() -> None:
    result = ledger.slugify("테스트 문제")
    assert "테스트" in result


# ─── next_id dynamic width ───

def test_next_id_dynamic_width() -> None:
    state: dict[str, Any] = {"counters": {"problem": 999}}
    id999 = ledger.next_id(state, "P")
    assert id999 == "P999"
    id1000 = ledger.next_id(state, "P")
    assert id1000 == "P1000"


# ─── error message i18n ───

def test_err_msg_returns_zh_when_set() -> None:
    original = ledger._current_language
    try:
        ledger.set_language("zh")
        msg = ledger.err_msg("ledger_valid")
        assert "验证通过" in msg
    finally:
        ledger.set_language(original)


def test_err_msg_falls_back_to_english() -> None:
    original = ledger._current_language
    try:
        ledger.set_language("fr")
        msg = ledger.err_msg("ledger_valid")
        assert "valid" in msg.lower()
    finally:
        ledger.set_language(original)
