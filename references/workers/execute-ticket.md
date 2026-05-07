# Worker Next Action: execute-ticket

## Mission

Execute the shown `one_go` ticket as one bounded execution attempt.

Produce either:

- a result body, when the parent ticket can honestly return a result now; or
- spawned child problem body files, when execution discovers a needed blocking subprogram.

Do not run problem-level `check_success` in this step. Execution result is not the same as problem success.

## Work

Do the real work required by the ticket. A bounded `one_go` attempt is not permission to be shallow; push the task as far as safely and honestly possible inside the current ticket. Depending on the task, this may include:

- editing code
- reading files
- researching
- running tests
- generating artifacts
- verifying output
- integrating results from tools or subagents

If you discover during execution that the whole problem cannot be completed in this attempt, do not silently reclassify the ticket or start splitting the current problem. Continue as far as safely possible, preserve useful progress, and record the actual partial or failed result.

If you discover a concrete subprogram that must run before the current ticket can return a useful result, spawn a child problem instead of pretending the ticket is complete. Runtime spawn is different from split and follow-up:

- `split` is plan-time decomposition before execution.
- `spawn` is run-time subprogram creation from the executing ticket.
- `follow-up` is check-time repair after verification fails.

Spawn only when the child is specific and blocking. The spawned problem must be small enough to solve recursively and must have concrete success criteria.

Be honest about what was and was not verified. Do not compress uncertainty into a cheerful summary; visible gaps are useful because `check-success` can turn them into follow-up work.

## Spawned Child Body

When spawning, write each spawned child as Markdown:

```md
# Spawned problem title

## Problem

Describe the blocking subprogram needed by the current ticket.

## Success Criteria

-
```

The Root Agent records it with:

```bash
ledger.py set-status problem P000 doing
ledger.py set-status ticket T000 executing
ledger.py create-problem --parent P000 --from-ticket T000 --mode spawn --from-file path/to/spawned-subproblem.md
```

After spawning, stop this action and run `ledger.py next`. Do not also record the parent result in the same action.

## Result Body

Write a result body as Markdown:

```md
# Result title

## Summary

## Done

-

## Verification

-

## Known Gaps

-

## Artifacts

-
```

`Known Gaps` may be `None` only when that is actually true. Partial completion, failed attempts, blockers, and unresolved work must be recorded as known gaps or artifacts.

Recording a partial or failed result is valid. The ticket can be done even when the original problem is not solved; `check-success` will create follow-up work if needed.

## Output

Return:

- result body file path, or spawned child problem body file paths
- important commands run and outcomes
- changed files or artifacts, if any
- known gaps

The Root Agent records it with:

```bash
ledger.py set-status problem P000 doing
ledger.py result --ticket T000 --from-file path/to/result.md
```

Then the Root Agent runs `ledger.py next`.
