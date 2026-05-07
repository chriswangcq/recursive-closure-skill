---
name: recursive-closure-skill
description: "Solve complex, ambiguous, multi-step problems with a recursive closure loop and schema-v6 problem-package ledger. Use when work needs durable problem/ticket/result/check state, Markdown body files, recursive subproblems, strict success checks, follow-up gap closure, phase planning, or agent-executed tickets."
---

# Recursive Closure Skill

## Mission

Use this skill to turn complex work into a closed recursive loop:

```text
solve(problem):
  ticket = create_ticket(problem)

  # do ticket start

  classify(ticket) as one_go or split

  if one_go:
    result = execute_ticket(ticket)
    # During execution, the ticket may spawn blocking child problems
    # when a needed subprogram is discovered.
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

Keep these meanings separate:

- `problem`: the original thing that must be solved.
- `ticket`: the current proposed solution path.
- `result`: what execution actually produced.
- `check_success`: the judge of whether the problem is truly solved.
- `followup`: the smallest problem that closes a detected gap.

Ticket done means the ticket path produced a recorded result. Problem done means `check_success(problem, result_with_followups)` proved the original problem is solved.

Child creation has three distinct meanings:

- `split`: plan-time children from a `split` ticket before execution.
- `spawn`: run-time children from an `executing` `one_go` ticket when execution discovers a needed subprogram.
- `follow-up`: check-time children from `not_success` when verification finds a gap.

Do not blur these meanings. Split is planning, spawn is execution-time subprogram call, and follow-up is repair after failed checking.

## When To Use The Ledger

Use the file-system ledger when the task is complex, important, resumable, multi-step, research-heavy, implementation-heavy, phase-based, or the user asks about tickets, status, checks, phases, or closure.

For tiny one-shot tasks, you may keep state in chat. If unsure, use the ledger.

The bundled script is the source of truth:

```bash
scripts/ledger.py ...
```

Resolve `scripts/ledger.py` relative to this skill directory.

The bundled dashboard renderer is read-only and can visualize any workspace that contains `.complex-problems`:

```bash
node scripts/render-dashboard.mjs --workspace /path/to/workspace
```

By default this writes `/path/to/workspace/.complex-problems/dashboard.html`.

## Hard Rules

- Do exactly one `next_action` at a time.
- Treat the current agent as both Root Agent and Worker Agent unless a separate worker is explicitly delegated.
- As Root Agent, drive the loop: run `scripts/ledger.py next`, choose/dispatch the current `next_action`, record the worker output through the CLI, then run `next` again.
- As Worker Agent, do only the concrete work in the current `next_instruction`: write ticket/result/check bodies, execute the task, classify, split, or verify.
- For delegated worker behavior, attach or read the matching worker instruction from `references/workers/index.md`.
- The CLI state machine is the only authority for legal transitions. The agent supplies judgment and content; the CLI decides whether the move is legal.
- Before choosing any state-changing command, run `scripts/ledger.py next`.
- After each state-changing command bundle for the current `next_action`, run `scripts/ledger.py next` again.
- If `next` repeats the same action after a preparatory command such as `set-status`, continue only that same action.
- Do not use the command examples below as a linear script. They are allowed commands for the current `next_action` only.
- Before recording any `result`, the problem must be `doing` or `followup`.
- Before running `check_success`, the problem must not still be `todo`.
- Every problem gets a ticket before classification.
- Classify only after the ticket is defined.
- Ticket classification is exactly `one_go` or `split`.
- Do not mark a problem done from execution alone.
- A success check must include explicit result IDs, evidence, criteria map, execution map, stress test, and residual risk.
- If verification is weak, record `not_success`, create a follow-up, and solve it.
- Do not hide gaps in summaries. Record gaps and close them or report a blocker.
- Do not choose `one_go` lightly. Use it only when the work is genuinely small, concrete, low-risk, and easy to verify in one bounded attempt.
- When in doubt, choose `split`. Do not be afraid of extra problems, tickets, results, and checks; the ledger exists to make that work cheap and explicit.
- Check `one_go` results with extra skepticism. A fast execution path must still prove the original criteria with evidence, stress testing, and residual-risk review.
- Do not use legacy ticket fields: `objective`, `scope`, `expected_result`, or ticket-level `verification`.
- The ledger is schema v6 only on this experimental branch. Delete or reinitialize old ledgers instead of migrating or normalizing them.
- Each problem has at most one ticket. Create a child or follow-up problem instead of adding a second ticket to the same problem.
- Tickets never use `blocked`; record a result and let problem-level checks/follow-ups represent failure, gaps, or blockers.
- Public `set-status` is only a preparatory command: problem -> `doing`, ticket -> `executing` or `splitting`. `result` and `check` own terminal outcomes.
- A done problem is terminal. Create an explicit new problem for later work; do not reopen it through `check` or `set-status`.
- Split child problems are created with `create-problem --from-ticket --mode split --from-file` from a splitting split ticket.
- Runtime-spawned child problems are created with `create-problem --from-ticket --mode spawn --from-file` from an executing one_go ticket.
- Follow-up problems are created only by `check --status not_success --followup-from-file`.
- Child problems are never created from thin air: every child must be split-time, spawn-time, or check-time with explicit provenance.
- A ticket cannot record its final result while any child problem created from that ticket is still open.
- Write every problem, ticket, result, and check as a Markdown body file. State-changing PTRC write commands require `--from-file`.
- Markdown body files are the required content layer; CLI flags are the state-machine contract for IDs, relations, statuses, and rare explicit overrides. If the CLI rejects a command, fix the body shape rather than bypassing the transition.
- Treat `state.json` as IDs/status/relations only. Treat body Markdown as the content layer.
- Do not store a top-level ledger status. Derive ledger status from problem statuses.
- Treat each problem directory as the work package. Tickets, results, checks, follow-ups, and child problems for that problem live under that package.
- Do not edit `views/*.md` as state. They are rendered from `state.json`.
- Prefer `ledger.py next` as the guide between actions.
- `next` schedules the runnable frontier leaf. A problem with open child or follow-up problems is open but not runnable; solve its children first.

## Next-Gated Loop

Start or select a ledger:

```bash
scripts/ledger.py list
scripts/ledger.py init --from-file path/to/root-problem.md
scripts/ledger.py use L20260507-001
scripts/ledger.py status
scripts/ledger.py next
```

Then obey `next_instruction`.

Do not skip ahead. Match `next_action` to exactly one row:

| next_action | Allowed agent move |
| --- | --- |
| `create-solution-ticket` | Create one v6 ticket for the shown problem. |
| `define-ticket` | Complete the current ticket definition; normal CLI-created tickets should already be complete. |
| `classify-ticket` | Classify the shown ticket as `one_go` or `split`. |
| `execute-ticket` | Execute the shown ticket; record its result, or spawn a blocking runtime child if execution discovers a needed subprogram. |
| `split-ticket` | Move the shown ticket to `splitting`, then create plan-time child problems from it. |
| `record-result` | Record the result for the shown ticket only. |
| `check-success` | Run `check --status success` or `check --status not_success` for the shown problem. |
| `unblock-or-report` | Report the blocker or move the problem back to `doing` after the blocker is resolved. |
| `none` | Validate, render, status, and summarize. |

After the allowed move, run `scripts/ledger.py next` before doing anything else.

Worker instruction mapping:

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

### Command Examples

Use these commands only when the current `next_action` allows them.

`--from-file` parses exact Markdown sections. Use `# title` plus the `##` headings shown below. If a command fails with a missing-field error, fix the body file first.

For every `--from-file` or `--followup-from-file` write, prefer the `mktemp` + single-quoted heredoc pattern when the body is only an input to the ledger and does not need to remain as a repo artifact:

```bash
tmp=$(mktemp)
cat > "$tmp" <<'EOF'
# Body title

## Required Section

Write the full Markdown body here.
EOF

# Example:
scripts/ledger.py result --ticket T000 --from-file "$tmp"
```

Use `<<'EOF'` so shell variables, backticks, and command substitutions inside the Markdown body are not expanded. This pattern applies to root problems, child problems, follow-up problems, tickets, results, and checks. If the body should be reviewed or reused later, write it to an explicit workspace path instead; either way, pass the file with `--from-file`.

Create a problem body for `init`, `split-ticket` child problems, `execute-ticket` spawned child problems, or `not_success` follow-up problems:

```md
# Problem title

## Problem

Describe the problem, scope, context, and why it matters.

## Success Criteria

- Concrete criterion
```

Submit the root problem:

```bash
scripts/ledger.py init --from-file path/to/root-problem.md
```

Create a split child problem only when the current `next_action` is `split-ticket`:

```bash
scripts/ledger.py set-status ticket T000 splitting
scripts/ledger.py create-problem --parent P000 --from-ticket T000 --mode split --from-file path/to/subproblem.md
```

Create a runtime-spawned child problem only during `execute-ticket`, after the ticket is executing:

```bash
scripts/ledger.py set-status problem P000 doing
scripts/ledger.py set-status ticket T000 executing
scripts/ledger.py create-problem --parent P000 --from-ticket T000 --mode spawn --from-file path/to/spawned-subproblem.md
```

Create a ticket body for `create-solution-ticket`:

```md
# Ticket title

## Problem Definition

## Proposed Solution

## Acceptance Criteria

-

## Verification Plan

## Risks

-

## Assumptions

-
```

Submit it:

```bash
scripts/ledger.py create-ticket --problem P000 --from-file path/to/ticket.md
```

The body must start with `# Ticket title`; the positional ticket title is only an optional override.

Classify it:

```bash
scripts/ledger.py classify-ticket T000 --classification one_go --reason "Small, safe, and directly verifiable"
scripts/ledger.py classify-ticket T000 --classification split --reason "Requires child problems"
```

For `one_go`, execute the work outside the ledger. If execution discovers a needed subprogram, spawn it from the executing ticket and stop this action; `next` will route to the child before returning to the parent result:

```bash
scripts/ledger.py set-status problem P000 doing
scripts/ledger.py set-status ticket T000 executing
scripts/ledger.py create-problem --parent P000 --from-ticket T000 --mode spawn --from-file path/to/spawned-subproblem.md
scripts/ledger.py next
```

If no spawned child is needed, write a result body:

```md
# Result summary

## Summary

## Done

-

## Verification

-

## Known Gaps

- none

## Artifacts

-
```

Submit it:

```bash
scripts/ledger.py set-status problem P000 doing
scripts/ledger.py result --ticket T000 --from-file path/to/result.md
```

For `split`, move the ticket into splitting, create child problem bodies, then let `next` guide you:

```bash
scripts/ledger.py set-status ticket T000 splitting
scripts/ledger.py create-problem --parent P000 --from-ticket T000 --mode split --from-file path/to/subproblem.md
scripts/ledger.py next
```

For multiple child problems in one `split-ticket` action, use the batch form of the same `mktemp` + heredoc pattern. This keeps each problem body complete without leaving scratch files in the repo. Use this only when the current `next_action` is `split-ticket`, and run `next` immediately after the batch:

```bash
set -e
ledger="scripts/ledger.py"
"$ledger" set-status ticket T000 splitting

for name in runtime handler tests docs; do
  tmp=$(mktemp)
  case "$name" in
    runtime)
      cat > "$tmp" <<'EOF'
# Upgrade runtime schema and FSM

## Problem

Describe the runtime slice, current limitation, and why it must be solved separately.

## Success Criteria

- Concrete runtime criterion.
- Concrete validation criterion.
EOF
      ;;
    handler)
      cat > "$tmp" <<'EOF'
# Wire native handler integration

## Problem

Describe the handler/tooling slice and its boundary.

## Success Criteria

- Concrete handler criterion.
- Concrete tool spec or integration criterion.
EOF
      ;;
    tests)
      cat > "$tmp" <<'EOF'
# Verify the change

## Problem

Describe the verification slice and the risks it must catch.

## Success Criteria

- Unit or integration tests cover the important transition.
- Repository checks pass.
EOF
      ;;
    docs)
      cat > "$tmp" <<'EOF'
# Document the behavior

## Problem

Describe what future agents or humans must understand.

## Success Criteria

- Current behavior is documented.
- Stale or misleading wording is removed.
EOF
      ;;
  esac
  "$ledger" create-problem --parent P000 --from-ticket T000 --mode split --from-file "$tmp"
done

"$ledger" next
```

If the batch fails halfway, run `scripts/ledger.py next` and inspect created children before retrying; do not blindly rerun a partially successful batch.

After children close, record the parent ticket result:

```bash
scripts/ledger.py result --ticket T000 --from-file path/to/result.md
```

Write the problem-level success check body:

```md
# Check summary

## Summary

## Evidence

-

## Criteria Map

- criterion -> evidence

## Execution Map

- ticket/subproblem -> result and verification

## Stress Test

- failure mode -> why fixed or non-blocking

## Residual Risk

-

## Result IDs

- R000

## Blocking Gaps

- none
```

Submit it:

```bash
scripts/ledger.py check --problem P000 --status success --result R000 --from-file path/to/check.md
```

The success check body must contain `## Summary`, `## Evidence`, `## Criteria Map`, `## Execution Map`, `## Stress Test`, `## Residual Risk`, and `## Result IDs`. If any of these are missing or written with a different heading level, the CLI will reject the check.

If not solved, create the follow-up through the check:

```bash
scripts/ledger.py check --problem P000 --status not_success \
  --result R000 \
  --from-file path/to/check.md \
  --followup-from-file path/to/followup-problem.md
scripts/ledger.py next
```

The not-success check body must contain `## Summary` and `## Blocking Gaps`, and the command must include `--followup-from-file` pointing at a problem body for the follow-up.

Before final response:

```bash
scripts/ledger.py validate
scripts/ledger.py render
scripts/ledger.py status
scripts/ledger.py next
```

For code tasks, also run the repository-appropriate final checks before recording the final result or final success check:

- Full test matrix or the nearest project-wide test command.
- Lint/typecheck/architecture guard commands that are relevant to the touched code.
- Generated artifact cleanup or regeneration checks.
- `git diff --stat` and a focused diff review.
- `scripts/ledger.py validate`, `scripts/ledger.py render`, `scripts/ledger.py status`, and `scripts/ledger.py next`.

### Common Failure Recovery

- `init requires --from-file` or `create-problem requires --from-file`: write a problem body with `# title`, `## Problem`, and `## Success Criteria`.
- `create-ticket requires ...`: the ticket body is missing `# title` or one of `## Problem Definition`, `## Proposed Solution`, `## Acceptance Criteria`, `## Verification Plan`. Fix the body, then retry the same `create-ticket`; do not create a second ticket for the problem.
- `success check requires ...`: the check body is missing one of the required success sections. Fix the check body, then retry the same `check`.
- `not_success check requires ...`: include `## Blocking Gaps` in the check body and pass `--followup-from-file` with a follow-up problem body.
- `result requires --from-file` or `result body missing: ## Summary`: write a result body with `# title`, `## Summary`, `## Done`, `## Verification`, `## Known Gaps`, and `## Artifacts`.
- `next` repeats the same action after `set-status`: the status transition was only preparation. Continue the same `next_action` and finish the required result, split, or check.
- `Cannot close problem ... child problems still open`: run `ledger.py next` and solve the child/follow-up problem first.
- `Cannot finish ticket ... child problems still open`: run `ledger.py next` and solve the child spawned or split from that ticket before recording the parent result.
- `Problem already has ticket`: do not add another ticket. Continue the existing ticket path, or create a child/follow-up problem through the legal split/spawn/check path.

## `next` Contract

Treat `scripts/ledger.py next` as the agent guide. It returns the next concrete action, not just a status hint.

Possible `next_action` values:

- `create-solution-ticket`
- `define-ticket`
- `classify-ticket`
- `execute-ticket`
- `split-ticket`
- `record-result`
- `check-success`
- `unblock-or-report`
- `none`

Use `next --json` when machine-readable output is useful.

A single skill invocation is not the same as one ticket. A complex problem may create many problems, tickets, results, checks, and events inside one ledger. That is expected: the unit of closure is the root problem reaching `next_action=none`, not the count of CLI commands.

## Decision Standards

Return `one_go` when the ticket is suitable for one bounded execution attempt before problem-level checking. `one_go` does not mean guaranteed one-shot success; it means the agent should execute as far as safely possible, record the actual result, then let `check_success` decide whether follow-up work is needed.

Use `one_go` only when all of these are true:

- The problem definition is concrete, narrow, and not hiding broad words such as "improve", "optimize", "clean up", or "handle".
- The proposed solution is clear before execution begins.
- Scope fits one focused execution attempt without needing multiple independent success paths.
- Risk is low or reversible.
- Verification is immediate, concrete, and can be performed in the same attempt.
- No unresolved dependency blocks execution.
- Failure would still leave an easy-to-review partial result rather than a vague half-solved state.

Return `split` when:

- The problem has multiple independent outcomes.
- Success requires multiple verification paths.
- Important context is missing.
- The work is high impact or expensive to reverse.
- The prompt is broad, such as "improve", "optimize", "fix", "refactor", "handle", or "make it better".
- You are tempted to say "probably one go" instead of "clearly one go".

If a `one_go` execution discovers a concrete subprogram is needed before the parent ticket can honestly return a result, spawn a blocking child with `create-problem --mode spawn` from the executing ticket. If execution instead produces a partial or failed attempt with no useful subprogram to call immediately, record the partial result with known gaps; the problem-level check creates a follow-up, and that follow-up may be classified as `split`.

## Success Check Standard

`success` requires all of:

- Original problem is satisfied.
- All acceptance criteria are mapped to evidence.
- Every ticket or child problem has a result and verification.
- Stress test names at least one plausible failure mode.
- Residual risks are explicit and non-blocking.
- No hidden TODO, skipped check, vague claim, or known gap remains.

For a `one_go` path, apply a higher burden of proof: the check must show that the shortcut was justified after execution, not merely that the agent made progress. If evidence, stress testing, or residual-risk analysis is thin, choose `not_success` and create a follow-up.

If any item is missing, use `not_success` and solve the follow-up.

## State Model

The ledger stores:

- Problems: `Pxxx`
- Tickets: `Txxx`
- Results: `Rxxx`
- Checks: `Cxxx`
- Events: `events.jsonl`
- Rendered views: `views/*.md`
- Problem package body files:
  - Root problem: `problems/P000/README.md`
  - Child problem: `problems/P000/children/P001/README.md`
  - Problem tickets: `problems/P000/tickets/T000.md`
  - Problem results: `problems/P000/results/R000.md`
  - Problem checks: `problems/P000/checks/C000.md`

Ticket states:

```text
created -> defined -> classified -> executing -> done
created -> defined -> classified -> splitting -> done
```

Problem states:

```text
todo -> doing -> checking -> done
todo -> blocked
doing -> blocked
doing -> followup (internal, via check not_success)
checking -> followup
checking -> doing (retry after failed check without follow-up)
checking -> blocked
followup -> doing
followup -> checking
followup -> blocked
blocked -> doing
```

Do not reopen done tickets or done problems with `set-status`. Create an explicit new problem unless a dedicated reopen command exists.

## Output To User

Respond to the user in their language. If the user writes in Chinese, respond in Chinese; if in English, respond in English. Match the user's language regardless of the `--language` setting on the ledger.

When creating a new ledger with `init`, pass `--language` matching the user's language so that all body content (titles, descriptions, summaries, criteria, evidence) is written in that language. CLI flags and field names always stay in English.

Keep user updates short. Mention:

- Current problem and ticket.
- Whether the ticket is `one_go` or `split`.
- What was executed or split.
- What `check_success` verified.
- Remaining follow-up, blocker, or residual risk.

Do the work after planning unless the user explicitly asks only for planning.
