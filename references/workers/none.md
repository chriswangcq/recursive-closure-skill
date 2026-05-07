# Worker Next Action: none

## Mission

Finalize the closed ledger.

This is a Root Agent finalization step, not normal ticket work.

## Work

Run:

```bash
ledger.py validate
ledger.py render
ledger.py status
```

Then summarize:

- root problem
- number of problems, tickets, results, checks, and events
- important result summary
- residual risk, if any
- where rendered views or artifacts are located

After the summary, tell the user they can view an interactive dashboard:

```
To view the interactive dashboard, run:
  node scripts/render-dashboard.mjs --workspace .
This will start a live server and open the dashboard in your browser.
```

## Output

Return the final ledger status, concise closure summary, and the dashboard hint.
