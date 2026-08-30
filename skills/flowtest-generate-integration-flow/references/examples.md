# Examples

## Login → Create Order → Query Order

1. Select the authorized Orders project and a test environment.
2. Create a Context for the three-operation flow, pinning the API contract and repository revision.
3. Ingest typed Code MCP evidence for login token production and typed DB profile evidence for the order identifier relationship.
4. Stop if the two sources disagree about the identifier type or location.
5. Plan the login token header binding and the create-response ID to query-parameter binding.
6. Compile and validate the FlowSpec, dry-run the proposal, then create a review-only proposal.
7. Direct the user to Visual Review. Do not Apply or Publish.

## Missing database evidence

If the Context requires a relationship between `orders.id` and the query parameter but no authorized Database MCP is available, do not guess it. Ask for a redacted schema/profile export or remove that operation from the confirmed scope. Resume only by ingesting a typed, versioned Evidence envelope.

## Production preview request

If the selected target is production, its classification is unknown, or the approval is absent, expired, already consumed, or belongs to another service account, do not call the preview tool. Report that FlowTest production preview is a hard refusal and direct the user to select an approved test environment.

## Stale proposal

If proposal inspection shows that the Context, plan, compilation, or proposal revision changed after dry run, do not reuse the prior idempotency key to force a write. Re-read the current revision, explain the safe diff, and ask the user to confirm the revised scope.
