# Worker Next Action: record-result

## Mission

Record the current ticket's result only.

Do not judge whether the problem is solved. Do not create follow-ups. Do not run `check_success`.

## Work

Turn existing execution, split-child summary, partial attempt, failed attempt, blocker evidence, or observed work into a durable result body.

For split tickets, the result should summarize closed split child problem results. For one_go tickets that spawned runtime child problems, the result should incorporate the closed spawned child results. If any child problem created from the current ticket is still open, report that the parent result is not ready.

## Result Body

Write:

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

Known gaps are allowed. Recording a result marks the ticket done; problem-level `check_success` decides whether those gaps require follow-up work.

Do not withhold a result just because the attempt did not solve the problem. A failed or partial attempt with evidence is still a useful result.

## Output

Return:

- result body file path
- cited child results or evidence
- known gaps

The Root Agent records it with:

```bash
ledger.py set-status problem P000 doing
ledger.py result --ticket T000 --from-file path/to/result.md
```

Then the Root Agent runs `ledger.py next`.
