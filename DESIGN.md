# Recursive Closure Skill Design

This document captures the design rationale behind the schema-v6 recursive closure automaton.

## Core Idea

Complex problem solving is split across four roles:

- **State Machine**: the CLI automaton.
- **Root Agent**: the loop driver.
- **Worker Agent**: the concrete task executor.
- **Markdown / Problem Package**: the durable semantic content layer.

The current runtime normally uses one LLM agent for both Root Agent and Worker Agent. The roles are separated conceptually so the system can later dispatch work to multiple agents without changing the ledger model.

The instruction architecture is intentionally two-layered:

- `scripts/ledger.py next` emits a short dispatch instruction: current goal, boundary, command hints, and the relevant worker file.
- `references/workers/*.md` files carry the detailed action-specific worker behavior.

This keeps CLI output compact while preserving strong, role-specific instructions for delegated workers.

## Recursive Automaton

The target algorithm is:

```text
solve(problem):
  ticket = create_ticket(problem)

  # do ticket start

  classify(ticket) as one_go or split

  if one_go:
    result = execute_ticket(ticket)
    # execution may spawn blocking child problems if a needed
    # subprogram is discovered at run time
  else:
    create child problems from ticket
    child_results = [solve(each child) for each child]
    result = summary_results(child_results)

  record_result_to_ticket(ticket, result)
  mark_done(ticket)
  # do ticket end

  result_with_followups = [result]
  while True:
    check = check_success(problem, result_with_followups)
    if check is success:
      break
    else:
      new_result = solve(check.followup)
      result_with_followups.append(new_result)
```

The key separation is:

- Ticket done means the ticket path produced a recorded result.
- Problem done means `check_success(problem, result_with_followups)` succeeded.
- Failures, gaps, and blockers are represented at result/check/problem level, not as ticket blocked states.

`one_go` means one bounded execution attempt before problem-level checking. It is not a guarantee of one-shot success. If execution discovers a concrete blocking subprogram, the ticket may spawn a runtime child problem and wait for that child to close before recording the parent result. If execution discovers gaps without a useful immediate subprogram, the agent records the partial or failed result, marks the ticket done, and lets `check_success` create a follow-up problem that can itself be classified as `split`.

Child creation has three provenance modes:

- **Plan-time split**: `create-problem --mode split` from a split ticket in `splitting`.
- **Run-time spawn**: `create-problem --mode spawn` from a one_go ticket in `executing`.
- **Check-time follow-up**: `check --status not_success --followup-from-file`.

These are intentionally separate. Split is planned decomposition, spawn is a subprogram call discovered during execution, and follow-up is repair after failed verification.

## Role Responsibilities

### State Machine

The state machine is implemented by `scripts/ledger.py`.

It owns:

- ID allocation: `Pxxx`, `Txxx`, `Rxxx`, `Cxxx`.
- State transitions.
- `next_action` selection.
- Short `next_instruction` dispatch generation.
- Child/follow-up provenance rules.
- Explicit result context for checks.
- Path and relation validation.
- Rendered views.
- Rejection of illegal commands.

It does not own business reasoning, execution, or evidence writing.

### Root Agent

The Root Agent is the orchestrator.

It owns:

- Calling `scripts/ledger.py next`.
- Reading `next_action` and `next_instruction`.
- Reading or attaching the matching `references/workers/*.md` file when delegating work.
- Dispatching the current work item to itself or to a Worker Agent.
- Recording worker output through the CLI.
- Calling `next` again after each state-changing action bundle.
- Driving the recursive loop until `next_action=none`.
- Running final `validate`, `render`, and `status`.

The Root Agent should not invent state transitions. It should treat the CLI as the authority.

### Worker Agent

The Worker Agent handles exactly one concrete `next_instruction` and one matching worker instruction file.

It owns:

- Writing ticket bodies.
- Classifying tickets as `one_go` or `split`.
- Executing one-go work.
- Splitting a ticket into child problems.
- Solving assigned child or follow-up problems.
- Writing result bodies.
- Writing check bodies with evidence, criteria map, execution map, stress test, residual risk, and gaps.

The Worker Agent should not decide the global flow. It returns artifacts or observations for the Root Agent to record.

Worker files are split one-to-one with the public `next_action` values:

| next_action | Worker instruction |
| --- | --- |
| `create-solution-ticket` | `references/workers/create-solution-ticket.md` |
| `define-ticket` | `references/workers/define-ticket.md` |
| `classify-ticket` | `references/workers/classify-ticket.md` |
| `execute-ticket` | `references/workers/execute-ticket.md` |
| `split-ticket` | `references/workers/split-ticket.md` |
| `record-result` | `references/workers/record-result.md` |
| `check-success` | `references/workers/check-success.md` |
| `unblock-or-report` | `references/workers/unblock-or-report.md` |
| `none` | `references/workers/none.md` |

The index file `references/workers/index.md` exists only to map action names to the exact worker instruction file.

### Markdown / Problem Package

Markdown bodies carry rich semantic content while `state.json` remains structural.

The package layout is:

```text
problems/P000/README.md
problems/P000/tickets/T000.md
problems/P000/results/R000.md
problems/P000/checks/C000.md
problems/P000/children/P001/README.md
```

The CLI records paths and relations. Markdown carries the human-readable reasoning and evidence.

## Next Contract

`scripts/ledger.py next` is the Root Agent's guide. It returns:

- `next_action`: the exact action to perform.
- `next_instruction`: a short dispatch instruction.
- `commands`: legal command hints for recording the action.
- context IDs such as problem, ticket, and available result IDs.

The `next_instruction` is intentionally brief. It names the goal and boundary, then points to the detailed worker file. The detailed worker file is where long-form behavior lives.

`next` schedules the runnable frontier leaf. An open parent with open child or follow-up problems is waiting, not runnable; the scheduler should point directly at the deepest open child that can take a concrete action. The parent becomes runnable again only after its open children close.

Example shape:

```text
Only perform `check-success` for `P000: Root problem`.
Goal: judge whether cited results solve the original problem.
Boundary: do not perform new implementation work; create at most one follow-up if not successful.
Detailed worker requirements: `references/workers/check-success.md`.
After this action, run `ledger.py next`.
```

This division prevents `next` output from becoming a second copy of the worker manual.

## CLI Automaton Rules

The CLI enforces rules that LLMs should not improvise:

- Ticket flow is `created -> defined -> classified -> executing/splitting -> done`.
- Tickets do not have `blocked`.
- Any completed ticket attempt records a result and becomes `done`.
- Problem flow includes `todo`, `doing`, `checking`, `followup`, `done`, and `blocked`.
- Each problem has at most one ticket; additional attempts are child or follow-up problems.
- Done problems are terminal unless a future explicit reopen command records a new provenance path.
- Public `set-status` is limited to preparatory moves; `result` and `check` own completion and judgment states.
- Ledger status is derived from problem statuses; there is no separate top-level state status.
- Every problem, ticket, result, and check write requires a Markdown body file.
- Split child problems are created with `create-problem --from-ticket --mode split --from-file` from a splitting split ticket.
- Runtime-spawned child problems are created with `create-problem --from-ticket --mode spawn --from-file` from an executing one_go ticket.
- Follow-up problems are created only by `check --status not_success --followup-from-file`.
- Children created from a ticket must be `done` before the parent ticket can record its summary result.
- Follow-ups are sequential, not parallel; an open follow-up must be solved before another is created for the same parent.
- `check --status success|not_success` must cite explicit `--result` IDs.
- A check can cite only the current problem result plus returned follow-up results.
- A problem can become `done` only through a success check.
- The scheduler distinguishes open from runnable: parents with open children wait; runnable frontier leaves get the next action.

## Why This Shape Works

This design covers both extremes:

- **Auto-planning / reactive execution**: small problems quickly become one bounded execution attempt, one result, one check, and follow-up if needed.
- **Plan-driven decomposition**: broad problems split into child problems, each recursively solved and checked.

The Root Agent does not need a full plan up front. The CLI exposes the next legal move, and recursive closure builds the plan as needed.

The Worker Agent retains the LLM's strength: judgment, writing, code execution, research, and synthesis.

The state machine retains the system's discipline: no skipped checks, no illegal parent closure, no untracked follow-up fan-out, and no hidden state.

## Why Split Worker Instructions By Action

A single generic worker document makes the agent carry too many roles at once. That increases the chance of skip-ahead behavior: an executor starts reviewing, a reviewer starts implementing, or a splitter starts solving child problems.

Action-scoped worker files narrow attention:

- `execute-ticket` workers execute and write result evidence, but do not judge problem success.
- `check-success` workers review evidence, but do not perform new implementation work.
- `split-ticket` workers create child problem bodies, but do not solve them.
- `record-result` workers record the current ticket result, but do not create follow-ups.

That is the core discipline of the system: the Root Agent drives, the Worker Agent focuses, and the CLI enforces.

## Effort Levels

The `--effort` parameter provides a single knob that controls four behavioral surfaces:

- **Classification threshold**: how readily the agent chooses `one_go` vs `split`.
- **Check strictness**: how much evidence, stress testing, and residual-risk analysis is required.
- **Split granularity**: how fine-grained the child problems are.
- **Execution rigor**: how thoroughly the agent investigates edge cases and verifies claims.

Four levels — `low`, `medium`, `high`, `extra-high` — map to short behavioral hints per action type. The hints are defined in `EFFORT_HINTS` in `ledger.py` and injected into the `next_instruction` text that the CLI returns. Worker instruction files (`references/workers/*.md`) remain unchanged across effort levels; the hint in `next_instruction` is the only per-effort modulation.

This design avoids two failure modes:

- **Combinatorial explosion**: three independent knobs (classification, checking, splitting) would create 64 combinations. A single effort level maps to a coherent policy.
- **Worker file drift**: injecting hints at dispatch time keeps worker files as stable, canonical specs. The agent sees the hint once per action without the worker manual being duplicated or forked per effort level.

## Language

The `--language` parameter controls the language of Markdown body content — titles, descriptions, criteria, evidence, and summaries. CLI flags, field names, and state-machine IDs always remain in English.

When `language` is not `en`, the CLI appends a language instruction to `next_instruction`. This instructs the agent to write body content in the specified language while keeping all CLI interaction in English. The agent's conversational replies to the user follow the user's language regardless of this setting (controlled by SKILL.md's "Output To User" section).

This separation means:

- `state.json` is always machine-readable English.
- Body Markdown is human-readable in the user's preferred language.
- Worker instruction files remain English-only canonical references.

