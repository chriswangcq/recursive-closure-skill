# Worker Next Action: check-success

## Mission

Judge whether the original problem is solved.

Act like a reviewer, not like the executor defending the work. Do not perform new implementation work in this step.

## Work

Inspect the problem, success criteria, cited result IDs, returned follow-up results, artifacts, and verification evidence.

A success check must be earned. If evidence is weak, incomplete, or not mapped to criteria, the check is `not_success`.

For a `one_go` result, be stricter than usual. The shortcut must prove itself after execution:

- every original criterion is mapped to evidence
- verification was actually run or the missing verification is treated as a gap
- the stress test covers a plausible failure mode
- residual risk is explicit and non-blocking
- no known gap is being waved away as "probably fine"

If a `one_go` result is partial, failed, blocked, lightly verified, or has unresolved known gaps, judge the original problem normally. When it is not solved, write `not_success` and create exactly one follow-up problem. That follow-up problem may later be classified as `split`.

Do not be afraid to create the follow-up. The closure system is designed to make extra work explicit instead of pretending the first attempt solved everything.

## Success Check Body

For success, write:

```md
# Check title

## Summary

## Evidence

-

## Criteria Map

-

## Execution Map

-

## Stress Test

-

## Residual Risk

-

## Result IDs

-
```

## Not Success Check Body

For not success, write:

```md
# Check title

## Summary

## Blocking Gaps

-

## Result IDs

-
```

Also write exactly one follow-up problem body:

```md
# Follow-up problem title

## Problem

## Success Criteria

-
```

The follow-up should be the smallest problem that closes the detected gap.

Do not create multiple follow-ups in parallel.

## Output

Return:

- decision: `success` or `not_success`
- check body file path
- cited result IDs
- follow-up problem body path if not successful

The Root Agent records one of:

```bash
ledger.py check --problem P000 --status success --result R000 --from-file path/to/check.md
ledger.py check --problem P000 --status not_success --result R000 --from-file path/to/check.md --followup-from-file path/to/followup.md
```

Then the Root Agent runs `ledger.py next`.
