# Worker Next Action: create-solution-ticket

## Mission

Create exactly one solution ticket for the shown problem.

Do not classify, execute, split, record a result, or check success in this step.

## Inputs

Use the current `next_instruction` to identify:

- problem ID
- problem title
- problem body and success criteria
- any context the Root Agent attaches

## Work

Write a ticket body as Markdown. The ticket must define a concrete solution path, not just restate the problem.

Required body shape:

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

## Output

Return the ticket body file path and a short summary of the proposed solution.

The Root Agent records it with:

```bash
ledger.py create-ticket --problem P000 --from-file path/to/ticket.md
```

Then the Root Agent runs `ledger.py next`.
