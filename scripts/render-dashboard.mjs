#!/usr/bin/env node
// ── Imports and constants ──
import fs from "node:fs";
import path from "node:path";
import http from "node:http";
import crypto from "node:crypto";
import { spawn } from "node:child_process";

const DEFAULT_LEDGER_DIR = ".complex-problems";

function parseArgs(argv) {
  const args = {
    workspace: process.cwd(),
    ledgerDir: DEFAULT_LEDGER_DIR,
    port: 3000,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--workspace") {
      args.workspace = argv[++index];
    } else if (arg === "--ledger-dir") {
      args.ledgerDir = argv[++index];
    } else if (arg === "--port") {
      args.port = parseInt(argv[++index], 10);
    } else if (arg === "--help" || arg === "-h") {
      printHelp();
      process.exit(0);
    } else {
      throw new Error(`Unknown argument: ${arg}`);
    }
  }
  return args;
}

function printHelp() {
  console.log(`Usage: node ${process.argv[1]} [options]

Options:
  --workspace <path>   Project root directory (default: cwd)
  --ledger-dir <name>  Ledger directory name (default: ${DEFAULT_LEDGER_DIR})
  --port <number>      Server port (default: 3000)
  --help, -h           Show this help`);
}

// ── Utility functions ──

function readJson(file) {
  return JSON.parse(fs.readFileSync(file, "utf8"));
}

function toPosix(value) {
  return value.split(path.sep).join("/");
}

function safeArray(value) {
  return Array.isArray(value) ? value : [];
}

function latestTimestamp(values) {
  const timestamps = values
    .flatMap((value) => [value?.updated_at, value?.created_at])
    .filter(Boolean)
    .sort();
  return timestamps[timestamps.length - 1] || "";
}

function statusCounts(items) {
  return items.reduce((counts, item) => {
    const status = item.status || "unknown";
    counts[status] = (counts[status] || 0) + 1;
    return counts;
  }, {});
}

function pick(object, keys) {
  const picked = {};
  for (const key of keys) {
    if (object[key] !== undefined) {
      picked[key] = object[key];
    }
  }
  return picked;
}

// ── Data normalization ──

function normalizeProblem(problem) {
  return pick(problem, [
    "id",
    "title",
    "description",
    "status",
    "parent_id",
    "created_from_check_id",
    "created_from_ticket_id",
    "success_criteria",
    "ticket_ids",
    "subproblem_ids",
    "result_ids",
    "check_ids",
    "followup_ids",
    "package_path",
    "body_path",
    "created_at",
    "updated_at",
  ]);
}

function normalizeTicket(ticket) {
  return pick(ticket, [
    "id",
    "title",
    "problem_id",
    "status",
    "classification",
    "classification_reason",
    "problem_definition",
    "proposed_solution",
    "acceptance_criteria",
    "verification_plan",
    "risks",
    "assumptions",
    "result_ids",
    "body_path",
    "created_at",
    "updated_at",
  ]);
}

function normalizeResult(result) {
  return pick(result, [
    "id",
    "ticket_id",
    "problem_id",
    "status",
    "summary",
    "done",
    "verification",
    "known_gaps",
    "artifacts",
    "body_path",
    "created_at",
  ]);
}

function normalizeCheck(check) {
  return pick(check, [
    "id",
    "problem_id",
    "status",
    "summary",
    "evidence",
    "criteria_map",
    "execution_map",
    "stress_test",
    "residual_risk",
    "blocking_gaps",
    "result_ids",
    "followup_problem_id",
    "body_path",
    "created_at",
  ]);
}

function deriveLedgerStatus(problems) {
  const counts = statusCounts(problems);
  if (counts.blocked) return "blocked";
  const openCount = problems.filter((problem) => problem.status !== "done").length;
  return openCount === 0 ? "done" : "doing";
}

function readEventsJsonl(ledgerPath) {
  const eventsFile = path.join(ledgerPath, "events.jsonl");
  if (!fs.existsSync(eventsFile)) return [];
  try {
    return fs.readFileSync(eventsFile, "utf8")
      .split("\n")
      .filter(Boolean)
      .map((line) => { try { return JSON.parse(line); } catch { return null; } })
      .filter(Boolean);
  } catch { return []; }
}

// ── Data collection and ledger summarization ──

function readBodyPreview(ledgerPath, bodyPath, maxChars = 2000) {
  if (!bodyPath) return "";
  const fullPath = path.join(ledgerPath, bodyPath);
  if (!fs.existsSync(fullPath)) return "";
  try {
    const content = fs.readFileSync(fullPath, "utf8");
    return content.length > maxChars ? content.slice(0, maxChars) + "\n…(truncated)" : content;
  } catch { return ""; }
}

function summarizeLedger(state, ledgerPath) {
  const problems = Object.values(state.problems || {}).map(normalizeProblem);
  const tickets = Object.values(state.tickets || {}).map(normalizeTicket);
  const results = Object.values(state.results || {}).map(normalizeResult);
  const checks = Object.values(state.checks || {}).map(normalizeCheck);
  for (const entity of [...problems, ...tickets, ...results, ...checks]) {
    if (entity.body_path) {
      entity.body_preview = readBodyPreview(ledgerPath, entity.body_path);
    }
  }
  const events = readEventsJsonl(ledgerPath);
  const root = state.problems?.[state.root_id] || problems[0] || {};
  const updatedAt = state.updated_at || latestTimestamp([...problems, ...tickets, ...results, ...checks, ...events]);
  const problemCounts = statusCounts(problems);
  const ticketCounts = statusCounts(tickets);
  const checkCounts = statusCounts(checks);
  const openProblems = problems.filter((problem) => problem.status !== "done");
  const doneCount = problemCounts.done || 0;
  const totalCount = problems.length || 1;
  const completionPct = Math.round((doneCount / totalCount) * 100);
  return {
    ledger_id: state.ledger_id || path.basename(ledgerPath),
    schema_version: state.schema_version,
    root_id: state.root_id,
    title: root.title || state.ledger_id || path.basename(ledgerPath),
    status: deriveLedgerStatus(problems),
    updated_at: updatedAt,
    created_at: state.created_at || "",
    effort: state.effort || "medium",
    language: state.language || "en",
    completion_pct: completionPct,
    counts: {
      problems: problems.length,
      tickets: tickets.length,
      results: results.length,
      checks: checks.length,
      events: events.length,
      open: openProblems.length,
      done: doneCount,
      blocked: problemCounts.blocked || 0,
      followup: problemCounts.followup || 0,
    },
    problem_counts: problemCounts,
    ticket_counts: ticketCounts,
    check_counts: checkCounts,
    problems,
    tickets,
    results,
    checks,
    events: events.slice(-200).map((event) => pick(event, ["id", "type", "at", "payload"])),
  };
}

function loadIndex(ledgerDir) {
  const indexPath = path.join(ledgerDir, "INDEX.json");
  if (!fs.existsSync(indexPath)) {
    return {};
  }
  try {
    return readJson(indexPath);
  } catch (error) {
    return { index_error: String(error.message || error) };
  }
}

function findLedgerStateFiles(ledgerDir) {
  return fs.readdirSync(ledgerDir, { withFileTypes: true })
    .filter((entry) => entry.isDirectory() && entry.name.startsWith("L"))
    .map((entry) => path.join(ledgerDir, entry.name, "state.json"))
    .filter((file) => fs.existsSync(file))
    .sort();
}

function collectDashboardData(rootDir, ledgerDir, outFile) {
  const absoluteLedgerDir = path.resolve(rootDir, ledgerDir);
  const absoluteOut = path.resolve(rootDir, outFile);
  const outDir = path.dirname(absoluteOut);
  const index = loadIndex(absoluteLedgerDir);
  const ledgers = [];
  const errors = [];
  for (const stateFile of findLedgerStateFiles(absoluteLedgerDir)) {
    try {
      ledgers.push(summarizeLedger(readJson(stateFile), path.dirname(stateFile)));
    } catch (error) {
      errors.push({
        file: toPosix(path.relative(rootDir, stateFile)),
        error: String(error.message || error),
      });
    }
  }
  ledgers.sort((a, b) => {
    const dateCompare = String(b.updated_at || "").localeCompare(String(a.updated_at || ""));
    return dateCompare || String(b.ledger_id).localeCompare(String(a.ledger_id));
  });
  const totals = ledgers.reduce((acc, ledger) => {
    acc.ledgers += 1;
    acc.problems += ledger.counts.problems;
    acc.tickets += ledger.counts.tickets;
    acc.results += ledger.counts.results;
    acc.checks += ledger.counts.checks;
    acc.open += ledger.counts.open;
    acc.blocked += ledger.counts.blocked;
    acc.followup += ledger.counts.followup;
    if (ledger.status === "done") acc.doneLedgers += 1;
    if (ledger.status !== "done") acc.openLedgers += 1;
    return acc;
  }, {
    ledgers: 0,
    problems: 0,
    tickets: 0,
    results: 0,
    checks: 0,
    open: 0,
    blocked: 0,
    followup: 0,
    doneLedgers: 0,
    openLedgers: 0,
  });
  return {
    generated_at: new Date().toISOString(),
    workspace: rootDir,
    ledger_dir: toPosix(path.relative(rootDir, absoluteLedgerDir)),
    ledger_dir_from_output: toPosix(path.relative(outDir, absoluteLedgerDir)) || ".",
    active_ledger_id: index.active_ledger_id || "",
    index_error: index.index_error || "",
    totals,
    errors,
    ledgers,
  };
}

// ── HTML rendering (self-contained dashboard with inline CSS/JS) ──

function renderHtml(data) {
  const json = JSON.stringify(data).replace(/</g, "\\u003c").replace(/`/g, "\\u0060").replace(/\$\{/g, "\\u0024{");
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Recursive Closure Dashboard</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --panel-2: #fbfcfe;
      --text: #17202a;
      --muted: #667085;
      --line: #d8dee8;
      --accent: #166b5f;
      --accent-2: #255e9c;
      --danger: #b42318;
      --warn: #b54708;
      --ok: #067647;
      --shadow: 0 1px 2px rgba(16, 24, 40, 0.08);
      --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
      --sans: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    * { box-sizing: border-box; }
    html, body { height: 100%; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: var(--sans);
      font-size: 14px;
      line-height: 1.45;
      letter-spacing: 0;
      transition: background 0.3s, color 0.3s;
    }
    button, input, select { font: inherit; letter-spacing: 0; }
    button {
      border: 1px solid var(--line);
      background: var(--panel);
      color: var(--text);
      border-radius: 6px;
      padding: 7px 10px;
      cursor: pointer;
      transition: border-color 0.2s, background 0.2s, color 0.2s;
    }
    button:hover { border-color: #9aa8ba; }
    a { color: var(--accent-2); text-decoration: none; }
    a:hover { text-decoration: underline; }
    .app {
      min-height: 100vh;
      display: grid;
      grid-template-rows: auto 1fr;
    }
    .topbar {
      display: grid;
      grid-template-columns: minmax(260px, 1fr) auto;
      gap: 16px;
      align-items: center;
      padding: 16px 20px;
      background: var(--panel);
      border-bottom: 1px solid var(--line);
    }
    .title h1 {
      margin: 0;
      font-size: 20px;
      line-height: 1.2;
      font-weight: 720;
    }
    .title p {
      margin: 4px 0 0;
      color: var(--muted);
      font-size: 13px;
    }
    .toolbar {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }
    .toolbar input,
    .toolbar select {
      border: 1px solid var(--line);
      background: var(--panel);
      color: var(--text);
      border-radius: 6px;
      min-height: 34px;
      padding: 6px 9px;
    }
    .toolbar input { width: min(360px, 42vw); }
    .layout {
      display: grid;
      grid-template-columns: 360px minmax(0, 1fr) 380px;
      gap: 12px;
      padding: 12px;
      height: calc(100vh - 73px);
    }
    .sidebar,
    .main,
    .details {
      min-height: 0;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
      overflow: hidden;
      transition: background 0.3s, border-color 0.3s;
    }
    .sidebar,
    .details {
      display: grid;
      grid-template-rows: auto 1fr;
    }
    .panel-head {
      padding: 12px;
      border-bottom: 1px solid var(--line);
      background: var(--panel-2);
    }
    .panel-head h2 {
      margin: 0;
      font-size: 14px;
      font-weight: 720;
    }
    .panel-head p {
      margin: 4px 0 0;
      color: var(--muted);
      font-size: 12px;
    }
    .scroll {
      min-height: 0;
      overflow: auto;
    }
    .ledger-list {
      list-style: none;
      padding: 0;
      margin: 0;
    }
    .ledger-item {
      border-bottom: 1px solid var(--line);
    }
    .ledger-button {
      width: 100%;
      border: 0;
      border-radius: 0;
      background: transparent;
      text-align: left;
      padding: 10px 12px;
      display: grid;
      gap: 6px;
      transition: background 0.2s, box-shadow 0.2s;
    }
    .ledger-button.is-selected {
      background: #e9f5f3;
      box-shadow: inset 3px 0 0 var(--accent);
    }
    .ledger-title {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 8px;
      align-items: start;
    }
    .ledger-title strong {
      font-size: 13px;
      line-height: 1.25;
      overflow-wrap: anywhere;
    }
    .ledger-meta,
    .entity-meta {
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
      align-items: center;
      color: var(--muted);
      font-size: 12px;
    }
    .badge {
      display: inline-flex;
      align-items: center;
      min-height: 20px;
      padding: 2px 6px;
      border-radius: 999px;
      background: #eef2f6;
      color: #344054;
      font-size: 12px;
      white-space: nowrap;
      transition: background 0.2s, color 0.2s;
    }
    .badge.done, .badge.success { background: #dcfae6; color: var(--ok); }
    .badge.doing, .badge.followup, .badge.checking { background: #e0f2fe; color: #175cd3; }
    .badge.blocked, .badge.not_success { background: #fee4e2; color: var(--danger); }
    .badge.todo, .badge.created, .badge.defined, .badge.classified { background: #fff1c2; color: var(--warn); }
    .main {
      display: grid;
      grid-template-rows: auto auto auto 1fr;
    }
    .stats {
      display: grid;
      grid-template-columns: auto repeat(6, minmax(0, 1fr));
      border-bottom: 1px solid var(--line);
      background: var(--panel);
    }
    .stat {
      padding: 12px;
      border-right: 1px solid var(--line);
      min-width: 0;
    }
    .stat:last-child { border-right: 0; }
    .stat .value {
      font-size: 20px;
      font-weight: 760;
      line-height: 1;
    }
    .stat .label {
      margin-top: 5px;
      color: var(--muted);
      font-size: 12px;
    }
    .ledger-header {
      padding: 14px 16px;
      border-bottom: 1px solid var(--line);
      background: var(--panel-2);
      display: grid;
      gap: 8px;
    }
    .ledger-header h2 {
      margin: 0;
      font-size: 18px;
      line-height: 1.25;
    }
    .tree {
      padding: 12px 14px 40px;
    }
    .tree-node {
      position: relative;
      margin: 0 0 8px;
    }
    .tree-node .children {
      margin-left: 20px;
      padding-left: 14px;
      border-left: 1px solid var(--line);
    }
    details > summary {
      list-style: none;
      cursor: pointer;
    }
    details > summary::-webkit-details-marker { display: none; }
    .problem-row,
    .child-row {
      display: grid;
      grid-template-columns: auto 1fr auto;
      gap: 8px;
      align-items: center;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 8px 10px;
      background: var(--panel);
      cursor: pointer;
      transition: border-color 0.2s, box-shadow 0.2s, background 0.2s;
    }
    .problem-row:hover,
    .child-row:hover { border-color: #9aa8ba; }
    .problem-row.is-selected,
    .child-row.is-selected {
      border-color: var(--accent);
      box-shadow: 0 0 0 2px rgba(22, 107, 95, 0.12);
    }
    .chevron {
      color: var(--muted);
      font-size: 12px;
      width: 20px;
      height: 20px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border-radius: 4px;
      cursor: pointer;
      transition: background 0.15s, transform 0.2s;
    }
    .chevron:hover { background: var(--line); }
    details[open] > summary .chevron { transform: rotate(90deg); }
    .row-title {
      min-width: 0;
    }
    .row-title strong {
      display: block;
      overflow-wrap: anywhere;
    }
    .row-title span {
      display: block;
      margin-top: 2px;
      color: var(--muted);
      font-size: 12px;
      overflow-wrap: anywhere;
    }
    .ptrc {
      margin: 7px 0 10px 34px;
      display: grid;
      gap: 6px;
    }
    .child-row {
      grid-template-columns: auto 1fr auto;
      padding: 6px 8px;
      background: #fcfcfd;
      font-size: 13px;
    }
    .type-pill {
      min-width: 22px;
      text-align: center;
      font-family: var(--mono);
      font-weight: 700;
      color: #475467;
    }
    .details-body {
      padding: 12px;
    }
    .empty {
      color: var(--muted);
      padding: 24px;
      text-align: center;
    }
    .detail-title {
      margin: 0 0 8px;
      font-size: 16px;
      line-height: 1.25;
      overflow-wrap: anywhere;
    }
    .detail-section {
      border-top: 1px solid var(--line);
      padding-top: 10px;
      margin-top: 10px;
    }
    .detail-section h3 {
      margin: 0 0 6px;
      font-size: 12px;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0;
    }
    .kv {
      display: grid;
      grid-template-columns: 110px 1fr;
      gap: 6px 10px;
      font-size: 13px;
    }
    .kv dt { color: var(--muted); }
    .kv dd { margin: 0; min-width: 0; overflow-wrap: anywhere; }
    .text-block {
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      background: #f8fafc;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 9px;
      font-size: 13px;
      max-height: 260px;
      overflow: auto;
    }
    .list {
      margin: 0;
      padding-left: 18px;
    }
    .list li { margin: 3px 0; }
    .footer-note {
      color: var(--muted);
      font-size: 12px;
      margin-top: 10px;
    }
    .timeline { padding: 0; margin: 0; list-style: none; }
    .timeline-item {
      display: grid;
      grid-template-columns: 56px 12px 1fr;
      gap: 0 8px;
      min-height: 36px;
      font-size: 13px;
    }
    .timeline-time {
      text-align: right;
      color: var(--muted);
      font-family: var(--mono);
      font-size: 11px;
      padding-top: 2px;
    }
    .timeline-dot {
      display: flex;
      flex-direction: column;
      align-items: center;
    }
    .timeline-dot::before {
      content: "";
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--accent);
      flex-shrink: 0;
      margin-top: 4px;
    }
    .timeline-dot::after {
      content: "";
      width: 1px;
      flex: 1;
      background: var(--line);
    }
    .timeline-item:last-child .timeline-dot::after { display: none; }
    .timeline-content { padding-bottom: 8px; }
    .timeline-content strong { font-size: 13px; }
    .timeline-content span { color: var(--muted); font-size: 12px; }
    .view-tabs {
      display: flex;
      gap: 0;
      border-bottom: 1px solid var(--line);
      background: var(--panel-2);
    }
    .view-tab {
      border: 0;
      border-radius: 0;
      background: transparent;
      padding: 8px 16px;
      font-size: 13px;
      font-weight: 600;
      color: var(--muted);
      border-bottom: 2px solid transparent;
      transition: color 0.2s, border-color 0.2s;
      cursor: pointer;
    }
    .view-tab:hover { color: var(--text); }
    .view-tab.active { color: var(--accent); border-bottom-color: var(--accent); }
    .graph-container {
      width: 100%;
      height: 100%;
      display: none;
    }
    .graph-container.visible { display: block; }
    .graph-container svg { width: 100%; height: 100%; }
    .graph-node { cursor: pointer; }
    .graph-node circle { transition: r 0.2s; }
    .graph-node:hover circle { r: 10; }
    .graph-label { font-family: var(--sans); font-size: 10px; fill: var(--text); pointer-events: none; }
    .graph-link { stroke: var(--line); stroke-opacity: 0.6; }
    .graph-tooltip {
      position: absolute;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 6px 10px;
      font-size: 12px;
      box-shadow: var(--shadow);
      pointer-events: none;
      opacity: 0;
      transition: opacity 0.15s;
      z-index: 10;
    }
    @media (max-width: 1180px) {
      .layout {
        grid-template-columns: 300px minmax(0, 1fr);
        grid-template-rows: minmax(0, 1fr) minmax(360px, 42vh);
      }
      .details {
        grid-column: 1 / -1;
      }
      .stats {
        grid-template-columns: repeat(3, minmax(0, 1fr));
      }
    }
    [data-theme="dark"] {
      color-scheme: dark;
      --bg: #0f1117;
      --panel: #1a1d27;
      --panel-2: #21242f;
      --text: #e0e4ec;
      --muted: #8b92a5;
      --line: #2e3345;
      --accent: #34d399;
      --accent-2: #60a5fa;
      --danger: #f87171;
      --warn: #fbbf24;
      --ok: #4ade80;
      --shadow: 0 1px 3px rgba(0, 0, 0, 0.4);
    }
    [data-theme="dark"] .badge { background: #2e3345; color: #8b92a5; }
    [data-theme="dark"] .badge.done,
    [data-theme="dark"] .badge.success { background: #064e3b; color: #6ee7b7; }
    [data-theme="dark"] .badge.doing,
    [data-theme="dark"] .badge.followup,
    [data-theme="dark"] .badge.checking { background: #1e3a5f; color: #93c5fd; }
    [data-theme="dark"] .badge.blocked,
    [data-theme="dark"] .badge.not_success { background: #450a0a; color: #fca5a5; }
    [data-theme="dark"] .badge.todo,
    [data-theme="dark"] .badge.created,
    [data-theme="dark"] .badge.defined,
    [data-theme="dark"] .badge.classified { background: #422006; color: #fde68a; }
    [data-theme="dark"] .ledger-button.is-selected { background: #1a2e2a; }
    [data-theme="dark"] .child-row { background: #1e2130; }
    [data-theme="dark"] .text-block { background: #14161f; }
    [data-theme="dark"] button:hover { border-color: #4b5563; }
    [data-theme="dark"] .problem-row:hover,
    [data-theme="dark"] .child-row:hover { border-color: #4b5563; }
    [data-theme="dark"] .problem-row.is-selected,
    [data-theme="dark"] .child-row.is-selected { border-color: var(--accent); box-shadow: 0 0 0 2px rgba(52, 211, 153, 0.15); }
    .theme-toggle {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      font-size: 13px;
      min-height: 34px;
    }
    .theme-toggle svg { width: 16px; height: 16px; }
    .progress-ring { flex-shrink: 0; }
    .progress-ring .track { stroke: var(--line); }
    .progress-ring .fill { stroke: var(--accent); transition: stroke-dashoffset 0.4s ease; }
    .progress-ring text { fill: var(--text); font-family: var(--sans); font-weight: 700; }
    @media (max-width: 780px) {
      .topbar {
        grid-template-columns: 1fr;
      }
      .toolbar {
        justify-content: stretch;
      }
      .toolbar input,
      .toolbar select {
        width: 100%;
      }
      .layout {
        height: auto;
        min-height: calc(100vh - 73px);
        grid-template-columns: 1fr;
        grid-template-rows: 360px auto 420px;
      }
      .stats {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
    }
    @media print {
      .topbar, .sidebar, .toolbar, .view-tabs, #graphContainer, .theme-toggle { display: none !important; }
      .layout { display: block !important; height: auto !important; }
      .main { overflow: visible !important; }
      .details { overflow: visible !important; max-height: none !important; }
      .tree-node { page-break-inside: avoid; }
      body { background: white; color: black; font-size: 11px; }
      .badge { border: 1px solid #999; }
    }
  </style>
</head>
<body>
  <div class="app">
    <header class="topbar">
      <div class="title">
        <h1>Recursive Closure Dashboard</h1>
        <p id="subtitle"></p>
      </div>
      <div class="toolbar">
        <input id="search" type="search" placeholder="Search ledger, problem, ticket, result, check">
        <select id="statusFilter">
          <option value="all">All statuses</option>
          <option value="open">Open ledgers</option>
          <option value="done">Done</option>
          <option value="blocked">Blocked</option>
          <option value="followup">Has follow-up</option>
        </select>
        <button id="themeToggle" class="theme-toggle" type="button" aria-label="Toggle dark mode">
          <svg id="themeIcon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>
          Light
        </button>
        <button id="expandAll" type="button">Expand</button>
        <button id="collapseAll" type="button">Collapse</button>
        <button id="exportJson" type="button">Export JSON</button>
      </div>
    </header>
    <div class="layout">
      <aside class="sidebar">
        <div class="panel-head">
          <h2>Ledgers</h2>
          <p id="ledgerSummary"></p>
        </div>
        <div class="scroll">
          <ul id="ledgerList" class="ledger-list"></ul>
        </div>
      </aside>
      <main class="main">
        <section id="stats" class="stats"></section>
        <section id="ledgerHeader" class="ledger-header"></section>
        <div class="view-tabs">
          <button class="view-tab active" data-view="tree" type="button">Tree</button>
          <button class="view-tab" data-view="graph" type="button">Graph</button>
        </div>
        <section class="scroll" style="position:relative">
          <div id="tree" class="tree"></div>
          <div id="graphContainer" class="graph-container"></div>
          <div id="graphTooltip" class="graph-tooltip"></div>
        </section>
      </main>
      <aside class="details">
        <div class="panel-head">
          <h2>Details</h2>
          <p>Click any problem, ticket, result, or check.</p>
        </div>
        <div id="details" class="scroll details-body"></div>
      </aside>
    </div>
  </div>
  <script>
    window.DASHBOARD_DATA = ${json};
  </script>
  <script>
    const data = window.DASHBOARD_DATA;

    // Theme
    const THEME_KEY = "cp-dashboard-theme";
    function applyTheme(theme) {
      document.documentElement.setAttribute("data-theme", theme);
      localStorage.setItem(THEME_KEY, theme);
      const btn = document.getElementById("themeToggle");
      const sun = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>';
      const moon = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z"/></svg>';
      btn.innerHTML = (theme === "dark" ? sun : moon) + " " + (theme === "dark" ? "Light" : "Dark");
    }
    const savedTheme = localStorage.getItem(THEME_KEY) || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    applyTheme(savedTheme);
    document.getElementById("themeToggle").addEventListener("click", () => {
      applyTheme(document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark");
    });

    function progressRing(pct, size, stroke) {
      const r = (size - stroke) / 2;
      const c = 2 * Math.PI * r;
      const offset = c - (Math.min(Math.max(pct, 0), 100) / 100) * c;
      const showLabel = size >= 40;
      return '<svg class="progress-ring" width="' + size + '" height="' + size + '" viewBox="0 0 ' + size + " " + size + '">' +
        '<circle class="track" cx="' + size / 2 + '" cy="' + size / 2 + '" r="' + r + '" fill="none" stroke-width="' + stroke + '"/>' +
        '<circle class="fill" cx="' + size / 2 + '" cy="' + size / 2 + '" r="' + r + '" fill="none" stroke-width="' + stroke + '" stroke-linecap="round" stroke-dasharray="' + c + '" stroke-dashoffset="' + offset + '" transform="rotate(-90 ' + size / 2 + " " + size / 2 + ')"/>' +
        (showLabel ? '<text x="' + size / 2 + '" y="' + size / 2 + '" text-anchor="middle" dominant-baseline="central" font-size="' + Math.round(size * 0.28) + '">' + Math.round(pct) + '%</text>' : "") +
        '</svg>';
    }
    const state = {
      selectedLedgerId: location.hash ? decodeURIComponent(location.hash.slice(1)) : (data.active_ledger_id || data.ledgers[0]?.ledger_id || ""),
      selectedEntity: null,
      query: "",
      statusFilter: "all",
      forceOpen: null,
      toggledNodes: new Set(),
    };

    const byId = (id) => document.getElementById(id);
    const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#039;",
    })[char]);
    const statusBadge = (status) => '<span class="badge ' + escapeHtml(status || "unknown") + '">' + escapeHtml(status || "unknown") + '</span>';
    const compactDate = (value) => {
      if (!value) return "-";
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return value;
      return date.toLocaleString([], { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
    };
    const normalizeText = (value) => String(value ?? "").toLowerCase();
    const selectedLedger = () => data.ledgers.find((ledger) => ledger.ledger_id === state.selectedLedgerId) || data.ledgers[0];

    function matchesQuery(ledger, query) {
      if (!query) return true;
      const haystack = [
        ledger.ledger_id,
        ledger.title,
        ledger.status,
        ...ledger.problems.flatMap((item) => [item.id, item.title, item.status, item.description]),
        ...ledger.tickets.flatMap((item) => [item.id, item.title, item.status, item.classification, item.problem_definition, item.proposed_solution]),
        ...ledger.results.flatMap((item) => [item.id, item.summary, ...(item.done || []), ...(item.verification || [])]),
        ...ledger.checks.flatMap((item) => [item.id, item.summary, item.status, ...(item.evidence || []), ...(item.blocking_gaps || [])]),
      ].join(" ").toLowerCase();
      return haystack.includes(query);
    }

    function matchesStatus(ledger, filter) {
      if (filter === "all") return true;
      if (filter === "open") return ledger.status !== "done";
      if (filter === "done") return ledger.status === "done";
      if (filter === "blocked") return ledger.counts.blocked > 0;
      if (filter === "followup") return ledger.counts.followup > 0 || ledger.problems.some((problem) => (problem.followup_ids || []).length > 0);
      return true;
    }

    function renderSubtitle() {
      byId("subtitle").textContent = data.workspace + " · " + data.ledger_dir + " · generated " + compactDate(data.generated_at);
      byId("ledgerSummary").textContent = data.totals.ledgers + " ledgers · " + data.totals.problems + " problems · " + data.totals.open + " open";
    }

    function renderLedgers() {
      const query = normalizeText(state.query);
      const ledgers = data.ledgers.filter((ledger) => matchesStatus(ledger, state.statusFilter) && matchesQuery(ledger, query));
      byId("ledgerList").innerHTML = ledgers.map((ledger) => {
        const selected = ledger.ledger_id === selectedLedger()?.ledger_id ? " is-selected" : "";
        const active = ledger.ledger_id === data.active_ledger_id ? '<span class="badge doing">active</span>' : "";
        const pct = ledger.completion_pct ?? 0;
        return '<li class="ledger-item"><button class="ledger-button' + selected + '" data-ledger-id="' + escapeHtml(ledger.ledger_id) + '">' +
          '<div class="ledger-title"><strong>' + escapeHtml(ledger.title) + '</strong><span style="display:flex;align-items:center;gap:6px">' + progressRing(pct, 24, 3) + statusBadge(ledger.status) + '</span></div>' +
          '<div class="ledger-meta"><span>' + escapeHtml(ledger.ledger_id) + '</span>' + active + '<span>' + compactDate(ledger.updated_at) + '</span></div>' +
          '<div class="ledger-meta"><span>' + ledger.counts.problems + 'P</span><span>' + ledger.counts.tickets + 'T</span><span>' + ledger.counts.results + 'R</span><span>' + ledger.counts.checks + 'C</span><span>' + ledger.counts.open + ' open</span></div>' +
          '</button></li>';
      }).join("") || '<li class="empty">No ledgers match the current filters.</li>';
    }

    function renderStats(ledger) {
      const pct = ledger?.completion_pct ?? 0;
      const stats = [
        ["Ledgers", data.totals.ledgers],
        ["Problems", ledger?.counts.problems ?? 0],
        ["Tickets", ledger?.counts.tickets ?? 0],
        ["Results", ledger?.counts.results ?? 0],
        ["Checks", ledger?.counts.checks ?? 0],
        ["Open", ledger?.counts.open ?? 0],
      ];
      const ringHtml = '<div class="stat" style="display:flex;align-items:center;justify-content:center">' + progressRing(pct, 48, 4) + '</div>';
      byId("stats").innerHTML = ringHtml + stats.map(([label, value]) => '<div class="stat"><div class="value">' + escapeHtml(value) + '</div><div class="label">' + escapeHtml(label) + '</div></div>').join("");
    }

    function indexById(items) {
      return Object.fromEntries(items.map((item) => [item.id, item]));
    }

    function entitySearchText(entity) {
      return normalizeText(JSON.stringify(entity));
    }

    function bodyLink(ledger, bodyPath) {
      if (!bodyPath) return "";
      return data.ledger_dir_from_output + "/" + ledger.ledger_id + "/" + bodyPath;
    }

    function renderPtrcRows(ledger, problem, indexes) {
      const rows = [];
      for (const ticketId of problem.ticket_ids || []) {
        const ticket = indexes.tickets[ticketId];
        if (ticket) rows.push(renderChildRow(ledger, "ticket", ticket, "T", ticket.status + (ticket.classification ? " · " + ticket.classification : "")));
      }
      for (const resultId of problem.result_ids || []) {
        const result = indexes.results[resultId];
        if (result) rows.push(renderChildRow(ledger, "result", result, "R", result.summary || "result"));
      }
      for (const checkId of problem.check_ids || []) {
        const check = indexes.checks[checkId];
        if (check) rows.push(renderChildRow(ledger, "check", check, "C", check.summary || check.status));
      }
      return rows.length ? '<div class="ptrc">' + rows.join("") + '</div>' : "";
    }

    function renderChildRow(ledger, type, entity, label, subtitle) {
      const selected = state.selectedEntity?.type === type && state.selectedEntity?.id === entity.id ? " is-selected" : "";
      const link = bodyLink(ledger, entity.body_path);
      return '<div class="child-row' + selected + '" data-entity-type="' + type + '" data-entity-id="' + escapeHtml(entity.id) + '">' +
        '<span class="type-pill">' + label + '</span>' +
        '<span class="row-title"><strong>' + escapeHtml(entity.id + ": " + (entity.title || entity.summary || entity.status || "")) + '</strong><span>' + escapeHtml(subtitle || "") + '</span></span>' +
        '<span class="entity-meta">' + (entity.status ? statusBadge(entity.status) : "") + (link ? '<a href="' + escapeHtml(link) + '" target="_blank" rel="noreferrer">body</a>' : "") + '</span>' +
        '</div>';
    }

    function renderProblemNode(ledger, problem, childrenMap, indexes, query) {
      const children = childrenMap[problem.id] || [];
      const descendantHtml = children.map((child) => renderProblemNode(ledger, child, childrenMap, indexes, query)).filter(Boolean);
      const selfMatches = !query || entitySearchText(problem).includes(query);
      if (query && !selfMatches && descendantHtml.length === 0) return "";
      const selected = state.selectedEntity?.type === "problem" && state.selectedEntity?.id === problem.id ? " is-selected" : "";
      const defaultOpen = problem.status !== "done";
      const toggled = state.toggledNodes.has(problem.id);
      const isOpen = state.forceOpen === true || query || (state.forceOpen === null && (defaultOpen !== toggled));
      const open = isOpen ? " open" : "";
      const source = problem.created_from_check_id ? "follow-up from " + problem.created_from_check_id : (problem.created_from_ticket_id ? "child from " + problem.created_from_ticket_id : "root");
      const link = bodyLink(ledger, problem.body_path);
      return '<details class="tree-node"' + open + '>' +
        '<summary>' +
          '<div class="problem-row' + selected + '" data-entity-type="problem" data-entity-id="' + escapeHtml(problem.id) + '">' +
            '<span class="chevron">▶</span>' +
            '<span class="row-title"><strong>' + escapeHtml(problem.id + ": " + problem.title) + '</strong><span>' + escapeHtml(source) + '</span></span>' +
            '<span class="entity-meta">' + statusBadge(problem.status) + '<span>' + (problem.ticket_ids || []).length + 'T</span><span>' + (problem.result_ids || []).length + 'R</span><span>' + (problem.check_ids || []).length + 'C</span>' + (link ? '<a href="' + escapeHtml(link) + '" target="_blank" rel="noreferrer">body</a>' : "") + '</span>' +
          '</div>' +
        '</summary>' +
        renderPtrcRows(ledger, problem, indexes) +
        (descendantHtml.length ? '<div class="children">' + descendantHtml.join("") + '</div>' : "") +
      '</details>';
    }

    function renderTree(ledger) {
      if (!ledger) {
        byId("ledgerHeader").innerHTML = '<h2>No ledger data</h2>';
        byId("tree").innerHTML = '<div class="empty">No ledgers found.</div>';
        return;
      }
      byId("ledgerHeader").innerHTML =
        '<h2>' + escapeHtml(ledger.title) + '</h2>' +
        '<div class="ledger-meta">' + statusBadge(ledger.status) + '<span>' + escapeHtml(ledger.ledger_id) + '</span><span>updated ' + compactDate(ledger.updated_at) + '</span><span>schema v' + escapeHtml(ledger.schema_version) + '</span></div>';
      const childrenMap = {};
      for (const problem of ledger.problems) {
        const parent = problem.parent_id || "__root__";
        if (!childrenMap[parent]) childrenMap[parent] = [];
        childrenMap[parent].push(problem);
      }
      for (const key of Object.keys(childrenMap)) {
        childrenMap[key].sort((a, b) => a.id.localeCompare(b.id));
      }
      const indexes = {
        tickets: indexById(ledger.tickets),
        results: indexById(ledger.results),
        checks: indexById(ledger.checks),
      };
      const rootProblems = childrenMap.__root__ || ledger.problems.filter((problem) => problem.id === ledger.root_id);
      const query = normalizeText(state.query);
      byId("tree").innerHTML = rootProblems.map((problem) => renderProblemNode(ledger, problem, childrenMap, indexes, query)).filter(Boolean).join("") || '<div class="empty">No tree nodes match the current search.</div>';
    }

    function renderDetails(ledger) {
      if (!ledger) {
        byId("details").innerHTML = '<div class="empty">No details.</div>';
        return;
      }
      const selected = state.selectedEntity || { type: "ledger", id: ledger.ledger_id };
      const collections = {
        ledger: { [ledger.ledger_id]: ledger },
        problem: indexById(ledger.problems),
        ticket: indexById(ledger.tickets),
        result: indexById(ledger.results),
        check: indexById(ledger.checks),
      };
      const entity = collections[selected.type]?.[selected.id] || ledger;
      const type = collections[selected.type]?.[selected.id] ? selected.type : "ledger";
      byId("details").innerHTML = detailHtml(ledger, type, entity);
    }

    function listHtml(values) {
      const items = Array.isArray(values) ? values.filter((item) => item !== "") : [];
      if (!items.length) return '<span class="muted">none</span>';
      return '<ul class="list">' + items.map((item) => '<li>' + escapeHtml(item) + '</li>').join("") + '</ul>';
    }

    function detailHtml(ledger, type, entity) {
      const title = type === "ledger" ? ledger.title : (entity.id + ": " + (entity.title || entity.summary || entity.status || ""));
      const link = entity.body_path ? bodyLink(ledger, entity.body_path) : "";
      const rows = Object.entries({
        type,
        id: entity.id || ledger.ledger_id,
        status: entity.status || ledger.status,
        updated: entity.updated_at || ledger.updated_at,
        created: entity.created_at || ledger.created_at,
        body: link ? '<a href="' + escapeHtml(link) + '" target="_blank" rel="noreferrer">' + escapeHtml(entity.body_path) + '</a>' : "",
      }).filter(([, value]) => value !== "");
      let html = '<h2 class="detail-title">' + escapeHtml(title) + '</h2>';
      html += '<dl class="kv">' + rows.map(([key, value]) => '<dt>' + escapeHtml(key) + '</dt><dd>' + (String(value).startsWith("<a ") ? value : escapeHtml(value)) + '</dd>').join("") + '</dl>';
      const sections = [
        ["Description", entity.description],
        ["Problem Definition", entity.problem_definition],
        ["Proposed Solution", entity.proposed_solution],
        ["Summary", entity.summary],
        ["Success Criteria", entity.success_criteria],
        ["Acceptance Criteria", entity.acceptance_criteria],
        ["Verification Plan", entity.verification_plan],
        ["Done", entity.done],
        ["Verification", entity.verification],
        ["Known Gaps", entity.known_gaps],
        ["Evidence", entity.evidence],
        ["Criteria Map", entity.criteria_map],
        ["Execution Map", entity.execution_map],
        ["Stress Test", entity.stress_test],
        ["Residual Risk", entity.residual_risk],
        ["Blocking Gaps", entity.blocking_gaps],
        ["Artifacts", entity.artifacts],
      ];
      for (const [heading, value] of sections) {
        const hasValue = Array.isArray(value) ? value.length : Boolean(value);
        if (!hasValue) continue;
        html += '<section class="detail-section"><h3>' + escapeHtml(heading) + '</h3>';
        html += Array.isArray(value) ? listHtml(value) : '<div class="text-block">' + escapeHtml(value) + '</div>';
        html += '</section>';
      }
      if (type === "ledger") {
        html += '<section class="detail-section"><h3>Status Counts</h3><div class="text-block">' + escapeHtml(JSON.stringify(ledger.problem_counts, null, 2)) + '</div></section>';
        if (ledger.events && ledger.events.length) {
          const shown = ledger.events.slice(-60).reverse();
          html += '<section class="detail-section"><h3>Timeline (' + ledger.events.length + ' events)</h3><ul class="timeline" style="max-height:320px;overflow:auto">';
          for (const ev of shown) {
            const evDetail = ev.payload ? Object.values(ev.payload).filter(v => typeof v === "string").join(" — ") : "";
            html += '<li class="timeline-item"><span class="timeline-time">' + escapeHtml(compactDate(ev.at || ev.created_at)) + '</span><span class="timeline-dot"></span><div class="timeline-content"><strong>' + escapeHtml(ev.type || "event") + '</strong> <span>' + escapeHtml(evDetail) + '</span></div></li>';
          }
          html += '</ul></section>';
        }
      }
      html += '<p class="footer-note">Body links open the Markdown source from the ledger package.</p>';
      if (entity.body_preview) {
        html += '<section class="detail-section"><h3>Body Preview</h3><pre class="body-preview" style="max-height:400px;overflow:auto;background:var(--panel-2);border:1px solid var(--line);border-radius:6px;padding:12px;font-size:12px;white-space:pre-wrap;word-break:break-word;font-family:var(--mono)">' + escapeHtml(entity.body_preview) + '</pre></section>';
      }
      return html;
    }

    function render() {
      const ledger = selectedLedger();
      if (ledger && state.selectedLedgerId !== ledger.ledger_id) {
        state.selectedLedgerId = ledger.ledger_id;
      }
      renderSubtitle();
      renderLedgers();
      renderStats(ledger);
      renderTree(ledger);
      renderDetails(ledger);
    }

    byId("ledgerList").addEventListener("click", (event) => {
      const button = event.target.closest("[data-ledger-id]");
      if (!button) return;
      state.selectedLedgerId = button.dataset.ledgerId;
      state.selectedEntity = null;
      location.hash = encodeURIComponent(state.selectedLedgerId);
      render();
    });
    byId("tree").addEventListener("click", (event) => {
      const link = event.target.closest("a");
      if (link) return;
      // Chevron click toggles collapse for that node
      const chevron = event.target.closest(".chevron");
      if (chevron) {
        const row = chevron.closest("[data-entity-id]");
        if (row) {
          event.preventDefault();
          event.stopPropagation();
          const id = row.dataset.entityId;
          state.forceOpen = null;
          if (state.toggledNodes.has(id)) state.toggledNodes.delete(id);
          else state.toggledNodes.add(id);
          render();
          return;
        }
      }
      const button = event.target.closest("[data-entity-type]");
      if (!button) return;
      event.preventDefault();
      event.stopPropagation();
      state.selectedEntity = { type: button.dataset.entityType, id: button.dataset.entityId };
      render();
    });
    byId("search").addEventListener("input", (event) => {
      state.query = event.target.value;
      render();
    });
    byId("statusFilter").addEventListener("change", (event) => {
      state.statusFilter = event.target.value;
      render();
    });
    byId("expandAll").addEventListener("click", () => {
      state.toggledNodes.clear();
      state.forceOpen = true;
      render();
    });
    byId("collapseAll").addEventListener("click", () => {
      state.toggledNodes.clear();
      state.forceOpen = false;
      render();
    });

    // Keyboard navigation
    document.addEventListener("keydown", (event) => {
      if (event.target.tagName === "INPUT" || event.target.tagName === "SELECT" || event.target.tagName === "TEXTAREA") return;
      const rows = Array.from(document.querySelectorAll("[data-entity-id]"));
      if (!rows.length) return;
      const currentIdx = rows.findIndex((r) => r.classList.contains("is-selected"));
      if (event.key === "ArrowDown" || event.key === "j") {
        event.preventDefault();
        const nextIdx = currentIdx < rows.length - 1 ? currentIdx + 1 : 0;
        const row = rows[nextIdx];
        state.selectedEntity = { type: row.dataset.entityType, id: row.dataset.entityId };
        render();
        row.scrollIntoView({ block: "nearest" });
      } else if (event.key === "ArrowUp" || event.key === "k") {
        event.preventDefault();
        const prevIdx = currentIdx > 0 ? currentIdx - 1 : rows.length - 1;
        const row = rows[prevIdx];
        state.selectedEntity = { type: row.dataset.entityType, id: row.dataset.entityId };
        render();
        row.scrollIntoView({ block: "nearest" });
      } else if (event.key === "Enter") {
        const selected = rows[currentIdx];
        if (selected) {
          const details = selected.closest("details");
          if (details) details.open = !details.open;
        }
      } else if (event.key === "/") {
        event.preventDefault();
        byId("search").focus();
      }
    });

    // Export JSON
    byId("exportJson").addEventListener("click", () => {
      const ledger = selectedLedger();
      if (!ledger) return;
      const blob = new Blob([JSON.stringify(ledger, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = (ledger.ledger_id || "ledger") + ".json";
      a.click();
      URL.revokeObjectURL(url);
    });

    // View tabs
    let currentView = "tree";
    document.querySelector(".view-tabs").addEventListener("click", (event) => {
      const tab = event.target.closest("[data-view]");
      if (!tab) return;
      currentView = tab.dataset.view;
      document.querySelectorAll(".view-tab").forEach((t) => t.classList.toggle("active", t.dataset.view === currentView));
      byId("tree").style.display = currentView === "tree" ? "" : "none";
      const gc = byId("graphContainer");
      gc.classList.toggle("visible", currentView === "graph");
      if (currentView === "graph") renderGraph(selectedLedger());
    });

    // D3 Force Graph
    let graphSim = null;
    function renderGraph(ledger) {
      const container = byId("graphContainer");
      container.innerHTML = "";
      if (!ledger || typeof d3 === "undefined") {
        container.innerHTML = '<div class="empty">No graph data or D3 not loaded.</div>';
        return;
      }
      const rect = container.getBoundingClientRect();
      const w = rect.width || 600;
      const h = rect.height || 400;

      const statusColor = (s) => {
        const colors = { done: "#16a34a", doing: "#2563eb", checking: "#2563eb", followup: "#2563eb", blocked: "#dc2626", todo: "#d97706", created: "#d97706", defined: "#d97706", classified: "#d97706", success: "#16a34a", not_success: "#dc2626" };
        return colors[s] || "#6b7280";
      };
      const typeRadius = { problem: 8, ticket: 6, result: 5, check: 5 };

      const nodes = [];
      const links = [];
      const nodeMap = {};

      for (const p of ledger.problems) {
        const n = { id: p.id, label: p.id, title: p.title, type: "problem", status: p.status, entity: p };
        nodes.push(n);
        nodeMap[p.id] = n;
      }
      for (const t of ledger.tickets) {
        const n = { id: t.id, label: t.id, title: t.title, type: "ticket", status: t.status, entity: t };
        nodes.push(n);
        nodeMap[t.id] = n;
        if (t.problem_id && nodeMap[t.problem_id]) links.push({ source: t.problem_id, target: t.id });
      }
      for (const r of ledger.results) {
        const n = { id: r.id, label: r.id, title: r.summary, type: "result", status: "done", entity: r };
        nodes.push(n);
        nodeMap[r.id] = n;
        if (r.ticket_id && nodeMap[r.ticket_id]) links.push({ source: r.ticket_id, target: r.id });
      }
      for (const c of ledger.checks) {
        const n = { id: c.id, label: c.id, title: c.summary, type: "check", status: c.status, entity: c };
        nodes.push(n);
        nodeMap[c.id] = n;
        if (c.problem_id && nodeMap[c.problem_id]) links.push({ source: c.problem_id, target: c.id });
      }
      for (const p of ledger.problems) {
        if (p.parent_id && nodeMap[p.parent_id]) links.push({ source: p.parent_id, target: p.id });
      }

      const svg = d3.select(container).append("svg").attr("viewBox", [0, 0, w, h]);
      const g = svg.append("g");
      svg.call(d3.zoom().scaleExtent([0.3, 4]).on("zoom", (event) => g.attr("transform", event.transform)));

      const link = g.append("g").selectAll("line").data(links).join("line").attr("class", "graph-link").attr("stroke-width", 1.5);
      const node = g.append("g").selectAll("g").data(nodes).join("g").attr("class", "graph-node");
      node.append("circle").attr("r", (d) => typeRadius[d.type] || 6).attr("fill", (d) => statusColor(d.status)).attr("stroke", (d) => {
        const q = normalizeText(state.query);
        if (q && normalizeText(JSON.stringify(d.entity)).includes(q)) return "#f59e0b";
        return "var(--panel)";
      }).attr("stroke-width", (d) => {
        const q = normalizeText(state.query);
        if (q && normalizeText(JSON.stringify(d.entity)).includes(q)) return 3;
        return 1.5;
      });
      node.append("text").attr("class", "graph-label").attr("dy", -12).attr("text-anchor", "middle").text((d) => d.label);

      const tooltip = byId("graphTooltip");
      node.on("mouseover", (event, d) => {
        tooltip.style.opacity = "1";
        tooltip.innerHTML = '<strong>' + escapeHtml(d.id) + '</strong><br>' + escapeHtml(d.title || "") + '<br><span class="badge ' + escapeHtml(d.status) + '">' + escapeHtml(d.status) + '</span>';
      }).on("mousemove", (event) => {
        const cr = container.getBoundingClientRect();
        tooltip.style.left = (event.clientX - cr.left + 12) + "px";
        tooltip.style.top = (event.clientY - cr.top - 10) + "px";
      }).on("mouseout", () => { tooltip.style.opacity = "0"; })
        .on("click", (event, d) => {
          state.selectedEntity = { type: d.type, id: d.id };
          render();
        });

      node.call(d3.drag().on("start", (event, d) => {
        if (!event.active) graphSim.alphaTarget(0.3).restart();
        d.fx = d.x; d.fy = d.y;
      }).on("drag", (event, d) => {
        d.fx = event.x; d.fy = event.y;
      }).on("end", (event, d) => {
        if (!event.active) graphSim.alphaTarget(0);
        d.fx = null; d.fy = null;
      }));

      if (graphSim) graphSim.stop();
      graphSim = d3.forceSimulation(nodes)
        .force("link", d3.forceLink(links).id((d) => d.id).distance(60))
        .force("charge", d3.forceManyBody().strength(-120))
        .force("center", d3.forceCenter(w / 2, h / 2))
        .force("collision", d3.forceCollide().radius(16))
        .on("tick", () => {
          link.attr("x1", (d) => d.source.x).attr("y1", (d) => d.source.y).attr("x2", (d) => d.target.x).attr("y2", (d) => d.target.y);
          node.attr("transform", (d) => "translate(" + d.x + "," + d.y + ")");
        });
    }

    render();
  </script>
  <script src="https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js" async
    onerror="document.getElementById('graphContainer').innerHTML='<div class=\\'empty\\'>D3 library failed to load. Graph view requires an internet connection or a local D3 installation.</div>';"></script>
  <script>
    (function() {
      var delay = 1000;
      function connect() {
        var ws = new WebSocket("ws://" + location.host + "/_ws");
        ws.onopen = function() { delay = 1000; document.title = document.title.replace(/ \\[offline\\]$/, ""); };
        ws.onmessage = function(ev) { if (ev.data === "reload") location.reload(); };
        ws.onclose = function() {
          document.title = document.title.replace(/ \\[offline\\]$/, "") + " [offline]";
          setTimeout(connect, delay);
          delay = Math.min(delay * 2, 30000);
        };
      }
      connect();
    })();
  </script>
</body>
</html>
`;
}

// ── WebSocket server (RFC 6455 manual handshake) ──

const WS_GUID = "258EAFA5-E914-47DA-95CA-5AB5DC525B27";

function createWsServer(httpServer) {
  const clients = new Set();

  httpServer.on("upgrade", (req, socket) => {
    if (req.url !== "/_ws") { socket.destroy(); return; }
    const key = req.headers["sec-websocket-key"];
    if (!key) { socket.destroy(); return; }
    const accept = crypto.createHash("sha1").update(key + WS_GUID).digest("base64");
    socket.write(
      "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: " + accept + "\r\n\r\n"
    );
    clients.add(socket);
    socket.on("close", () => clients.delete(socket));
    socket.on("error", () => clients.delete(socket));
  });

  function sendFrame(socket, text) {
    const payload = Buffer.from(text, "utf8");
    const header = [0x81];
    if (payload.length < 126) {
      header.push(payload.length);
    } else if (payload.length < 65536) {
      header.push(126, (payload.length >> 8) & 0xff, payload.length & 0xff);
    } else {
      header.push(127, 0, 0, 0, 0,
        (payload.length >> 24) & 0xff,
        (payload.length >> 16) & 0xff,
        (payload.length >> 8) & 0xff,
        payload.length & 0xff);
    }
    socket.write(Buffer.concat([Buffer.from(header), payload]));
  }

  return {
    broadcast(msg) {
      for (const s of clients) { try { sendFrame(s, msg); } catch { clients.delete(s); } }
    },
    get clientCount() { return clients.size; },
  };
}

// ── HTTP server with file watching and live reload ──

function openBrowser(url) {
  const cmd = process.platform === "darwin" ? "open" : "xdg-open";
  try { const c = spawn(cmd, [url], { detached: true, stdio: "ignore" }); c.unref(); } catch {}
}

function serveMode(rootDir, args) {
  const absoluteLedgerDir = path.resolve(rootDir, args.ledgerDir);

  function generateHtml() {
    const data = collectDashboardData(rootDir, args.ledgerDir, args.ledgerDir + "/dashboard.html");
    return renderHtml(data);
  }

  let cachedHtml = generateHtml();

  const server = http.createServer((req, res) => {
    if (req.url === "/" || req.url === "/index.html") {
      res.writeHead(200, { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-cache" });
      res.end(cachedHtml);
    } else {
      res.writeHead(404, { "Content-Type": "text/plain" });
      res.end("Not found");
    }
  });

  const ws = createWsServer(server);

  let debounce = null;
  function onFileChange(_event, filename) {
    if (!filename) return;
    if (!filename.endsWith("state.json") && !filename.endsWith("events.jsonl") && !filename.endsWith("INDEX.json")) return;
    clearTimeout(debounce);
    debounce = setTimeout(() => {
      try {
        cachedHtml = generateHtml();
        console.log(`[serve] refreshed (${ws.clientCount} client(s))`);
        ws.broadcast("reload");
      } catch (err) {
        console.error("[serve] refresh error:", err.message);
      }
    }, 300);
  }

  let watcher;
  try {
    watcher = fs.watch(absoluteLedgerDir, { recursive: true }, onFileChange);
  } catch {
    console.error(`Warning: could not watch ${absoluteLedgerDir}. Timer-based refresh still works in-browser.`);
  }

  const port = args.port;
  server.on("error", (err) => {
    if (err.code === "EADDRINUSE") {
      console.error(`Port ${port} is already in use. Try --port ${port + 1}`);
      process.exit(1);
    }
    throw err;
  });
  server.listen(port, () => {
    const url = `http://localhost:${port}`;
    console.log(`Dashboard server running at ${url}`);
    console.log(`Watching ${toPosix(path.relative(rootDir, absoluteLedgerDir))} for changes`);
    console.log("Press Ctrl+C to stop.");
    openBrowser(url);
  });

  function shutdown() {
    console.log("\nShutting down...");
    if (watcher) watcher.close();
    server.close();
    process.exit(0);
  }
  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  const rootDir = path.resolve(args.workspace);
  serveMode(rootDir, args);
}

main();
