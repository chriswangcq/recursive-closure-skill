# Worker Next Action: unblock-or-report

## Mission

Handle a blocked problem.

Either report the blocker clearly, or confirm that the blocker is resolved so the Root Agent can move the problem back into the normal flow.

Do not invent ticket-level blocked states. Tickets do not use `blocked`.

## Work

Identify:

- what input, dependency, permission, artifact, decision, or environment issue is blocking progress
- who or what can resolve it
- whether enough information now exists to continue

If the blocker is resolved, say so and provide the evidence.

If the blocker remains, report it clearly and stop.

## Output

Return one of:

- blocker report with required next external input
- unblock confirmation with evidence

If unblocked, the Root Agent may run:

```bash
ledger.py set-status problem P000 doing
```

Then the Root Agent runs `ledger.py next`.
