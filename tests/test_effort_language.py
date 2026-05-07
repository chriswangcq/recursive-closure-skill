#!/usr/bin/env python3
"""Tests for effort levels and language hint features."""

from __future__ import annotations

import importlib.util
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


def write_problem(path: Path, title: str) -> Path:
    path.write_text(
        f"# {title}\n\n## Problem\n\nSolve {title}.\n\n## Success Criteria\n\n- done\n",
        encoding="utf-8",
    )
    return path


def test_effort_hint_returns_correct_values() -> None:
    assert "one_go" in ledger.effort_hint("classify-ticket", "low").lower()
    assert "split" in ledger.effort_hint("classify-ticket", "extra-high").lower()
    assert "audit" in ledger.effort_hint("check-success", "extra-high").lower()
    assert "briskly" in ledger.effort_hint("execute-ticket", "low").lower()


def test_effort_hint_returns_empty_for_unknown_action() -> None:
    assert ledger.effort_hint("nonexistent-action", "medium") == ""


def test_effort_hint_returns_empty_for_unknown_level() -> None:
    assert ledger.effort_hint("classify-ticket", "nonexistent") == ""


def test_effort_hint_covers_all_actions_and_levels() -> None:
    for action in ledger.EFFORT_HINTS:
        for level in ledger.EFFORT_LEVELS:
            hint = ledger.effort_hint(action, level)
            assert isinstance(hint, str) and len(hint) > 0, f"Missing hint for {action}/{level}"


def test_effort_hints_covers_all_worker_actions() -> None:
    worker_actions = set(ledger.WORKER_INSTRUCTION_FILES.keys())
    hinted_actions = set(ledger.EFFORT_HINTS.keys())
    missing = worker_actions - hinted_actions
    assert not missing, f"EFFORT_HINTS missing actions present in WORKER_INSTRUCTION_FILES: {missing}"


def _base_state(effort: str = "medium", language: str = "en") -> dict[str, Any]:
    return {
        "schema_version": ledger.SCHEMA_VERSION,
        "ledger_id": "LTEST",
        "root_id": "P000",
        "effort": effort,
        "language": language,
        "counters": {"problem": 1, "ticket": 0, "result": 0, "check": 0, "event": 0},
        "problems": {
            "P000": {
                "id": "P000",
                "root_id": "P000",
                "parent_id": None,
                "created_from_check_id": None,
                "created_from_ticket_id": None,
                "created_from_ticket_mode": None,
                "title": "Test problem",
                "description": "test",
                "status": "todo",
                "success_criteria": ["done"],
                "ticket_ids": [],
                "subproblem_ids": [],
                "result_ids": [],
                "check_ids": [],
                "followup_ids": [],
                "created_at": "",
                "updated_at": "",
                "package_path": "problems/P000",
                "body_path": "problems/P000/README.md",
            }
        },
        "tickets": {},
        "results": {},
        "checks": {},
    }


def test_select_next_includes_effort_hint_for_high() -> None:
    state = _base_state(effort="high")
    item = ledger.select_next(state)
    assert item["next_action"] == "create-solution-ticket"
    assert item["effort"] == "high"


def test_select_next_includes_language_hint_for_non_english() -> None:
    state = _base_state(language="zh")
    item = ledger.select_next(state)
    assert "zh" in item["next_instruction"]


def test_select_next_no_language_hint_for_english() -> None:
    state = _base_state(language="en")
    item = ledger.select_next(state)
    assert "Write all body content" not in item["next_instruction"]


def test_select_next_effort_hint_in_classify_action() -> None:
    state = _base_state(effort="extra-high")
    state["tickets"]["T000"] = {
        "id": "T000",
        "root_id": "P000",
        "problem_id": "P000",
        "title": "Test ticket",
        "status": "defined",
        "classification": None,
        "classification_reason": "",
        "problem_definition": "test",
        "proposed_solution": "test",
        "acceptance_criteria": ["done"],
        "verification_plan": "test",
        "risks": [],
        "assumptions": [],
        "body_path": "",
        "result_ids": [],
        "created_at": "",
        "updated_at": "",
    }
    state["problems"]["P000"]["ticket_ids"] = ["T000"]
    item = ledger.select_next(state)
    assert item["next_action"] == "classify-ticket"
    assert "extra-high" in item["next_instruction"]
    assert "split" in item["next_instruction"].lower()


def test_init_stores_effort_and_language(tmp_path: Path) -> None:
    problem = write_problem(tmp_path / "root.md", "Test")
    run_cli(tmp_path, "init", "--from-file", str(problem), "--effort", "high", "--language", "zh")
    import json
    ledger_dir = next(p for p in (tmp_path / ".complex-problems").iterdir() if p.is_dir())
    state = json.loads((ledger_dir / "state.json").read_text())
    assert state["effort"] == "high"
    assert state["language"] == "zh"


def test_init_defaults_effort_and_language(tmp_path: Path) -> None:
    problem = write_problem(tmp_path / "root.md", "Test")
    run_cli(tmp_path, "init", "--from-file", str(problem))
    import json
    ledger_dir = next(p for p in (tmp_path / ".complex-problems").iterdir() if p.is_dir())
    state = json.loads((ledger_dir / "state.json").read_text())
    assert state["effort"] == "medium"
    assert state["language"] == "en"
