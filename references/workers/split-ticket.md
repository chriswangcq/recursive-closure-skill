# Worker Next Action: split-ticket

## Mission

Split the shown ticket into plan-time child problems derived from the ticket's proposed solution.

Do not solve the child problems in this step. Do not record the parent result or check the parent.

## Work

Create child problem bodies that are small enough to solve recursively.

Each split child must have:

- a clear problem
- concrete success criteria
- a reason it belongs under the current split ticket

Avoid vague buckets like "misc cleanup" or "finish remaining work". If the work is not clear enough to check, refine the child problem.

## Child Problem Body

Each child problem body must use:

```md
# Problem title

## Problem

## Success Criteria

-
```

## Output

Return the child problem body file paths and a short split rationale.

The Root Agent records each child with:

```bash
ledger.py set-status ticket T000 splitting
ledger.py create-problem --parent P000 --from-ticket T000 --mode split --from-file path/to/subproblem.md
```

Then the Root Agent runs `ledger.py next`.
