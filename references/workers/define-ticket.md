# Worker Next Action: define-ticket

## Mission

Repair or complete an existing ticket definition so it can be classified.

This state should be rare. Tickets created through `create-ticket --from-file` should normally already be fully defined.

Do not create another ticket for the same problem. Do not classify, execute, split, record a result, or check success in this step.

## Work

Inspect the existing ticket and identify why it is not classifiable.

The ticket must have enough content to support:

Required for classification (CLI-enforced):

- problem definition
- proposed solution
- acceptance criteria
- verification plan

Recommended (not required for the `created → defined` transition):

- risks
- assumptions

If the CLI-created ticket is incomplete or the state is inconsistent, report the inconsistency to the Root Agent instead of inventing a second ticket.

## Output

Return one of:

- a corrected ticket body path if a normal repair path exists
- a concise blocker report if the ticket cannot be repaired through the current public CLI

The Root Agent should run `ledger.py validate` and then `ledger.py next`.
