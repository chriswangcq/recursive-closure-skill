#!/usr/bin/env python3
"""Regression checks for recursive next-action scheduling."""

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


def problem(
    problem_id: str,
    status: str,
    *,
    parent_id: str | None = None,
    subproblem_ids: list[str] | None = None,
    ticket_ids: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": problem_id,
        "root_id": "P000",
        "parent_id": parent_id,
        "created_from_check_id": None,
        "created_from_ticket_id": None,
        "created_from_ticket_mode": None,
        "title": f"{problem_id} title",
        "description": "",
        "status": status,
        "success_criteria": [],
        "ticket_ids": ticket_ids or [],
        "subproblem_ids": subproblem_ids or [],
        "result_ids": [],
        "check_ids": [],
        "followup_ids": [],
        "created_at": "",
        "updated_at": "",
        "package_path": "",
        "body_path": "",
    }


def ticket(ticket_id: str, problem_id: str, status: str) -> dict[str, Any]:
    return {
        "id": ticket_id,
        "root_id": "P000",
        "problem_id": problem_id,
        "title": f"{ticket_id} title",
        "status": status,
        "classification": "split",
        "classification_reason": "",
        "problem_definition": "",
        "proposed_solution": "",
        "acceptance_criteria": [],
        "verification_plan": "",
        "risks": [],
        "assumptions": [],
        "body_path": "",
        "result_ids": [],
        "created_at": "",
        "updated_at": "",
    }


def base_state(problems: dict[str, dict[str, Any]], tickets: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "schema_version": ledger.SCHEMA_VERSION,
        "ledger_id": "LTEST",
        "root_id": "P000",
        "counters": {"problem": 0, "ticket": 0, "result": 0, "check": 0, "event": 0},
        "problems": problems,
        "tickets": tickets or {},
        "results": {},
        "checks": {},
        "events": [],
        "created_at": "",
        "updated_at": "",
    }


def test_open_child_is_selected_before_waiting_parent() -> None:
    state = base_state(
        {
            "P000": problem("P000", "followup", subproblem_ids=["P001"], ticket_ids=["T000"]),
            "P001": problem("P001", "todo", parent_id="P000"),
        },
        {"T000": ticket("T000", "P000", "splitting")},
    )

    item = ledger.select_next(state)

    assert item["problem_id"] == "P001"
    assert item["next_action"] == "create-solution-ticket"


def test_deepest_open_frontier_is_selected() -> None:
    state = base_state(
        {
            "P000": problem("P000", "followup", subproblem_ids=["P001"], ticket_ids=["T000"]),
            "P001": problem("P001", "followup", parent_id="P000", subproblem_ids=["P002"], ticket_ids=["T001"]),
            "P002": problem("P002", "todo", parent_id="P001"),
        },
        {
            "T000": ticket("T000", "P000", "splitting"),
            "T001": ticket("T001", "P001", "splitting"),
        },
    )

    item = ledger.select_next(state)

    assert item["problem_id"] == "P002"
    assert item["next_action"] == "create-solution-ticket"


def test_parent_becomes_runnable_after_children_close() -> None:
    state = base_state(
        {
            "P000": problem("P000", "followup", subproblem_ids=["P001"], ticket_ids=["T000"]),
            "P001": problem("P001", "done", parent_id="P000"),
        },
        {"T000": ticket("T000", "P000", "splitting")},
    )

    item = ledger.select_next(state)

    assert item["problem_id"] == "P000"
    assert item["next_action"] == "record-result"


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
    return write_body(
        path,
        f"""# {title}

## Problem

Solve {title}.

## Success Criteria

- done
""",
    )


def ticket_body(path: Path, title: str) -> Path:
    return write_body(
        path,
        f"""# {title}

## Problem Definition

Define the problem.

## Proposed Solution

Execute the solution.

## Acceptance Criteria

- done

## Verification Plan

Verify the result.

## Risks

- none

## Assumptions

- none
""",
    )


def result_body(path: Path, title: str) -> Path:
    return write_body(
        path,
        f"""# {title}

## Summary

Completed {title}.

## Done

- done

## Verification

- verified

## Known Gaps

- none

## Artifacts

- none
""",
    )


def check_body(path: Path, title: str) -> Path:
    return write_body(
        path,
        f"""# {title}

## Summary

Success.

## Evidence

- verified

## Criteria Map

- done -> verified

## Execution Map

- result executed

## Stress Test

- no obvious failure mode remains

## Residual Risk

- none

## Result IDs

- R000
""",
    )


def test_runtime_spawn_routes_to_child_and_blocks_parent_result(tmp_path: Path) -> None:
    root = problem_body(tmp_path / "root.md", "Root problem")
    run_cli(tmp_path, "init", "--from-file", str(root))
    run_cli(tmp_path, "create-ticket", "--problem", "P000", "--from-file", str(ticket_body(tmp_path / "ticket.md", "Parent ticket")))
    run_cli(tmp_path, "classify-ticket", "T000", "--classification", "one_go", "--reason", "bounded attempt")
    run_cli(tmp_path, "set-status", "problem", "P000", "doing")
    run_cli(tmp_path, "set-status", "ticket", "T000", "executing")
    run_cli(
        tmp_path,
        "create-problem",
        "--parent",
        "P000",
        "--from-ticket",
        "T000",
        "--mode",
        "spawn",
        "--from-file",
        str(problem_body(tmp_path / "spawned.md", "Spawned child")),
    )

    item = run_cli(tmp_path, "next", "--json").stdout
    assert '"problem_id": "P001"' in item
    assert '"next_action": "create-solution-ticket"' in item

    blocked = run_cli(tmp_path, "result", "--ticket", "T000", "--from-file", str(result_body(tmp_path / "parent-result.md", "Parent result")), check=False)
    assert blocked.returncode != 0
    assert "child problems still open: P001" in blocked.stderr


def test_runtime_spawn_happy_path_validates_after_child_closes(tmp_path: Path) -> None:
    root = problem_body(tmp_path / "root.md", "Root problem")
    run_cli(tmp_path, "init", "--from-file", str(root))
    run_cli(tmp_path, "create-ticket", "--problem", "P000", "--from-file", str(ticket_body(tmp_path / "parent-ticket.md", "Parent ticket")))
    run_cli(tmp_path, "classify-ticket", "T000", "--classification", "one_go", "--reason", "bounded attempt")
    run_cli(tmp_path, "set-status", "problem", "P000", "doing")
    run_cli(tmp_path, "set-status", "ticket", "T000", "executing")
    run_cli(
        tmp_path,
        "create-problem",
        "--parent",
        "P000",
        "--from-ticket",
        "T000",
        "--mode",
        "spawn",
        "--from-file",
        str(problem_body(tmp_path / "spawned.md", "Spawned child")),
    )

    run_cli(tmp_path, "create-ticket", "--problem", "P001", "--from-file", str(ticket_body(tmp_path / "child-ticket.md", "Child ticket")))
    run_cli(tmp_path, "classify-ticket", "T001", "--classification", "one_go", "--reason", "small child")
    run_cli(tmp_path, "set-status", "problem", "P001", "doing")
    run_cli(tmp_path, "result", "--ticket", "T001", "--from-file", str(result_body(tmp_path / "child-result.md", "Child result")))
    run_cli(tmp_path, "check", "--problem", "P001", "--status", "success", "--result", "R000", "--from-file", str(check_body(tmp_path / "child-check.md", "Child check")))

    item = run_cli(tmp_path, "next", "--json").stdout
    assert '"problem_id": "P000"' in item
    assert '"next_action": "record-result"' in item

    run_cli(tmp_path, "result", "--ticket", "T000", "--from-file", str(result_body(tmp_path / "parent-result.md", "Parent result")))
    run_cli(tmp_path, "validate")


def test_split_and_spawn_modes_reject_wrong_ticket_states(tmp_path: Path) -> None:
    root = problem_body(tmp_path / "root.md", "Root problem")
    run_cli(tmp_path, "init", "--from-file", str(root))
    run_cli(tmp_path, "create-ticket", "--problem", "P000", "--from-file", str(ticket_body(tmp_path / "ticket.md", "Parent ticket")))
    run_cli(tmp_path, "classify-ticket", "T000", "--classification", "one_go", "--reason", "bounded")
    run_cli(tmp_path, "set-status", "problem", "P000", "doing")
    run_cli(tmp_path, "set-status", "ticket", "T000", "executing")

    wrong_split = run_cli(
        tmp_path,
        "create-problem",
        "--parent",
        "P000",
        "--from-ticket",
        "T000",
        "--mode",
        "split",
        "--from-file",
        str(problem_body(tmp_path / "wrong-split.md", "Wrong split")),
        check=False,
    )
    assert wrong_split.returncode != 0
    assert "must be classified as split" in wrong_split.stderr

    second = tmp_path / "second"
    second.mkdir()
    run_cli(second, "init", "--from-file", str(problem_body(second / "root.md", "Root problem")))
    run_cli(second, "create-ticket", "--problem", "P000", "--from-file", str(ticket_body(second / "ticket.md", "Split ticket")))
    run_cli(second, "classify-ticket", "T000", "--classification", "split", "--reason", "needs split")
    run_cli(second, "set-status", "problem", "P000", "doing")
    run_cli(second, "set-status", "ticket", "T000", "splitting")
    wrong_spawn = run_cli(
        second,
        "create-problem",
        "--parent",
        "P000",
        "--from-ticket",
        "T000",
        "--mode",
        "spawn",
        "--from-file",
        str(problem_body(second / "wrong-spawn.md", "Wrong spawn")),
        check=False,
    )
    assert wrong_spawn.returncode != 0
    assert "must be classified as one_go" in wrong_spawn.stderr

    created_split = run_cli(
        second,
        "create-problem",
        "--parent",
        "P000",
        "--from-ticket",
        "T000",
        "--mode",
        "split",
        "--from-file",
        str(problem_body(second / "right-split.md", "Right split")),
    )
    assert created_split.stdout.strip() == "P001"
    run_cli(second, "validate")


if __name__ == "__main__":
    test_open_child_is_selected_before_waiting_parent()
    test_deepest_open_frontier_is_selected()
    test_parent_becomes_runnable_after_children_close()
    print("frontier scheduler tests passed")
