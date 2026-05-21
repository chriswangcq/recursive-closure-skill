#!/usr/bin/env python3
"""Complex Problem Ledger.

Single-file CLI for maintaining a root problem, problem tree, execution tickets,
results, checks, follow-ups, and rendered Markdown views.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

try:
    import fcntl
    _HAS_FCNTL = True
except ImportError:
    _HAS_FCNTL = False


SCHEMA_VERSION = 6
EFFORT_LEVELS = {"low", "medium", "high", "extra-high"}
PROBLEM_STATUSES = {"todo", "doing", "checking", "followup", "done", "blocked"}
OPEN_PROBLEM_STATUSES = PROBLEM_STATUSES - {"done"}
TICKET_STATUSES = {"created", "defined", "classified", "executing", "splitting", "done"}
TICKET_CLASSIFICATIONS = {"one_go", "split"}
CREATED_FROM_TICKET_MODES = {"split", "spawn"}
CHECK_STATUSES = {"success", "not_success", "blocked"}
STATE_FIELDS = {
    "schema_version", "ledger_id", "root_id", "effort", "language", "created_at", "updated_at",
    "counters", "problems", "tickets", "results", "checks",
}
PROBLEM_FIELDS = {
    "id", "root_id", "parent_id", "created_from_check_id", "created_from_ticket_id",
    "created_from_ticket_mode", "title", "description", "status", "success_criteria", "ticket_ids",
    "subproblem_ids", "result_ids", "check_ids", "followup_ids", "created_at",
    "updated_at", "package_path", "body_path",
}
TICKET_FIELDS = {
    "id", "root_id", "problem_id", "title", "status", "classification",
    "classification_reason", "problem_definition", "proposed_solution",
    "acceptance_criteria", "verification_plan", "risks", "assumptions",
    "result_ids", "created_at", "updated_at", "body_path",
}
RESULT_FIELDS = {
    "id", "root_id", "ticket_id", "problem_id", "summary", "done",
    "verification", "known_gaps", "artifacts", "created_at", "body_path",
}
CHECK_FIELDS = {
    "id", "root_id", "problem_id", "status", "evidence", "criteria_map",
    "execution_map", "stress_test", "residual_risk", "blocking_gaps",
    "result_ids", "followup_problem_id", "summary", "created_at", "body_path",
}
PROBLEM_TRANSITIONS = {
    "todo": {"doing", "blocked"},
    "doing": {"checking", "blocked"},
    "checking": {"done", "followup", "blocked", "doing"},
    "followup": {"doing", "checking", "blocked"},
    "blocked": {"doing"},
    "done": set(),
}
TICKET_TRANSITIONS = {
    "created": {"defined"},
    "defined": {"classified"},
    "classified": {"executing", "splitting"},
    "executing": {"done"},
    "splitting": {"done"},
    "done": set(),
}

EFFORT_HINTS = {
    "create-solution-ticket": {
        "low": "Write a concise ticket. Broad acceptance criteria are fine; do not over-specify.",
        "medium": "Write a clear ticket with concrete acceptance criteria and a realistic verification plan.",
        "high": "Write a thorough ticket. Each acceptance criterion must be independently verifiable. Enumerate risks and assumptions explicitly.",
        "extra-high": "Write an exhaustive ticket. Every criterion must have a matching verification step. Risks, assumptions, and edge cases must be enumerated; nothing left implicit.",
    },
    "define-ticket": {
        "low": "Repair the minimum fields needed to unblock classification.",
        "medium": "Ensure all required fields are complete and internally consistent.",
        "high": "Ensure all fields are complete, consistent, and specific enough to support fine-grained splitting or rigorous checking.",
        "extra-high": "Every field must be precise and independently verifiable. Vague or hand-wavy content must be rewritten before classification.",
    },
    "classify-ticket": {
        "low": "Prefer `one_go` unless the problem has clearly independent sub-outcomes. Bias toward action.",
        "medium": "Prefer `split` unless it is clearly small, concrete, low-risk, and easy to verify.",
        "high": "Choose `split` unless the work is trivially small. Even moderate complexity warrants decomposition.",
        "extra-high": "Default to `split` for everything except single-function, single-file, trivially verifiable changes.",
    },
    "execute-ticket": {
        "low": "Execute briskly. Record gaps honestly but do not over-investigate edge cases.",
        "medium": "Push the task as far as safely and honestly possible. Be honest about what was and was not verified.",
        "high": "Thorough execution with proactive edge-case investigation. Verify each claim before recording.",
        "extra-high": "Exhaustive execution. Every claim must be verified inline. Spawn a child for any non-trivial subprogram rather than inlining it.",
    },
    "split-ticket": {
        "low": "Split into 2-3 coarse-grained children. Combine related work into single children where reasonable.",
        "medium": "Split into children that are each small enough to solve recursively with clear success criteria.",
        "high": "Prefer fine-grained atomic children. Each child should have a single outcome and single verification path.",
        "extra-high": "Every child must be single-responsibility with one success criterion. Do not combine distinct verification paths into one child.",
    },
    "record-result": {
        "low": "Record a concise summary. Known gaps are acceptable if honestly listed.",
        "medium": "Record a clear summary with done items, verification notes, and honest gap list.",
        "high": "Record a thorough result. Every done item must have inline verification. Gaps must be specific and actionable.",
        "extra-high": "Record an exhaustive result. Every claim must cite evidence. Every gap must be specific, actionable, and scoped. No vague summaries.",
    },
    "check-success": {
        "low": "Verify that the core criteria are met. Light stress test is acceptable; skip exhaustive residual-risk enumeration if the result is straightforward.",
        "medium": "Strictly judge whether cited results solve the original problem; apply extra skepticism to `one_go` results.",
        "high": "Every criterion must map to independent evidence. Stress test must cover 2+ plausible failure modes. Residual risks must be enumerated even if non-blocking.",
        "extra-high": "Full audit: every criterion mapped, every execution path verified, stress test covers all plausible failure modes, residual risk is exhaustive. Any gap or vague claim triggers `not_success`.",
    },
    "unblock-or-report": {
        "low": "Report the blocker concisely. If resolvable, unblock and move on.",
        "medium": "Diagnose the blocker, report root cause, and unblock if the resolution is clear.",
        "high": "Thorough blocker diagnosis with root-cause analysis. Document what was tried before escalating.",
        "extra-high": "Exhaustive blocker analysis. Document all attempted resolutions, root cause, and downstream impact before unblocking or escalating.",
    },
    "none": {
        "low": "Summarize briefly.",
        "medium": "Summarize with key metrics and residual risks.",
        "high": "Thorough summary with full metrics, residual risks, and artifact locations.",
        "extra-high": "Exhaustive closure summary. Every problem, result, and check must be referenced. Residual risks must be explicitly enumerated.",
    },
}

ERROR_MESSAGES = {
    "unknown_problem": {"en": "Unknown problem: {id}", "zh": "未知问题: {id}"},
    "unknown_ticket": {"en": "Unknown ticket: {id}", "zh": "未知工单: {id}"},
    "unknown_ledger": {"en": "Unknown ledger under {root}: {id}", "zh": "{root} 下未找到台账: {id}"},
    "illegal_transition": {"en": "Illegal {kind} transition for {id}: {old} -> {new}", "zh": "{id} 的{kind}状态转换不合法: {old} -> {new}"},
    "problem_must_be_doing": {"en": "Problem {id} must be doing before recording a ticket result", "zh": "问题 {id} 必须处于 doing 状态才能记录工单结果"},
    "cannot_record_result": {"en": "Cannot record result for ticket {tid} while problem {pid} is {status}", "zh": "问题 {pid} 处于 {status} 状态时不能为工单 {tid} 记录结果"},
    "ticket_must_be_defined": {"en": "Ticket {id} must be defined before classification; current status is {status}", "zh": "工单 {id} 必须先定义才能分类；当前状态: {status}"},
    "problem_already_has_ticket": {"en": "Problem {id} already has a ticket: {tid}", "zh": "问题 {id} 已有工单: {tid}"},
    "set_status_problem_only_doing": {"en": "Public set-status for problems only allows doing; use check to write checking/done/followup/blocked outcomes", "zh": "公开的 set-status 仅允许设置问题为 doing；使用 check 写入 checking/done/followup/blocked"},
    "set_status_ticket_only_executing_splitting": {"en": "Public set-status for tickets only allows executing or splitting; use result to mark tickets done", "zh": "公开的 set-status 仅允许设置工单为 executing 或 splitting；使用 result 标记工单完成"},
    "no_ledgers_found": {"en": "No ledgers found under {root}", "zh": "{root} 下未找到台账"},
    "ledger_valid": {"en": "Ledger is valid!", "zh": "台账验证通过！"},
    "children_still_open": {"en": "Cannot finish ticket {tid}; child problems still open: {children}", "zh": "工单 {tid} 无法完成；子问题仍未关闭: {children}"},
    "split_no_children": {"en": "Cannot finish split ticket {tid}; create at least one child problem first", "zh": "拆分工单 {tid} 无法完成；请先创建至少一个子问题"},
}

_current_language = "en"


def set_language(lang: str) -> None:
    global _current_language
    _current_language = lang


def err_msg(key: str, **kwargs: Any) -> str:
    msgs = ERROR_MESSAGES.get(key, {})
    template = msgs.get(_current_language, msgs.get("en", key))
    return template.format(**kwargs)


def effort_hint(action: str, effort: str) -> str:
    hints = EFFORT_HINTS.get(action)
    if not hints:
        return ""
    return hints.get(effort, "")


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def slugify(text: str, limit: int = 48) -> str:
    text = text.lower()
    text = re.sub(
        r"[^a-z0-9"
        r"\u4e00-\u9fff"
        r"\u3400-\u4dbf"
        r"\u3040-\u309f"
        r"\u30a0-\u30ff"
        r"\uac00-\ud7af"
        r"\U00020000-\U0002a6df"
        r"]+", "-", text
    ).strip("-")
    return (text[:limit].strip("-") or "item")


def next_id(state: dict[str, Any], prefix: str) -> str:
    key = {"P": "problem", "T": "ticket", "R": "result", "C": "check", "E": "event"}[prefix]
    value = state["counters"].get(key, 0)
    state["counters"][key] = value + 1
    return f"{prefix}{value:0{max(3, len(str(value)))}d}"


def ledger_id() -> str:
    return "L" + dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def validate_ledger_id(value: str) -> str:
    if value in {".", ".."} or "/" in value or "\\" in value:
        raise SystemExit(f"Invalid ledger id: {value}")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value):
        raise SystemExit(f"Invalid ledger id: {value}")
    return value


def index_path(base_dir: str | Path = ".complex-problems") -> Path:
    return Path(base_dir) / "INDEX.json"


def load_workspace_index(base_dir: str | Path = ".complex-problems") -> dict[str, Any]:
    path = index_path(base_dir)
    if not path.exists():
        return {"active_ledger_id": None, "ledgers": []}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_workspace_index(base_dir: str | Path, index: dict[str, Any]) -> None:
    root = Path(base_dir)
    root.mkdir(parents=True, exist_ok=True)
    index["updated_at"] = now_iso()
    tmp = root / "INDEX.json.tmp"
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    tmp.replace(root / "INDEX.json")


def ledger_summary(ledger: Path, state: dict[str, Any] | None = None) -> dict[str, Any]:
    state = state or load_state(ledger)
    root = state["problems"][state["root_id"]]
    active = [p for p in state["problems"].values() if p["status"] in {"todo", "doing", "checking", "followup"}]
    blocked = [p for p in state["problems"].values() if p["status"] == "blocked"]
    done = [p for p in state["problems"].values() if p["status"] == "done"]
    status = "blocked" if blocked else ("done" if len(done) == len(state["problems"]) else "doing")
    return {
        "ledger_id": state["ledger_id"],
        "schema_version": state["schema_version"],
        "root_id": state["root_id"],
        "title": root["title"],
        "status": status,
        "path": ledger.name,
        "updated_at": state.get("updated_at"),
        "active_count": len(active),
        "blocked_count": len(blocked),
    }


def ledger_dirs(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted([p for p in root.iterdir() if p.is_dir() and (p / "state.json").exists()])


def supported_ledger_dirs(root: Path) -> list[Path]:
    ledgers = []
    for ledger in ledger_dirs(root):
        try:
            load_state(ledger)
        except SystemExit:
            continue
        ledgers.append(ledger)
    return ledgers


def update_workspace_index_for_ledger(ledger: Path, set_active: bool = False) -> None:
    base_dir = ledger.parent
    index = load_workspace_index(base_dir)
    summary = ledger_summary(ledger)
    ledgers = [item for item in index.get("ledgers", []) if item.get("ledger_id") != summary["ledger_id"]]
    ledgers.append(summary)
    ledgers.sort(key=lambda item: item.get("updated_at") or "")
    index["ledgers"] = ledgers
    if set_active or not index.get("active_ledger_id"):
        index["active_ledger_id"] = summary["ledger_id"]
    save_workspace_index(base_dir, index)


def resolve_ledger(path: str | None, base_dir: str = ".complex-problems") -> Path:
    if path:
        ledger = Path(path)
    else:
        root = Path(base_dir)
        if not root.exists():
            raise SystemExit(f"No ledger directory found at {root}")
        index = load_workspace_index(root)
        active_id = index.get("active_ledger_id")
        if active_id:
            ledger = root / active_id
            if (ledger / "state.json").exists():
                try:
                    load_state(ledger)
                except SystemExit:
                    ledgers = supported_ledger_dirs(root)
                    if not ledgers:
                        raise
                    ledger = ledgers[-1]
                    index["active_ledger_id"] = ledger.name
                    save_workspace_index(root, index)
            else:
                ledgers = supported_ledger_dirs(root)
                if not ledgers:
                    raise SystemExit(f"Active ledger {active_id} is missing and no supported ledger sessions exist under {root}")
                ledger = ledgers[-1]
                index["active_ledger_id"] = ledger.name
                save_workspace_index(root, index)
        else:
            ledgers = supported_ledger_dirs(root)
            if not ledgers:
                raise SystemExit(f"No supported ledger sessions found under {root}")
            ledger = ledgers[-1]
    if not (ledger / "state.json").exists():
        raise SystemExit(f"Not a ledger path: {ledger}")
    return ledger


def load_state(ledger: Path) -> dict[str, Any]:
    state_path = ledger / "state.json"
    try:
        with state_path.open("r", encoding="utf-8") as f:
            state = json.load(f)
    except FileNotFoundError:
        raise SystemExit(f"state.json not found: {state_path}")
    except json.JSONDecodeError as e:
        raise SystemExit(f"state.json is corrupted or not valid JSON: {state_path}\n{e}")
    except OSError as e:
        raise SystemExit(f"Cannot read state.json: {state_path}\n{e}")
    if state.get("schema_version") != SCHEMA_VERSION:
        version = state.get("schema_version")
        raise SystemExit(f"Unsupported ledger schema_version {version}; this script only supports schema_version {SCHEMA_VERSION}")
    state.pop("status", None)
    lang = state.get("language", "en")
    if lang and lang != "en":
        set_language(lang)
    return state


def save_state(ledger: Path, state: dict[str, Any]) -> None:
    state.pop("status", None)
    state["updated_at"] = now_iso()
    tmp = ledger / f"state.json.tmp.{os.getpid()}"
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    tmp.replace(ledger / "state.json")


@contextlib.contextmanager
def locked_state(ledger: Path):
    """Acquire an exclusive file lock, then yield state for the caller
    to read and modify. State is saved only if the block succeeds."""
    lock_path = ledger / "state.json.lock"
    if _HAS_FCNTL:
        with lock_path.open("w") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            state = load_state(ledger)
            success = False
            try:
                yield state
                success = True
            finally:
                if success:
                    save_state(ledger, state)
    else:
        state = load_state(ledger)
        success = False
        try:
            yield state
            success = True
        finally:
            if success:
                save_state(ledger, state)


def append_event(ledger: Path, state: dict[str, Any], event_type: str, payload: dict[str, Any]) -> str:
    event_id = next_id(state, "E")
    event = {
        "id": event_id,
        "type": event_type,
        "at": now_iso(),
        "root_id": state["root_id"],
        "payload": payload,
    }
    with (ledger / "events.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    return event_id


def transition_problem(ledger: Path, state: dict[str, Any], problem_id: str, status: str) -> None:
    problem = state["problems"][problem_id]
    old = problem["status"]
    if old == status:
        return
    if status not in PROBLEM_TRANSITIONS.get(old, set()):
        raise SystemExit(err_msg("illegal_transition", kind="problem", id=problem_id, old=old, new=status))
    problem["status"] = status
    problem["updated_at"] = now_iso()
    append_event(ledger, state, "problem_status_changed", {"id": problem_id, "from": old, "to": status})


def transition_ticket(ledger: Path, state: dict[str, Any], ticket_id: str, status: str) -> None:
    ticket = state["tickets"][ticket_id]
    old = ticket["status"]
    if old == status:
        return
    if status == "executing" and ticket.get("classification") != "one_go":
        raise SystemExit(f"Ticket {ticket_id} can enter executing only when classification is one_go")
    if status == "splitting" and ticket.get("classification") != "split":
        raise SystemExit(f"Ticket {ticket_id} can enter splitting only when classification is split")
    if status not in TICKET_TRANSITIONS.get(old, set()):
        raise SystemExit(f"Illegal ticket transition for {ticket_id}: {old} -> {status}")
    ticket["status"] = status
    ticket["updated_at"] = now_iso()
    append_event(ledger, state, "ticket_status_changed", {"id": ticket_id, "from": old, "to": status})


def define_ticket_if_ready(ledger: Path, state: dict[str, Any], ticket_id: str) -> None:
    ticket = state["tickets"][ticket_id]
    if ticket["status"] == "created" and ticket.get("problem_definition") and ticket.get("proposed_solution") and ticket.get("acceptance_criteria") and ticket.get("verification_plan"):
        transition_ticket(ledger, state, ticket_id, "defined")


def require_fields(args: argparse.Namespace, fields: list[str], status: str) -> None:
    missing = []
    for field in fields:
        value = getattr(args, field)
        if value is None or value == [] or value == "":
            missing.append("--" + field.replace("_", "-"))
    if missing:
        raise SystemExit(f"{status} check requires: {', '.join(missing)}")


def read_body_file(path: str | None) -> str | None:
    if not path:
        return None
    source = Path(path)
    if not source.exists():
        raise SystemExit(f"Body file not found: {source}")
    return source.read_text(encoding="utf-8")


def require_body_file(path: str | None, command: str) -> str:
    if not path:
        raise SystemExit(f"{command} requires --from-file")
    return read_body_file(path) or ""


def section(text: str, heading: str) -> str:
    pattern = re.compile(rf"^##\s+{re.escape(heading)}\s*$", re.MULTILINE | re.IGNORECASE)
    match = pattern.search(text)
    if not match:
        return ""
    next_heading = re.search(r"^##\s+", text[match.end():], re.MULTILINE)
    end = match.end() + next_heading.start() if next_heading else len(text)
    return text[match.end():end].strip()


def lines_from_section(text: str, heading: str) -> list[str]:
    value = section(text, heading)
    if not value:
        return []
    lines = []
    for line in value.splitlines():
        item = re.sub(r"^\s*[-*]\s+", "", line).strip()
        if item:
            lines.append(item)
    return lines


def gap_lines_from_section(text: str, heading: str) -> list[str]:
    lines = lines_from_section(text, heading)
    if len(lines) == 1 and lines[0].lower() in {"none", "no known gaps", "no blocking gaps", "无", "无缺口"}:
        return []
    return lines


def first_line(text: str) -> str:
    for line in text.splitlines():
        line = re.sub(r"^#\s+", "", line).strip()
        if line:
            return line
    return ""


def first_heading(text: str) -> str:
    for line in text.splitlines():
        match = re.match(r"^#\s+(.+?)\s*$", line)
        if match:
            return match.group(1).strip()
    return ""


def problem_fields_from_body(body_text: str, command: str) -> tuple[str, str, list[str]]:
    title = first_heading(body_text)
    description = section(body_text, "Problem")
    criteria = lines_from_section(body_text, "Success Criteria")
    missing = []
    if not title:
        missing.append("# title")
    if not description:
        missing.append("## Problem")
    if not criteria:
        missing.append("## Success Criteria")
    if missing:
        raise SystemExit(f"{command} body missing: {', '.join(missing)}")
    return title, description, criteria


def problem_fields_from_file(path: str | None, command: str) -> tuple[str, str, list[str], str]:
    body_text = require_body_file(path, command)
    title, description, criteria = problem_fields_from_body(body_text, command)
    return title, description, criteria, body_text


def write_body(ledger: Path, rel_path: str, content: str) -> str:
    path = ledger / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")
    return rel_path


def problem_body(title: str, description: str, criteria: list[str]) -> str:
    return "\n".join([
        f"# {title}",
        "",
        "## Problem",
        description,
        "",
        "## Success Criteria",
        bullet(criteria),
        "",
    ])


def ensure_problem_package(ledger: Path, package_path: str) -> None:
    package = ledger / package_path
    for name in ("tickets", "results", "checks", "children"):
        (package / name).mkdir(parents=True, exist_ok=True)


def root_package_path(problem_id: str) -> str:
    return f"problems/{problem_id}"


def problem_package_path(state: dict[str, Any], problem_id: str) -> str:
    problem = state["problems"][problem_id]
    package_path = problem.get("package_path")
    if not package_path:
        raise SystemExit(f"Problem {problem_id} is missing package_path")
    return package_path


def child_package_path(state: dict[str, Any], parent_id: str, problem_id: str) -> str:
    return f"{problem_package_path(state, parent_id)}/children/{problem_id}"


def problem_body_path(package_path: str) -> str:
    return f"{package_path}/README.md"


def ticket_body_path(state: dict[str, Any], problem_id: str, ticket_id: str) -> str:
    return f"{problem_package_path(state, problem_id)}/tickets/{ticket_id}.md"


def result_body_path(state: dict[str, Any], problem_id: str, result_id: str) -> str:
    return f"{problem_package_path(state, problem_id)}/results/{result_id}.md"


def check_body_path(state: dict[str, Any], problem_id: str, check_id: str) -> str:
    return f"{problem_package_path(state, problem_id)}/checks/{check_id}.md"


def ticket_body(title: str, problem_definition: str, proposed_solution: str, acceptance_criteria: list[str], verification_plan: str, risks: list[str], assumptions: list[str]) -> str:
    return "\n".join([
        f"# {title}",
        "",
        "## Problem Definition",
        problem_definition,
        "",
        "## Proposed Solution",
        proposed_solution,
        "",
        "## Acceptance Criteria",
        bullet(acceptance_criteria),
        "",
        "## Verification Plan",
        verification_plan,
        "",
        "## Risks",
        bullet(risks),
        "",
        "## Assumptions",
        bullet(assumptions),
        "",
    ])


def result_body(title: str, summary: str, done: list[str], verification: list[str], gaps: list[str], artifacts: list[str]) -> str:
    return "\n".join([
        f"# {title}",
        "",
        "## Summary",
        summary,
        "",
        "## Done",
        bullet(done),
        "",
        "## Verification",
        bullet(verification),
        "",
        "## Known Gaps",
        bullet(gaps),
        "",
        "## Artifacts",
        bullet(artifacts),
        "",
    ])


def check_body(title: str, summary: str, evidence: list[str], criteria_map: list[str], execution_map: list[str], stress_test: list[str], residual_risk: list[str], result_ids: list[str], gaps: list[str]) -> str:
    return "\n".join([
        f"# {title}",
        "",
        "## Summary",
        summary,
        "",
        "## Evidence",
        bullet(evidence),
        "",
        "## Criteria Map",
        bullet(criteria_map),
        "",
        "## Execution Map",
        bullet(execution_map),
        "",
        "## Stress Test",
        bullet(stress_test),
        "",
        "## Residual Risk",
        bullet(residual_risk),
        "",
        "## Result IDs",
        bullet(result_ids),
        "",
        "## Blocking Gaps",
        bullet(gaps),
        "",
    ])


def prepare_problem_for_check(ledger: Path, state: dict[str, Any], problem_id: str) -> None:
    status = state["problems"][problem_id]["status"]
    if status == "todo":
        transition_problem(ledger, state, problem_id, "doing")
        transition_problem(ledger, state, problem_id, "checking")
    elif status in {"doing", "followup"}:
        transition_problem(ledger, state, problem_id, "checking")
    elif status == "blocked":
        transition_problem(ledger, state, problem_id, "doing")
        transition_problem(ledger, state, problem_id, "checking")


def ensure_dirs(ledger: Path) -> None:
    for name in ("views", "artifacts", "problems"):
        (ledger / name).mkdir(parents=True, exist_ok=True)


def bullet(items: list[str]) -> str:
    if not items:
        return "- none"
    return "\n".join(f"- {item}" for item in items)


def md_escape(text: str) -> str:
    return text.replace("\n", " ").strip()


def init_cmd(args: argparse.Namespace) -> None:
    root_dir = Path(args.dir)
    body_title, body_description, body_criteria, body_text = problem_fields_from_file(args.from_file, "init")
    args.title = args.title or body_title
    args.description = args.description or body_description
    args.criteria = args.criteria or body_criteria
    lid = validate_ledger_id(args.ledger_id) if args.ledger_id else ledger_id()
    ledger = root_dir / lid
    if ledger.exists():
        raise SystemExit(f"Ledger already exists: {ledger}")
    ensure_dirs(ledger)
    root_id = "P000"
    root_package = root_package_path(root_id)
    root_body = problem_body_path(root_package)
    ensure_problem_package(ledger, root_package)
    state = {
        "schema_version": SCHEMA_VERSION,
        "ledger_id": lid,
        "root_id": root_id,
        "effort": args.effort or "medium",
        "language": args.language or "en",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "counters": {"problem": 1, "ticket": 0, "result": 0, "check": 0, "event": 0},
        "problems": {
            root_id: {
                "id": root_id,
                "root_id": root_id,
                "parent_id": None,
                "created_from_check_id": None,
                "created_from_ticket_id": None,
                "created_from_ticket_mode": None,
                "title": args.title,
                "description": args.description or args.title,
                "status": "todo",
                "success_criteria": args.criteria or [],
                "package_path": root_package,
                "body_path": root_body,
                "ticket_ids": [],
                "subproblem_ids": [],
                "result_ids": [],
                "check_ids": [],
                "followup_ids": [],
                "created_at": now_iso(),
                "updated_at": now_iso(),
            }
        },
        "tickets": {},
        "results": {},
        "checks": {},
    }
    write_body(ledger, root_body, body_text)
    append_event(ledger, state, "ledger_initialized", {"ledger_id": lid, "root_id": root_id, "title": args.title})
    save_state(ledger, state)
    render(ledger, state)
    update_workspace_index_for_ledger(ledger, set_active=True)
    print(str(ledger))


def create_problem_cmd(args: argparse.Namespace) -> None:
    ledger = resolve_ledger(args.ledger)
    body_title, body_description, body_criteria, body_text = problem_fields_from_file(args.from_file, "create-problem")
    args.title = args.title or body_title
    args.description = args.description or body_description
    args.criteria = args.criteria or body_criteria
    with locked_state(ledger) as state:
        parent_id = args.parent or state["root_id"]
        if parent_id not in state["problems"]:
            raise SystemExit(f"Unknown parent problem: {parent_id}")
        if not args.from_ticket:
            raise SystemExit("create-problem requires --from-ticket; follow-ups are created by check --status not_success --followup-from-file")
        if not args.mode:
            raise SystemExit("create-problem with --from-ticket requires --mode split or --mode spawn")
        if args.mode not in CREATED_FROM_TICKET_MODES:
            raise SystemExit(f"Invalid create-problem mode: {args.mode}")
        if args.from_ticket and args.from_ticket not in state["tickets"]:
            raise SystemExit(f"Unknown source ticket: {args.from_ticket}")
        if args.from_ticket:
            source_ticket = state["tickets"][args.from_ticket]
            if source_ticket["problem_id"] != parent_id:
                raise SystemExit(f"Source ticket {args.from_ticket} belongs to {source_ticket['problem_id']}, not parent {parent_id}")
            if args.mode == "split":
                if source_ticket.get("classification") != "split":
                    raise SystemExit(f"Source ticket {args.from_ticket} must be classified as split before creating split subproblems from it")
                if source_ticket.get("status") != "splitting":
                    raise SystemExit(f"Source ticket {args.from_ticket} must be in splitting status before creating split subproblems from it")
            if args.mode == "spawn":
                if state["problems"][parent_id].get("status") not in {"doing", "followup"}:
                    raise SystemExit(f"Parent problem {parent_id} must be doing or followup before spawning runtime subproblems")
                if source_ticket.get("classification") != "one_go":
                    raise SystemExit(f"Source ticket {args.from_ticket} must be classified as one_go before spawning runtime subproblems from it")
                if source_ticket.get("status") != "executing":
                    raise SystemExit(f"Source ticket {args.from_ticket} must be in executing status before spawning runtime subproblems from it")
        pid = next_id(state, "P")
        package_path = child_package_path(state, parent_id, pid)
        body_path = problem_body_path(package_path)
        ensure_problem_package(ledger, package_path)
        problem = {
            "id": pid,
            "root_id": state["root_id"],
            "parent_id": parent_id,
            "created_from_check_id": None,
            "created_from_ticket_id": args.from_ticket,
            "created_from_ticket_mode": args.mode,
            "title": args.title,
            "description": args.description or args.title,
            "status": "todo",
            "success_criteria": args.criteria or [],
            "package_path": package_path,
            "body_path": body_path,
            "ticket_ids": [],
            "subproblem_ids": [],
            "result_ids": [],
            "check_ids": [],
            "followup_ids": [],
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        state["problems"][pid] = problem
        write_body(ledger, body_path, body_text)
        state["problems"][parent_id]["subproblem_ids"].append(pid)
        append_event(ledger, state, "problem_created", {"problem_id": pid, "parent_id": parent_id, "title": args.title, "source": args.mode})
    render(ledger, state)
    update_workspace_index_for_ledger(ledger)
    print(pid)


def create_ticket_cmd(args: argparse.Namespace) -> None:
    ledger = resolve_ledger(args.ledger)
    body_text = require_body_file(args.from_file, "create-ticket")
    args.title = args.title or first_heading(body_text)
    args.problem_definition = args.problem_definition or section(body_text, "Problem Definition")
    args.proposed_solution = args.proposed_solution or section(body_text, "Proposed Solution")
    args.acceptance_criteria = args.acceptance_criteria or lines_from_section(body_text, "Acceptance Criteria")
    args.verification_plan = args.verification_plan or section(body_text, "Verification Plan")
    args.risk = args.risk or lines_from_section(body_text, "Risks")
    args.assumption = args.assumption or lines_from_section(body_text, "Assumptions")
    missing = []
    if not first_heading(body_text):
        missing.append("# title")
    for attr, flag in (
        ("problem_definition", "--problem-definition"),
        ("proposed_solution", "--proposed-solution"),
        ("acceptance_criteria", "--acceptance-criteria"),
        ("verification_plan", "--verification-plan"),
    ):
        if not getattr(args, attr):
            missing.append(flag)
    if missing:
        raise SystemExit(f"create-ticket body missing: {', '.join(missing)}")
    if not args.title:
        raise SystemExit("create-ticket body missing: # title")
    with locked_state(ledger) as state:
        if args.problem not in state["problems"]:
            raise SystemExit(f"Unknown problem: {args.problem}")
        problem = state["problems"][args.problem]
        if problem["ticket_ids"]:
            raise SystemExit(f"Problem {args.problem} already has ticket {problem['ticket_ids'][-1]}; create a new problem or explicit follow-up instead")
        tid = next_id(state, "T")
        body_path = ticket_body_path(state, args.problem, tid)
        ticket = {
            "id": tid,
            "root_id": state["root_id"],
            "problem_id": args.problem,
            "title": args.title,
            "status": "created",
            "classification": None,
            "classification_reason": "",
            "problem_definition": args.problem_definition or args.title,
            "proposed_solution": args.proposed_solution or "",
            "acceptance_criteria": args.acceptance_criteria or [],
            "verification_plan": args.verification_plan or "",
            "risks": args.risk or [],
            "assumptions": args.assumption or [],
            "body_path": body_path,
            "result_ids": [],
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        state["tickets"][tid] = ticket
        state["problems"][args.problem]["ticket_ids"].append(tid)
        write_body(ledger, body_path, body_text)
        append_event(ledger, state, "ticket_created", {"ticket_id": tid, "problem_id": args.problem, "title": args.title})
        define_ticket_if_ready(ledger, state, tid)
    render(ledger, state)
    update_workspace_index_for_ledger(ledger)
    print(tid)


def classify_ticket_cmd(args: argparse.Namespace) -> None:
    ledger = resolve_ledger(args.ledger)
    with locked_state(ledger) as state:
        if args.ticket not in state["tickets"]:
            raise SystemExit(f"Unknown ticket: {args.ticket}")
        if args.classification not in TICKET_CLASSIFICATIONS:
            raise SystemExit(f"Invalid classification: {args.classification}")
        ticket = state["tickets"][args.ticket]
        if ticket["status"] == "created":
            define_ticket_if_ready(ledger, state, args.ticket)
        if ticket["status"] != "defined":
            raise SystemExit(f"Ticket {args.ticket} must be defined before classification; current status is {ticket['status']}")
        ticket["classification"] = args.classification
        ticket["classification_reason"] = args.reason
        ticket["updated_at"] = now_iso()
        transition_ticket(ledger, state, args.ticket, "classified")
        append_event(ledger, state, "ticket_classified", {"ticket_id": args.ticket, "classification": args.classification, "reason": args.reason or ""})
    render(ledger, state)
    update_workspace_index_for_ledger(ledger)
    print(f"{args.ticket} -> {args.classification}")


def set_status_cmd(args: argparse.Namespace) -> None:
    ledger = resolve_ledger(args.ledger)
    with locked_state(ledger) as state:
        collection = "problems" if args.kind == "problem" else "tickets"
        allowed = PROBLEM_STATUSES if args.kind == "problem" else TICKET_STATUSES
        if args.status not in allowed:
            raise SystemExit(f"Invalid {args.kind} status: {args.status}")
        if args.id not in state[collection]:
            raise SystemExit(f"Unknown {args.kind}: {args.id}")
        if args.kind == "problem":
            if args.status != "doing":
                raise SystemExit(err_msg("set_status_problem_only_doing"))
            transition_problem(ledger, state, args.id, args.status)
        else:
            if args.status not in {"executing", "splitting"}:
                raise SystemExit(err_msg("set_status_ticket_only_executing_splitting"))
            transition_ticket(ledger, state, args.id, args.status)
    render(ledger, state)
    update_workspace_index_for_ledger(ledger)
    print(f"{args.id} -> {args.status}")


def result_cmd(args: argparse.Namespace) -> None:
    ledger = resolve_ledger(args.ledger)
    body_text = require_body_file(args.from_file, "result")
    if not first_heading(body_text):
        raise SystemExit("result body missing: # title")
    args.summary = args.summary or section(body_text, "Summary")
    args.done = args.done or lines_from_section(body_text, "Done")
    args.verification = args.verification or lines_from_section(body_text, "Verification")
    args.gap = args.gap or gap_lines_from_section(body_text, "Known Gaps")
    args.artifact = args.artifact or lines_from_section(body_text, "Artifacts")
    if not args.summary:
        raise SystemExit("result body missing: ## Summary")
    with locked_state(ledger) as state:
        if args.ticket not in state["tickets"]:
            raise SystemExit(err_msg("unknown_ticket", id=args.ticket))
        ticket = state["tickets"][args.ticket]
        problem = state["problems"][ticket["problem_id"]]
        if problem["status"] == "todo":
            raise SystemExit(err_msg("problem_must_be_doing", id=problem['id']))
        if problem["status"] in {"done", "blocked"}:
            raise SystemExit(err_msg("cannot_record_result", tid=args.ticket, pid=problem['id'], status=problem['status']))
        if ticket["status"] == "classified":
            if ticket.get("classification") == "one_go":
                transition_ticket(ledger, state, args.ticket, "executing")
            elif ticket.get("classification") == "split":
                transition_ticket(ledger, state, args.ticket, "splitting")
            else:
                raise SystemExit(f"Ticket {args.ticket} is classified without a valid classification")
        elif ticket["status"] not in {"executing", "splitting"}:
            raise SystemExit(f"Cannot record result for ticket {args.ticket} while status is {ticket['status']}")
        if ticket["status"] == "splitting":
            child_ids = child_problem_ids_from_ticket(state, args.ticket)
            if not child_ids:
                raise SystemExit(f"Cannot finish split ticket {args.ticket}; create at least one child problem first")
        child_ids = child_problem_ids_from_ticket(state, args.ticket)
        open_children = [
            child_id
            for child_id in child_ids
            if state["problems"][child_id].get("status") != "done"
        ]
        if open_children:
            raise SystemExit(f"Cannot finish ticket {args.ticket}; child problems still open: {', '.join(open_children)}")
        rid = next_id(state, "R")
        body_path = result_body_path(state, ticket["problem_id"], rid)
        result = {
            "id": rid,
            "root_id": state["root_id"],
            "ticket_id": args.ticket,
            "problem_id": ticket["problem_id"],
            "summary": args.summary,
            "done": args.done or [],
            "verification": args.verification or [],
            "known_gaps": args.gap or [],
            "artifacts": args.artifact or [],
            "body_path": body_path,
            "created_at": now_iso(),
        }
        state["results"][rid] = result
        write_body(ledger, body_path, body_text)
        ticket["result_ids"].append(rid)
        transition_ticket(ledger, state, args.ticket, "done")
        problem["result_ids"].append(rid)
        append_event(ledger, state, "result_recorded", {"result_id": rid, "ticket_id": args.ticket})
    render(ledger, state)
    update_workspace_index_for_ledger(ledger)
    print(rid)


def check_cmd(args: argparse.Namespace) -> None:
    ledger = resolve_ledger(args.ledger)
    if args.status not in CHECK_STATUSES:
        raise SystemExit(f"Invalid check status: {args.status}")
    body_text = require_body_file(args.from_file, "check")
    if not first_heading(body_text):
        raise SystemExit("check body missing: # title")
    args.summary = args.summary or section(body_text, "Summary")
    args.evidence = args.evidence or lines_from_section(body_text, "Evidence")
    args.criteria_map = args.criteria_map or lines_from_section(body_text, "Criteria Map")
    args.execution_map = args.execution_map or lines_from_section(body_text, "Execution Map")
    args.stress_test = args.stress_test or lines_from_section(body_text, "Stress Test")
    args.residual_risk = args.residual_risk or lines_from_section(body_text, "Residual Risk")
    args.result_ids = args.result_ids or lines_from_section(body_text, "Result IDs")
    args.gap = args.gap or gap_lines_from_section(body_text, "Blocking Gaps")
    checked_result_ids = args.result_ids or []
    if args.status == "success":
        require_fields(args, ["summary", "evidence", "criteria_map", "execution_map", "stress_test", "residual_risk"], "success")
    elif args.status == "not_success":
        require_fields(args, ["summary", "gap", "followup_from_file"], "not_success")
    else:
        require_fields(args, ["summary", "gap"], "blocked")
    followup_title = followup_description = followup_criteria = followup_body_text = None
    if args.status == "not_success":
        followup_title, followup_description, followup_criteria, followup_body_text = problem_fields_from_file(args.followup_from_file, "check --status not_success follow-up")
        args.followup_title = args.followup_title or followup_title
        args.followup_description = args.followup_description or followup_description
        args.followup_criteria = args.followup_criteria or followup_criteria
    with locked_state(ledger) as state:
        if args.problem not in state["problems"]:
            raise SystemExit(f"Unknown problem: {args.problem}")
        problem = state["problems"][args.problem]
        if problem["status"] == "todo":
            raise SystemExit(f"Problem {args.problem} must be doing or followup before check_success")
        if problem["status"] == "done":
            raise SystemExit(f"Problem {args.problem} is already done; create an explicit new problem instead of reopening it through check")
        if args.status in {"success", "not_success"} and not checked_result_ids:
            raise SystemExit(f"{args.status} check requires at least one --result")
        for result_id in checked_result_ids:
            result = state["results"].get(result_id)
            if not result:
                raise SystemExit(f"Unknown result for check_success: {result_id}")
            if result_id not in result_ids_for_check_context(state, args.problem):
                raise SystemExit(f"Result {result_id} is not in problem {args.problem}'s result_with_followups context")
        if args.status == "success":
            if not problem["ticket_ids"]:
                raise SystemExit(f"Cannot close problem {args.problem}; every problem must have a ticket before check_success")
            for tid in problem["ticket_ids"]:
                if state["tickets"][tid]["status"] != "done":
                    raise SystemExit(f"Cannot close problem {args.problem}; ticket {tid} is {state['tickets'][tid]['status']}")
            open_children = open_child_problem_ids(state, problem)
            if open_children:
                raise SystemExit(f"Cannot close problem {args.problem}; child problems still open: {', '.join(open_children)}")
        elif args.status == "not_success":
            open_followups = open_child_problem_ids(state, problem)
            if open_followups:
                raise SystemExit(f"Cannot create another follow-up for {args.problem}; solve open follow-up/child problems first: {', '.join(open_followups)}")
        prepare_problem_for_check(ledger, state, args.problem)
        cid = next_id(state, "C")
        followup_id = None
        if args.status == "not_success":
            followup_id = next_id(state, "P")
            followup_package = child_package_path(state, args.problem, followup_id)
            followup_body = problem_body_path(followup_package)
            ensure_problem_package(ledger, followup_package)
            followup = {
                "id": followup_id,
                "root_id": state["root_id"],
                "parent_id": args.problem,
                "created_from_check_id": cid,
                "created_from_ticket_id": None,
                "created_from_ticket_mode": None,
                "title": args.followup_title,
                "description": args.followup_description or args.followup_title,
                "status": "followup",
                "success_criteria": args.followup_criteria or [],
                "ticket_ids": [],
                "subproblem_ids": [],
                "result_ids": [],
                "check_ids": [],
                "followup_ids": [],
                "created_at": now_iso(),
                "updated_at": now_iso(),
                "package_path": followup_package,
                "body_path": followup_body,
            }
            state["problems"][followup_id] = followup
            write_body(ledger, followup["body_path"], followup_body_text)
            state["problems"][args.problem]["followup_ids"].append(followup_id)
            state["problems"][args.problem]["subproblem_ids"].append(followup_id)
        body_path = check_body_path(state, args.problem, cid)
        check = {
            "id": cid,
            "root_id": state["root_id"],
            "problem_id": args.problem,
            "status": args.status,
            "evidence": args.evidence or [],
            "criteria_map": args.criteria_map or [],
            "execution_map": args.execution_map or [],
            "stress_test": args.stress_test or [],
            "residual_risk": args.residual_risk or [],
            "result_ids": checked_result_ids,
            "blocking_gaps": args.gap or [],
            "followup_problem_id": followup_id,
            "summary": args.summary or "",
            "body_path": body_path,
            "created_at": now_iso(),
        }
        state["checks"][cid] = check
        write_body(ledger, body_path, body_text)
        problem["check_ids"].append(cid)
        if args.status == "success":
            transition_problem(ledger, state, args.problem, "done")
        elif args.status == "blocked":
            transition_problem(ledger, state, args.problem, "blocked")
        else:
            transition_problem(ledger, state, args.problem, "followup")
        problem["updated_at"] = now_iso()
        append_event(ledger, state, "check_recorded", {"check_id": cid, "problem_id": args.problem, "status": args.status, "followup_id": followup_id})
    render(ledger, state)
    update_workspace_index_for_ledger(ledger)
    print(cid if not followup_id else f"{cid} followup={followup_id}")


def render_problem_tree(state: dict[str, Any], pid: str, depth: int = 0) -> list[str]:
    p = state["problems"][pid]
    indent = "  " * depth
    lines = [f"{indent}- [{p['status']}] {pid}: {p['title']}"]
    for child in p["subproblem_ids"]:
        if child in state["problems"]:
            lines.extend(render_problem_tree(state, child, depth + 1))
    return lines


def problem_depth(state: dict[str, Any], problem_id: str) -> int:
    depth = 0
    current = state["problems"][problem_id]
    while current.get("parent_id"):
        depth += 1
        current = state["problems"][current["parent_id"]]
    return depth


def latest_check_status(state: dict[str, Any], problem: dict[str, Any]) -> str | None:
    if not problem.get("check_ids"):
        return None
    check_id = problem["check_ids"][-1]
    check = state["checks"].get(check_id)
    return check.get("status") if check else None


def has_open_children(state: dict[str, Any], problem: dict[str, Any]) -> bool:
    for child_id in problem.get("subproblem_ids", []):
        child = state["problems"].get(child_id)
        if child and child.get("status") in OPEN_PROBLEM_STATUSES:
            return True
    return False


def is_open_problem(problem: dict[str, Any]) -> bool:
    return problem.get("status") in OPEN_PROBLEM_STATUSES


def is_runnable_frontier_problem(state: dict[str, Any], problem: dict[str, Any]) -> bool:
    return is_open_problem(problem) and not has_open_children(state, problem)


def child_problem_ids_from_ticket(state: dict[str, Any], ticket_id: str) -> list[str]:
    return [
        problem["id"]
        for problem in state["problems"].values()
        if problem.get("created_from_ticket_id") == ticket_id
    ]


def open_child_problem_ids(state: dict[str, Any], problem: dict[str, Any]) -> list[str]:
    return [
        child_id
        for child_id in problem.get("subproblem_ids", [])
        if child_id in state["problems"] and state["problems"][child_id].get("status") in OPEN_PROBLEM_STATUSES
    ]


def result_ids_for_check_context(state: dict[str, Any], problem_id: str) -> list[str]:
    problem = state["problems"][problem_id]
    result_ids = list(problem.get("result_ids", []))
    for followup_id in problem.get("followup_ids", []):
        if followup_id in state["problems"]:
            result_ids.extend(result_ids_for_check_context(state, followup_id))
    return result_ids


def primary_ticket(state: dict[str, Any], problem: dict[str, Any]) -> dict[str, Any] | None:
    if not problem.get("ticket_ids"):
        return None
    return state["tickets"].get(problem["ticket_ids"][-1])


WORKER_INSTRUCTION_FILES = {
    "create-solution-ticket": "references/workers/create-solution-ticket.md",
    "define-ticket": "references/workers/define-ticket.md",
    "classify-ticket": "references/workers/classify-ticket.md",
    "execute-ticket": "references/workers/execute-ticket.md",
    "split-ticket": "references/workers/split-ticket.md",
    "record-result": "references/workers/record-result.md",
    "check-success": "references/workers/check-success.md",
    "unblock-or-report": "references/workers/unblock-or-report.md",
    "none": "references/workers/none.md",
}


def next_action_for_problem(state: dict[str, Any], problem: dict[str, Any]) -> tuple[str, str]:
    if problem["status"] == "blocked":
        return "unblock-or-report", "problem is blocked"
    ticket = primary_ticket(state, problem)
    if not ticket:
        return "create-solution-ticket", "problem has no solution ticket"
    if ticket["status"] == "created":
        return "define-ticket", f"ticket {ticket['id']} is created but not fully defined"
    if ticket["status"] == "defined":
        return "classify-ticket", f"ticket {ticket['id']} is defined but not classified"
    if ticket["status"] == "classified":
        if ticket.get("classification") == "one_go":
            return "execute-ticket", f"ticket {ticket['id']} is classified as one_go"
        if ticket.get("classification") == "split":
            return "split-ticket", f"ticket {ticket['id']} is classified as split"
        return "classify-ticket", f"ticket {ticket['id']} has no valid classification"
    if has_open_children(state, problem):
        raise RuntimeError(f"Scheduler selected waiting problem {problem['id']} with open children")
    if ticket["status"] in {"executing", "splitting"}:
        return "record-result", f"ticket {ticket['id']} is {ticket['status']}"
    if ticket["status"] != "done":
        return "record-result", f"ticket {ticket['id']} must produce a result before checking problem success"
    if latest_check_status(state, problem) != "success":
        return "check-success", "problem has results or closed children but no success check"
    return "none", "problem is closed"


def short_instruction(action: str, target: str, objective: str, boundary: str, effort: str = "medium", language: str = "en") -> str:
    worker_file = WORKER_INSTRUCTION_FILES[action]
    hint = effort_hint(action, effort)
    parts = [
        f"Only perform `{action}` for {target}.",
        f"Goal: {objective}.",
        f"Boundary: {boundary}.",
    ]
    if hint:
        parts.append(f"Effort [{effort}]: {hint}")
    parts.append(f"Detailed worker requirements: `{worker_file}`.")
    if language and language != "en":
        parts.append(f"Write all body content (titles, descriptions, summaries, criteria, evidence) in {language}. CLI flags and field names stay in English.")
    parts.append("After this action, run `ledger.py next`.")
    return " ".join(parts)


def instruction_for_next(item: dict[str, Any], effort: str = "medium", language: str = "en") -> tuple[str, list[str]]:
    problem_id = item["problem_id"]
    title = item["title"]
    action = item["next_action"]
    ticket_id = item.get("ticket_id")

    if item["status"] == "complete":
        return (
            "Only perform `none` finalization. Goal: validate, render, status, and summarize the closed ledger. Detailed worker requirements: `references/workers/none.md`.",
            ["ledger.py validate", "ledger.py render", "ledger.py status"],
        )
    result_ids = item.get("available_result_ids") or []
    result_flags = " ".join(f"--result {result_id}" for result_id in result_ids) or "--result R000"
    if action == "create-solution-ticket":
        return (
            short_instruction(
                action,
                f"`{problem_id}: {title}`",
                "create exactly one solution ticket",
                "do not classify, execute, split, record a result, or check success",
                effort, language,
            ),
            [
                f"ledger.py create-ticket --problem {problem_id} --from-file path/to/ticket.md",
                "ledger.py next",
            ],
        )
    if action == "define-ticket":
        return (
            short_instruction(
                action,
                f"`{ticket_id}` on `{problem_id}: {title}`",
                "repair or complete the existing ticket definition",
                "do not add another ticket, classify, execute, split, record a result, or check success",
                effort, language,
            ),
            [
                "ledger.py validate",
            ],
        )
    if action == "classify-ticket":
        return (
            short_instruction(
                action,
                f"`{ticket_id}` on `{problem_id}: {title}`",
                "classify the ticket as `one_go` or `split`",
                "do not execute, split, record a result, or check success",
                effort, language,
            ),
            [
                f"ledger.py classify-ticket {ticket_id} --classification one_go --reason \"...\"",
                f"ledger.py classify-ticket {ticket_id} --classification split --reason \"...\"",
                "ledger.py next",
            ],
        )
    if action == "execute-ticket":
        return (
            short_instruction(
                action,
                f"`{ticket_id}` on `{problem_id}: {title}`",
                "make one bounded execution attempt; either record the actual result or spawn a blocking runtime subproblem if execution discovers one is needed",
                "do not run problem-level check_success; do not create split or follow-up children",
                effort, language,
            ),
            [
                f"ledger.py set-status problem {problem_id} doing",
                f"ledger.py set-status ticket {ticket_id} executing",
                f"ledger.py create-problem --parent {problem_id} --from-ticket {ticket_id} --mode spawn --from-file path/to/spawned-subproblem.md",
                f"ledger.py result --ticket {ticket_id} --from-file path/to/result.md",
                "ledger.py next",
            ],
        )
    if action == "split-ticket":
        return (
            short_instruction(
                action,
                f"`{ticket_id}` on `{problem_id}: {title}`",
                "move the ticket to splitting and create child problem bodies",
                "do not solve children, record the parent result, or check the parent",
                effort, language,
            ),
            [
                f"ledger.py set-status ticket {ticket_id} splitting",
                f"ledger.py create-problem --parent {problem_id} --from-ticket {ticket_id} --mode split --from-file path/to/subproblem.md",
                "ledger.py next",
            ],
        )
    if action == "record-result":
        return (
            short_instruction(
                action,
                f"ticket `{ticket_id}`",
                "record the current ticket result body",
                "do not judge problem success or create follow-ups",
                effort, language,
            ),
            [
                f"ledger.py set-status problem {problem_id} doing",
                f"ledger.py result --ticket {ticket_id} --from-file path/to/result.md",
                "ledger.py next",
            ],
        )
    if action == "check-success":
        return (
            short_instruction(
                action,
                f"`{problem_id}: {title}`",
                "judge whether cited results solve the original problem",
                "do not perform new implementation work; create at most one follow-up if not successful",
                effort, language,
            ),
            [
                f"ledger.py check --problem {problem_id} --status success {result_flags} --from-file path/to/check.md",
                f"ledger.py check --problem {problem_id} --status not_success {result_flags} --from-file path/to/check.md --followup-from-file path/to/followup.md",
            ],
        )
    if action == "unblock-or-report":
        return (
            short_instruction(
                action,
                f"`{problem_id}: {title}`",
                "report the blocker or confirm it is resolved",
                "do not invent ticket-level blocked states or skip into execution",
                effort, language,
            ),
            [f"ledger.py set-status problem {problem_id} doing"],
        )
    return ("No next action is required.", [])


def select_next(state: dict[str, Any]) -> dict[str, Any]:
    effort = state.get("effort", "medium")
    language = state.get("language", "en")
    problems = state["problems"]
    open_problems = [
        p for p in problems.values()
        if is_open_problem(p)
    ]
    if not open_problems:
        root = problems[state["root_id"]]
        item = {
            "status": "complete",
            "schema_version": state["schema_version"],
            "ledger_id": state["ledger_id"],
            "root_id": state["root_id"],
            "problem_id": root["id"],
            "title": root["title"],
            "problem_status": root["status"],
            "next_action": "none",
            "reason": "no open problems remain",
        }
        instruction, commands = instruction_for_next(item, effort, language)
        item["next_instruction"] = instruction
        item["commands"] = commands
        return item

    def sort_key(problem: dict[str, Any]) -> tuple[int, int, str]:
        status_rank = {"doing": 0, "followup": 1, "todo": 2, "checking": 3, "blocked": 4}
        return (status_rank.get(problem["status"], 9), -problem_depth(state, problem["id"]), problem["id"])

    runnable_problems = [
        p for p in open_problems
        if is_runnable_frontier_problem(state, p)
    ]
    if not runnable_problems:
        raise SystemExit("No runnable frontier problem found; open problems appear to be waiting on each other")
    problem = sorted(runnable_problems, key=sort_key)[0]
    action, reason = next_action_for_problem(state, problem)
    ticket = primary_ticket(state, problem)
    ticket_id = ticket["id"] if ticket else None
    item = {
        "status": "next",
        "schema_version": state["schema_version"],
        "ledger_id": state["ledger_id"],
        "root_id": state["root_id"],
        "problem_id": problem["id"],
        "title": problem["title"],
        "problem_status": problem["status"],
        "ticket_id": ticket_id,
        "available_result_ids": result_ids_for_check_context(state, problem["id"]),
        "next_action": action,
        "reason": reason,
    }
    instruction, commands = instruction_for_next(item, effort, language)
    item["next_instruction"] = instruction
    item["effort"] = effort
    item["commands"] = commands
    return item


def render(ledger: Path, state: dict[str, Any] | None = None) -> None:
    state = state or load_state(ledger)
    views = ledger / "views"
    views.mkdir(parents=True, exist_ok=True)
    problems = state["problems"]
    tickets = state["tickets"]
    checks = state["checks"]

    active = [p for p in problems.values() if p["status"] in {"todo", "doing", "checking", "followup"}]
    done = [p for p in problems.values() if p["status"] == "done"]
    blocked = [p for p in problems.values() if p["status"] == "blocked"]
    ledger_status = "blocked" if blocked else ("done" if len(done) == len(problems) else "doing")

    index = [
        "# Complex Problem Ledger",
        "",
        f"Ledger: {state['ledger_id']}",
        f"Schema: v{state['schema_version']}",
        f"Root: {state['root_id']} - {problems[state['root_id']]['title']}",
        f"Status: {ledger_status}",
        f"Updated: {state.get('updated_at', '')}",
        "",
        "## Problem Tree",
        *render_problem_tree(state, state["root_id"]),
        "",
        "## Active",
        *(f"- [ ] {p['id']}: {p['title']} ({p['status']})" for p in active),
        "",
        "## Blocked",
        *(f"- [ ] {p['id']}: {p['title']}" for p in blocked),
        "",
        "## Done",
        *(f"- [x] {p['id']}: {p['title']}" for p in done),
        "",
        "## Tickets",
        *(f"- [{t['status']}] {t['id']}: {t['title']} -> {t['problem_id']} ({t.get('classification') or 'unclassified'})" for t in tickets.values()),
        "",
        "## Latest Checks",
        *(f"- [{c['status']}] {c['id']}: {c['problem_id']} {c.get('summary', '')}" for c in list(checks.values())[-10:]),
        "",
    ]
    (views / "INDEX.md").write_text("\n".join(index), encoding="utf-8")

    for p in problems.values():
        latest_check = p["check_ids"][-1] if p["check_ids"] else "none"
        body_lines = []
        if p.get("body_path"):
            body_lines.append(f"Problem: {p.get('body_path')}")
        body_lines.extend(f"Ticket {tid}: {tickets[tid].get('body_path')}" for tid in p["ticket_ids"] if tid in tickets)
        body_lines.extend(f"Result {rid}: {state['results'][rid].get('body_path')}" for rid in p["result_ids"] if rid in state["results"])
        body_lines.extend(f"Check {cid}: {state['checks'][cid].get('body_path')}" for cid in p["check_ids"] if cid in state["checks"])
        content = [
            f"# {p['id']}: {p['title']}",
            "",
            f"Status: {p['status']}",
            f"Parent: {p['parent_id'] or 'none'}",
            f"Root: {p['root_id']}",
            f"Source Ticket: {p.get('created_from_ticket_id') or 'none'} ({p.get('created_from_ticket_mode') or 'none'})",
            f"Source Check: {p.get('created_from_check_id') or 'none'}",
            f"Package: {p.get('package_path', 'none')}",
            f"Body: {p.get('body_path', 'none')}",
            f"Ticket(s): {', '.join(p['ticket_ids']) or 'none'}",
            "",
            "## Problem",
            p.get("description", ""),
            "",
            "## Success Criteria",
            bullet(p.get("success_criteria", [])),
            "",
            "## Subproblems",
            bullet([f"{sid}: {problems[sid]['title']}" for sid in p["subproblem_ids"] if sid in problems]),
            "",
            "## Results",
            bullet(p.get("result_ids", [])),
            "",
            "## Latest Check",
            latest_check,
            "",
            "## Bodies",
            bullet(body_lines),
            "",
            "## Follow-ups",
            bullet([f"{fid}: {problems[fid]['title']}" for fid in p["followup_ids"] if fid in problems]),
            "",
        ]
        (views / f"{p['id']}-{slugify(p['title'])}.md").write_text("\n".join(content), encoding="utf-8")


def validate(ledger: Path, state: dict[str, Any] | None = None) -> list[str]:
    state = state or load_state(ledger)
    errors: list[str] = []
    if state.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"Unsupported schema_version {state.get('schema_version')}; expected {SCHEMA_VERSION}")
    extra = sorted(set(state) - STATE_FIELDS)
    if extra:
        errors.append(f"Ledger has unsupported root fields: {', '.join(extra)}")
    root_id = state.get("root_id")
    if root_id not in state.get("problems", {}):
        errors.append(f"Missing root problem {root_id}")

    for pid, p in state["problems"].items():
        extra = sorted(set(p) - PROBLEM_FIELDS)
        if extra:
            errors.append(f"{pid} has unsupported problem fields: {', '.join(extra)}")
        if p.get("root_id") != root_id:
            errors.append(f"{pid} has wrong root_id {p.get('root_id')}")
        if p.get("status") not in PROBLEM_STATUSES:
            errors.append(f"{pid} has invalid status {p.get('status')}")
        parent = p.get("parent_id")
        if parent and parent not in state["problems"]:
            errors.append(f"{pid} has missing parent {parent}")
        if parent and bool(p.get("created_from_check_id")) == bool(p.get("created_from_ticket_id")):
            errors.append(f"{pid} must have exactly one source: created_from_check_id or created_from_ticket_id")
        from_check = p.get("created_from_check_id")
        if from_check:
            check = state["checks"].get(from_check)
            if not check:
                errors.append(f"{pid} references missing source check {from_check}")
            elif check.get("problem_id") != parent:
                errors.append(f"{pid} source check {from_check} does not belong to parent {parent}")
            elif check.get("status") != "not_success":
                errors.append(f"{pid} source check {from_check} is not not_success")
            elif check.get("followup_problem_id") != pid:
                errors.append(f"{pid} source check {from_check} points to followup {check.get('followup_problem_id')}")
        from_ticket = p.get("created_from_ticket_id")
        if from_ticket:
            source_mode = p.get("created_from_ticket_mode")
            ticket = state["tickets"].get(from_ticket)
            if not ticket:
                errors.append(f"{pid} references missing source ticket {from_ticket}")
            elif ticket.get("problem_id") != parent:
                errors.append(f"{pid} source ticket {from_ticket} does not belong to parent {parent}")
            elif source_mode and source_mode not in CREATED_FROM_TICKET_MODES:
                errors.append(f"{pid} has invalid created_from_ticket_mode {source_mode}")
            elif (source_mode == "split" or (not source_mode and ticket.get("classification") == "split")):
                if ticket.get("classification") != "split":
                    errors.append(f"{pid} source ticket {from_ticket} is not classified as split")
                elif ticket.get("status") not in {"splitting", "done"}:
                    errors.append(f"{pid} source ticket {from_ticket} is neither splitting nor done")
            elif source_mode == "spawn":
                if ticket.get("classification") != "one_go":
                    errors.append(f"{pid} source ticket {from_ticket} is not classified as one_go for spawn")
                elif ticket.get("status") not in {"executing", "done"}:
                    errors.append(f"{pid} source ticket {from_ticket} is neither executing nor done for spawn")
            else:
                errors.append(f"{pid} must set created_from_ticket_mode to split or spawn")
        for tid in p.get("ticket_ids", []):
            if tid not in state["tickets"]:
                errors.append(f"{pid} references missing ticket {tid}")
            elif state["tickets"][tid].get("problem_id") != pid:
                errors.append(f"{pid} references ticket {tid} owned by {state['tickets'][tid].get('problem_id')}")
        for sid in p.get("subproblem_ids", []):
            if sid not in state["problems"]:
                errors.append(f"{pid} references missing subproblem {sid}")
        for rid in p.get("result_ids", []):
            if rid not in state["results"]:
                errors.append(f"{pid} references missing result {rid}")
        for cid in p.get("check_ids", []):
            if cid not in state["checks"]:
                errors.append(f"{pid} references missing check {cid}")
        package_path = p.get("package_path")
        if not package_path:
            errors.append(f"{pid} missing package_path")
        elif not (ledger / package_path).is_dir():
            errors.append(f"{pid} missing problem package {package_path}")
        else:
            expected_package = root_package_path(pid) if pid == root_id else (child_package_path(state, parent, pid) if parent in state["problems"] else None)
            if expected_package and package_path != expected_package:
                errors.append(f"{pid} package_path is {package_path}; expected {expected_package}")
            for dirname in ("tickets", "results", "checks", "children"):
                if not (ledger / package_path / dirname).is_dir():
                    errors.append(f"{pid} package missing {dirname}/ directory")
        expected_body = problem_body_path(package_path) if package_path else None
        if expected_body and p.get("body_path") != expected_body:
            errors.append(f"{pid} body_path is {p.get('body_path')}; expected {expected_body}")
        if not p.get("body_path") or not (ledger / p["body_path"]).exists():
            errors.append(f"{pid} missing body file {p.get('body_path')}")
        if len(p.get("ticket_ids", [])) > 1:
            errors.append(f"{pid} has multiple tickets: {', '.join(p.get('ticket_ids', []))}")
        if p.get("status") == "done":
            if not p.get("ticket_ids"):
                errors.append(f"{pid} is done without a ticket")
            if not p.get("check_ids"):
                errors.append(f"{pid} is done without a success check")
            else:
                latest = state["checks"][p["check_ids"][-1]]
                if latest.get("status") != "success":
                    errors.append(f"{pid} is done but latest check is {latest.get('status')}")
            for sid in p.get("subproblem_ids", []):
                child = state["problems"].get(sid)
                if child and child.get("status") != "done":
                    errors.append(f"{pid} is done but subproblem {sid} is {child.get('status')}")
            for tid in p.get("ticket_ids", []):
                ticket = state["tickets"].get(tid)
                if ticket and ticket.get("status") != "done":
                    errors.append(f"{pid} is done but ticket {tid} is {ticket.get('status')}")

    for tid, t in state["tickets"].items():
        extra = sorted(set(t) - TICKET_FIELDS)
        if extra:
            errors.append(f"{tid} has unsupported ticket fields: {', '.join(extra)}")
        if t.get("root_id") != root_id:
            errors.append(f"{tid} has wrong root_id {t.get('root_id')}")
        if t.get("status") not in TICKET_STATUSES:
            errors.append(f"{tid} has invalid status {t.get('status')}")
        if t.get("problem_id") not in state["problems"]:
            errors.append(f"{tid} references missing problem {t.get('problem_id')}")
        elif tid not in state["problems"][t["problem_id"]].get("ticket_ids", []):
            errors.append(f"{tid} is not linked from problem {t['problem_id']}")
        if t.get("status") in {"defined", "classified", "executing", "splitting", "done"}:
            for field in ("problem_definition", "proposed_solution", "acceptance_criteria", "verification_plan"):
                if not t.get(field):
                    errors.append(f"{tid} {t.get('status')} ticket missing {field}")
        if t.get("status") in {"classified", "executing", "splitting", "done"}:
            if t.get("classification") not in TICKET_CLASSIFICATIONS:
                errors.append(f"{tid} classified ticket has invalid classification {t.get('classification')}")
            if not t.get("classification_reason"):
                errors.append(f"{tid} classified ticket missing classification_reason")
        if t.get("status") == "executing" and t.get("classification") != "one_go":
            errors.append(f"{tid} is executing but classification is {t.get('classification')}")
        if t.get("status") == "splitting" and t.get("classification") != "split":
            errors.append(f"{tid} is splitting but classification is {t.get('classification')}")
        if t.get("status") == "done" and not t.get("result_ids"):
            errors.append(f"{tid} is done without a result")
        if t.get("status") == "done" and t.get("classification") == "split":
            child_ids = child_problem_ids_from_ticket(state, tid)
            if not child_ids:
                errors.append(f"{tid} is a done split ticket without child problems")
            for child_id in child_ids:
                child = state["problems"].get(child_id)
                if child and child.get("status") != "done":
                    errors.append(f"{tid} is done but split child {child_id} is {child.get('status')}")
        if t.get("status") == "done":
            for child_id in child_problem_ids_from_ticket(state, tid):
                child = state["problems"].get(child_id)
                if child and child.get("status") != "done":
                    errors.append(f"{tid} is done but child {child_id} is {child.get('status')}")
        for rid in t.get("result_ids", []):
            if rid not in state["results"]:
                errors.append(f"{tid} references missing result {rid}")
        if t.get("problem_id") in state["problems"]:
            expected_body = ticket_body_path(state, t["problem_id"], tid)
            if t.get("body_path") != expected_body:
                errors.append(f"{tid} body_path is {t.get('body_path')}; expected {expected_body}")
        if not t.get("body_path") or not (ledger / t["body_path"]).exists():
            errors.append(f"{tid} missing body file {t.get('body_path')}")

    for rid, r in state["results"].items():
        extra = sorted(set(r) - RESULT_FIELDS)
        if extra:
            errors.append(f"{rid} has unsupported result fields: {', '.join(extra)}")
        if r.get("root_id") != root_id:
            errors.append(f"{rid} has wrong root_id {r.get('root_id')}")
        if r.get("ticket_id") not in state["tickets"]:
            errors.append(f"{rid} references missing ticket {r.get('ticket_id')}")
        if r.get("problem_id") not in state["problems"]:
            errors.append(f"{rid} references missing problem {r.get('problem_id')}")
        if r.get("ticket_id") in state["tickets"] and rid not in state["tickets"][r["ticket_id"]].get("result_ids", []):
            errors.append(f"{rid} is not linked from ticket {r['ticket_id']}")
        if r.get("problem_id") in state["problems"] and rid not in state["problems"][r["problem_id"]].get("result_ids", []):
            errors.append(f"{rid} is not linked from problem {r['problem_id']}")
        if r.get("problem_id") in state["problems"]:
            expected_body = result_body_path(state, r["problem_id"], rid)
            if r.get("body_path") != expected_body:
                errors.append(f"{rid} body_path is {r.get('body_path')}; expected {expected_body}")
        if not r.get("body_path") or not (ledger / r["body_path"]).exists():
            errors.append(f"{rid} missing body file {r.get('body_path')}")

    for cid, c in state["checks"].items():
        extra = sorted(set(c) - CHECK_FIELDS)
        if extra:
            errors.append(f"{cid} has unsupported check fields: {', '.join(extra)}")
        if c.get("root_id") != root_id:
            errors.append(f"{cid} has wrong root_id {c.get('root_id')}")
        if c.get("status") not in CHECK_STATUSES:
            errors.append(f"{cid} has invalid status {c.get('status')}")
        if c.get("problem_id") not in state["problems"]:
            errors.append(f"{cid} references missing problem {c.get('problem_id')}")
        followup = c.get("followup_problem_id")
        if c.get("status") in {"success", "not_success"} and not c.get("result_ids"):
            errors.append(f"{cid} {c.get('status')} check missing result_ids")
        for result_id in c.get("result_ids", []):
            result = state["results"].get(result_id)
            if not result:
                errors.append(f"{cid} references missing checked result {result_id}")
            elif c.get("problem_id") in state["problems"] and result_id not in result_ids_for_check_context(state, c["problem_id"]):
                errors.append(f"{cid} checks result {result_id} outside problem {c['problem_id']}'s result_with_followups context")
        if c.get("status") == "success":
            for field in ("summary", "evidence", "criteria_map", "execution_map", "stress_test", "residual_risk"):
                if not c.get(field):
                    errors.append(f"{cid} success check missing {field}")
        if c.get("status") == "not_success" and not followup:
            errors.append(f"{cid} is not_success without followup_problem_id")
        if c.get("status") == "not_success" and not c.get("blocking_gaps"):
            errors.append(f"{cid} not_success check missing blocking_gaps")
        if c.get("status") == "blocked" and not c.get("blocking_gaps"):
            errors.append(f"{cid} blocked check missing blocking_gaps")
        if followup and followup not in state["problems"]:
            errors.append(f"{cid} references missing followup {followup}")
        if c.get("problem_id") in state["problems"] and cid not in state["problems"][c["problem_id"]].get("check_ids", []):
            errors.append(f"{cid} is not linked from problem {c['problem_id']}")
        if c.get("problem_id") in state["problems"]:
            expected_body = check_body_path(state, c["problem_id"], cid)
            if c.get("body_path") != expected_body:
                errors.append(f"{cid} body_path is {c.get('body_path')}; expected {expected_body}")
        if not c.get("body_path") or not (ledger / c["body_path"]).exists():
            errors.append(f"{cid} missing body file {c.get('body_path')}")

    counters = state.get("counters", {})
    for prefix, key in [("P", "problem"), ("T", "ticket"), ("R", "result"), ("C", "check")]:
        expected = len(state.get(f"{key}s", {}))
        actual = counters.get(key, 0)
        if actual < expected:
            errors.append(f"Counter '{key}' is {actual} but {expected} {key}s exist")

    iso_re = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?([+-]\d{2}:\d{2}|Z)$")
    for collection_name in ("problems", "tickets", "results", "checks"):
        for eid, entity in state.get(collection_name, {}).items():
            for ts_field in ("created_at", "updated_at"):
                ts = entity.get(ts_field)
                if ts and not iso_re.match(ts):
                    errors.append(f"{eid} has invalid ISO timestamp in {ts_field}: {ts}")

    for pid, p in state["problems"].items():
        body_path = p.get("body_path")
        if body_path and (ledger / body_path).exists():
            body_text = (ledger / body_path).read_text(encoding="utf-8")
            heading = first_heading(body_text)
            if heading and p.get("title") and heading != p["title"]:
                errors.append(f"{pid} body title '{heading}' != state title '{p['title']}'")

    return errors


def render_cmd(args: argparse.Namespace) -> None:
    ledger = resolve_ledger(args.ledger)
    state = load_state(ledger)
    render(ledger, state)
    update_workspace_index_for_ledger(ledger)
    print(ledger / "views" / "INDEX.md")


def validate_cmd(args: argparse.Namespace) -> None:
    ledger = resolve_ledger(args.ledger)
    errors = validate(ledger)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
    print(err_msg("ledger_valid"))


def status_cmd(args: argparse.Namespace) -> None:
    ledger = resolve_ledger(args.ledger)
    state = load_state(ledger)
    errors = validate(ledger, state)
    root = state["problems"][state["root_id"]]
    active = [p for p in state["problems"].values() if p["status"] in {"todo", "doing", "checking", "followup"}]
    blocked = [p for p in state["problems"].values() if p["status"] == "blocked"]
    print(f"ledger={state['ledger_id']} schema_version={state['schema_version']} root={state['root_id']} title={root['title']}")
    print(f"problems={len(state['problems'])} active={len(active)} blocked={len(blocked)} tickets={len(state['tickets'])} checks={len(state['checks'])}")
    print(f"valid={'yes' if not errors else 'no'}")
    if errors:
        for error in errors:
            print(f"ERROR: {error}")


def next_cmd(args: argparse.Namespace) -> None:
    ledger = resolve_ledger(args.ledger)
    state = load_state(ledger)
    item = select_next(state)
    if args.json:
        print(json.dumps(item, ensure_ascii=False, sort_keys=True))
        return
    print(f"ledger={item['ledger_id']} schema_version={item['schema_version']} root={item['root_id']} effort={item.get('effort', 'medium')}")
    print(f"status={item['status']}")
    print(f"next_action={item['next_action']}")
    print("next_instruction:")
    print(item["next_instruction"])
    print(f"context_problem={item['problem_id']} title={item['title']} problem_status={item['problem_status']}")
    if item.get("ticket_id"):
        print(f"context_ticket={item['ticket_id']}")
    print(f"reason={item['reason']}")
    if item.get("commands"):
        print("commands:")
        for command in item["commands"]:
            print(f"- {command}")


def list_cmd(args: argparse.Namespace) -> None:
    root = Path(args.dir)
    index = load_workspace_index(root)
    active_id = index.get("active_ledger_id")
    items = []
    if root.exists():
        for ledger in ledger_dirs(root):
            try:
                state = load_state(ledger)
            except SystemExit as exc:
                items.append({
                    "ledger_id": ledger.name,
                    "schema_version": "unsupported",
                    "status": "unsupported",
                    "title": str(exc),
                    "path": ledger.name,
                    "updated_at": "",
                })
                continue
            items.append(ledger_summary(ledger, state))
    if not items:
        print(err_msg("no_ledgers_found", root=root))
        return
    for item in sorted(items, key=lambda row: row.get("updated_at") or "", reverse=True):
        marker = "*" if item.get("ledger_id") == active_id else " "
        print(f"{marker} {item['ledger_id']} [schema=v{item.get('schema_version', '?')}] [{item.get('status', 'unknown')}] {item.get('title', '')} path={item.get('path', item['ledger_id'])}")


def use_cmd(args: argparse.Namespace) -> None:
    root = Path(args.dir)
    ledger_id_value = validate_ledger_id(args.ledger_id)
    ledger = root / ledger_id_value
    if not (ledger / "state.json").exists():
        raise SystemExit(f"Unknown ledger under {root}: {ledger_id_value}")
    update_workspace_index_for_ledger(ledger, set_active=True)
    print(f"active_ledger_id={ledger_id_value}")


def archive_cmd(args: argparse.Namespace) -> None:
    import shutil
    root = Path(args.dir)
    ledger_id_value = validate_ledger_id(args.ledger_id)
    ledger = root / ledger_id_value
    if not (ledger / "state.json").exists():
        raise SystemExit(err_msg("unknown_ledger", root=root, id=ledger_id_value))
    archive_dir = root / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    dest = archive_dir / ledger_id_value
    if dest.exists():
        raise SystemExit(f"Archive destination already exists: {dest}")
    shutil.move(str(ledger), str(dest))
    index = load_workspace_index(root)
    index["ledgers"] = [item for item in index.get("ledgers", []) if item.get("ledger_id") != ledger_id_value]
    if index.get("active_ledger_id") == ledger_id_value:
        index["active_ledger_id"] = None
    save_workspace_index(root, index)
    print(f"archived {ledger_id_value} -> {dest}")


def delete_cmd(args: argparse.Namespace) -> None:
    import shutil
    root = Path(args.dir)
    ledger_id_value = validate_ledger_id(args.ledger_id)
    ledger = root / ledger_id_value
    if not (ledger / "state.json").exists():
        raise SystemExit(err_msg("unknown_ledger", root=root, id=ledger_id_value))
    if not args.force:
        raise SystemExit(f"Use --force to confirm deletion of {ledger_id_value}")
    shutil.rmtree(str(ledger))
    index = load_workspace_index(root)
    index["ledgers"] = [item for item in index.get("ledgers", []) if item.get("ledger_id") != ledger_id_value]
    if index.get("active_ledger_id") == ledger_id_value:
        index["active_ledger_id"] = None
    save_workspace_index(root, index)
    print(f"deleted {ledger_id_value}")


def undo_cmd(args: argparse.Namespace) -> None:
    ledger = resolve_ledger(args.ledger)
    events_path = ledger / "events.jsonl"
    if not events_path.exists():
        raise SystemExit("No events to undo")
    lines = events_path.read_text(encoding="utf-8").strip().split("\n")
    if not lines or lines == [""]:
        raise SystemExit("No events to undo")
    last_event = json.loads(lines[-1])
    remaining = lines[:-1]
    if remaining:
        events_path.write_text("\n".join(remaining) + "\n", encoding="utf-8")
    else:
        events_path.write_text("", encoding="utf-8")
    print(f"undone event: {last_event.get('id')} type={last_event.get('type')}")
    print("Warning: state.json was NOT reverted; only the event log was trimmed. Manual state repair may be needed.")


def set_effort_cmd(args: argparse.Namespace) -> None:
    ledger = resolve_ledger(args.ledger)
    with locked_state(ledger) as state:
        old = state.get("effort", "medium")
        state["effort"] = args.effort
        append_event(ledger, state, "effort_changed", {"from": old, "to": args.effort})
    print(f"effort: {old} -> {args.effort}")


def purge_events_cmd(args: argparse.Namespace) -> None:
    ledger = resolve_ledger(args.ledger)
    events_path = ledger / "events.jsonl"
    if not events_path.exists():
        print("No events file found")
        return
    line_count = len(events_path.read_text(encoding="utf-8").strip().split("\n"))
    if args.keep > 0:
        lines = events_path.read_text(encoding="utf-8").strip().split("\n")
        kept = lines[-args.keep:]
        events_path.write_text("\n".join(kept) + "\n", encoding="utf-8")
        purged = max(0, line_count - args.keep)
    else:
        events_path.write_text("", encoding="utf-8")
        purged = line_count
    print(f"purged {purged} events, kept {min(args.keep, line_count)}")


def batch_next_cmd(args: argparse.Namespace) -> None:
    ledger = resolve_ledger(args.ledger)
    state = load_state(ledger)
    effort = state.get("effort", "medium")
    language = state.get("language", "en")
    problems = state["problems"]
    open_problems = [p for p in problems.values() if is_open_problem(p)]
    if not open_problems:
        print("[]" if args.json else "No open problems")
        return
    runnable = [p for p in open_problems if is_runnable_frontier_problem(state, p)]
    if not runnable:
        print("[]" if args.json else "No runnable frontier problems")
        return
    items = []
    for problem in runnable:
        action, reason = next_action_for_problem(state, problem)
        ticket = primary_ticket(state, problem)
        item = {
            "problem_id": problem["id"],
            "title": problem["title"],
            "problem_status": problem["status"],
            "ticket_id": ticket["id"] if ticket else None,
            "next_action": action,
            "reason": reason,
        }
        items.append(item)
    if args.json:
        print(json.dumps(items, ensure_ascii=False, sort_keys=True))
    else:
        for item in items:
            print(f"{item['problem_id']}: {item['next_action']} ({item['reason']})")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Maintain a complex-problem ledger.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="Create a new ledger session with P000 root.")
    p.add_argument("title", nargs="?")
    p.add_argument("--from-file", required=True)
    p.add_argument("--description")
    p.add_argument("--criteria", action="append")
    p.add_argument("--dir", default=".complex-problems")
    p.add_argument("--ledger-id")
    p.add_argument("--effort", choices=sorted(EFFORT_LEVELS), default="medium")
    p.add_argument("--language", default="en", help="Language for body content (e.g. en, zh, ja, es)")
    p.set_defaults(func=init_cmd)

    p = sub.add_parser("create-problem", help="Create a child problem from a source ticket.")
    p.add_argument("title", nargs="?")
    p.add_argument("--ledger")
    p.add_argument("--parent")
    p.add_argument("--from-ticket")
    p.add_argument("--mode", choices=sorted(CREATED_FROM_TICKET_MODES))
    p.add_argument("--from-file", required=True)
    p.add_argument("--description")
    p.add_argument("--criteria", action="append")
    p.set_defaults(func=create_problem_cmd)

    p = sub.add_parser("create-ticket", help="Create and define a v6 solution ticket for a problem.")
    p.add_argument("title", nargs="?")
    p.add_argument("--ledger")
    p.add_argument("--problem", required=True)
    p.add_argument("--from-file", required=True)
    p.add_argument("--problem-definition")
    p.add_argument("--proposed-solution")
    p.add_argument("--acceptance-criteria", action="append")
    p.add_argument("--verification-plan")
    p.add_argument("--risk", action="append")
    p.add_argument("--assumption", action="append")
    p.set_defaults(func=create_ticket_cmd)

    p = sub.add_parser("classify-ticket", help="Classify a defined ticket as one_go or split.")
    p.add_argument("ticket")
    p.add_argument("--ledger")
    p.add_argument("--classification", choices=sorted(TICKET_CLASSIFICATIONS), required=True)
    p.add_argument("--reason", required=True)
    p.set_defaults(func=classify_ticket_cmd)

    p = sub.add_parser("set-status", help="Set problem or ticket status.")
    p.add_argument("kind", choices=["problem", "ticket"])
    p.add_argument("id")
    p.add_argument("status")
    p.add_argument("--ledger")
    p.set_defaults(func=set_status_cmd)

    p = sub.add_parser("result", help="Record execution result for a ticket.")
    p.add_argument("--ledger")
    p.add_argument("--ticket", required=True)
    p.add_argument("--from-file", required=True)
    p.add_argument("--summary")
    p.add_argument("--done", action="append")
    p.add_argument("--verification", action="append")
    p.add_argument("--gap", action="append")
    p.add_argument("--artifact", action="append")
    p.set_defaults(func=result_cmd)

    p = sub.add_parser("check", help="Record check_success for a problem.")
    p.add_argument("--ledger")
    p.add_argument("--problem", required=True)
    p.add_argument("--status", choices=sorted(CHECK_STATUSES), required=True)
    p.add_argument("--from-file", required=True)
    p.add_argument("--summary")
    p.add_argument("--evidence", action="append")
    p.add_argument("--criteria-map", action="append")
    p.add_argument("--execution-map", action="append")
    p.add_argument("--stress-test", action="append")
    p.add_argument("--residual-risk", action="append")
    p.add_argument("--result", dest="result_ids", action="append")
    p.add_argument("--gap", action="append")
    p.add_argument("--followup-title")
    p.add_argument("--followup-description")
    p.add_argument("--followup-criteria", action="append")
    p.add_argument("--followup-from-file")
    p.set_defaults(func=check_cmd)

    p = sub.add_parser("render", help="Render Markdown views from state.json.")
    p.add_argument("--ledger")
    p.set_defaults(func=render_cmd)

    p = sub.add_parser("validate", help="Validate ledger consistency.")
    p.add_argument("--ledger")
    p.set_defaults(func=validate_cmd)

    p = sub.add_parser("status", help="Print compact ledger status.")
    p.add_argument("--ledger")
    p.set_defaults(func=status_cmd)

    p = sub.add_parser("next", help="Show the next concrete agent instruction.")
    p.add_argument("--ledger")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=next_cmd)

    p = sub.add_parser("list", help="List ledgers in a workspace index.")
    p.add_argument("--dir", default=".complex-problems")
    p.set_defaults(func=list_cmd)

    p = sub.add_parser("use", help="Set the active ledger for a workspace.")
    p.add_argument("ledger_id")
    p.add_argument("--dir", default=".complex-problems")
    p.set_defaults(func=use_cmd)

    p = sub.add_parser("archive", help="Move a ledger to the archive directory.")
    p.add_argument("ledger_id")
    p.add_argument("--dir", default=".complex-problems")
    p.set_defaults(func=archive_cmd)

    p = sub.add_parser("delete", help="Permanently delete a ledger.")
    p.add_argument("ledger_id")
    p.add_argument("--dir", default=".complex-problems")
    p.add_argument("--force", action="store_true", help="Confirm deletion")
    p.set_defaults(func=delete_cmd)

    p = sub.add_parser("undo", help="Remove the last event from the event log.")
    p.add_argument("--ledger")
    p.set_defaults(func=undo_cmd)

    p = sub.add_parser("set-effort", help="Change the effort level of the active ledger.")
    p.add_argument("effort", choices=sorted(EFFORT_LEVELS))
    p.add_argument("--ledger")
    p.set_defaults(func=set_effort_cmd)

    p = sub.add_parser("purge-events", help="Purge old events from the event log.")
    p.add_argument("--ledger")
    p.add_argument("--keep", type=int, default=0, help="Number of recent events to keep")
    p.set_defaults(func=purge_events_cmd)

    p = sub.add_parser("batch-next", help="List all runnable frontier problems and their next actions.")
    p.add_argument("--ledger")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=batch_next_cmd)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
