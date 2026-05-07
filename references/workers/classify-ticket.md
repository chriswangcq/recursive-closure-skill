# Worker Next Action: classify-ticket

## Mission

Classify the shown ticket as exactly one of:

- `one_go`
- `split`

Do not execute, split, record a result, or check success in this step.

## Classification Standard

Use `one_go` only when the ticket is genuinely suitable for one bounded execution attempt before problem-level checking.

`one_go` does not mean guaranteed one-shot success. It means the executor should try the proposed solution, advance as far as safely possible, record the actual result, and let `check-success` decide whether follow-up work is required. If the executor discovers a concrete blocking subprogram during execution, it may spawn a runtime child from the executing ticket instead of pretending the parent result is ready.

Do not choose `one_go` lightly. All of these should be true:

- the problem is narrow and concrete
- the solution path is already clear
- verification can be done immediately in the same attempt
- the risk is low or reversible
- there are no independent sub-outcomes that deserve their own criteria
- a failed attempt would still produce a clean, reviewable result

Use `split` when the ticket contains:

- multiple independent subproblems
- risky implementation slices
- uncertain research paths
- broad unknowns that need recursive closure
- work that would benefit from separate child success criteria

Prefer `split` when a one-pass attempt would produce vague results or hidden gaps. When uncertain, choose `split`; do not avoid extra tickets just because they feel tedious.

Do not choose `split` merely because success is uncertain. Choose `split` when the work itself needs child problem structure before a meaningful execution attempt can be made.

## Output

Return:

- classification: `one_go` or `split`
- short reason

The Root Agent records it with one of:

```bash
ledger.py classify-ticket T000 --classification one_go --reason "..."
ledger.py classify-ticket T000 --classification split --reason "..."
```

Then the Root Agent runs `ledger.py next`.
