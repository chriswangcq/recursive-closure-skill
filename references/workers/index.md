# Worker Instruction Index

Worker Agent completes exactly one current `next_action`.

Worker Agent is not the global driver. The Root Agent owns `scripts/ledger.py next`, dispatches the current step, records outputs through the CLI, then asks `next` again.

Use the instruction file that matches the current `next_action` exactly:

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

Common rule for every worker:

- Do only the current action.
- Do not skip ahead.
- Do not rewrite `state.json` directly.
- Do not edit rendered `views/*.md` as state.
- For any body consumed by `--from-file` or `--followup-from-file`, write a complete Markdown file. Prefer `mktemp` plus `cat > "$tmp" <<'EOF' ... EOF` when the body is temporary ledger input; use a durable workspace path only when the body needs later human review.
- Return the smallest useful output the Root Agent needs to record or continue.
