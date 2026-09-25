# Workflow contract

Use this reference whenever the skill is invoked. The Quick FlowSpec path is the default; native control insertion and deep evidence stages are explicit branches. The output of one stage is the input identity for the next stage; never reconstruct IDs or revisions from memory.

## Quick path (default)

1. `list_projects`/`find_assets` → select one authorized project and one explicit non-production environment.
2. `propose_simple_flow` → submit existing API definition IDs and pinned versions, a bounded list of named steps, bindings, assertions, outputs, polling limits, and declared runtime inputs. The server resolves resources and creates a review-only FlowSpec draft without Context, Evidence, Integration Plan, database MCP, or execution.
3. Read `proposal_id`, `proposal_revision`, `static_validation`, `readiness`, `missing_inputs`, `diagnostics`, and `execution_status=not_run`. Use `inspect_flow_proposal` and stop at Visual Review.
4. To revise a Quick proposal, reuse its `proposal_id` with the exact current `proposal_revision` as `expected_revision`; the server updates that proposal in place and returns the next revision. A stale revision is rejected without replacing the newer draft.
5. For each explicitly requested flow, use a distinct idempotency key and share the caller's `task_ref` for correlated proposals. A failed proposal does not roll back or recreate successful proposals.

Use the deep path below only when the user explicitly asks for evidence, full coverage, source/database analysis, or an audit.

For ordinary generation, select at most three representative cases and keep the flow serial unless its real behavior requires another structure. Existing API IDs and pinned versions take priority over copied assets. FlowSpec has no lossless schema 4.0 region representation. When the user requests an inline ForEach, IF/Switch, condition loop, parallel branch, or Try/Finally in an existing workflow, use the native control-block proposal path below. Do not replace it with repeated flat nodes or an unrelated legacy node.

## Native control-block proposal (only when requested)

1. Use `inspect_flow` to read the target workflow ID, project ID, current `draft_revision`, main edge ID, schema version, and budget. Use `discover_control_capabilities` to confirm the requested kind and version are executable with inline regions.
2. Follow [control-blocks.md](control-blocks.md) to construct one control node and its regions. Supply the exact `expected_revision`, the chosen unmapped main edge ID, and an explicit main request budget when upgrading to schema 4.0. Use existing pinned API assets for body steps.
3. Call `propose_control_block` once with a distinct idempotency key. It validates the entire candidate but writes only a pending MCP ChangeSet. Preserve `proposal_id`, `item_id`, `base_revision`, and `review_url`; the target draft is unchanged.
4. Stop at the returned human MCP ChangeSet review page. The agent must never call the accept/reject route. A human acceptance rechecks the revision, atomically inserts the block into the draft, and still does not publish or execute it.

If there is no existing authorized workflow, no safe main edge, a stale revision, or a capability the runtime cannot execute, return the exact blocker. A new workflow can first be proposed through Quick FlowSpec and applied by a human; only then can a native control block be proposed against its current draft.

| Stage | FlowTest MCP operations | Required result |
| --- | --- | --- |
| Select project | `list_projects`, `inspect_project`, `discover_services`, `inspect_contract` | One authorized project, one explicit business-flow objective, one non-production target |
| Create Context | `begin_test_context` | Context ID and immutable current revision with pinned source references |
| Find gaps | `inspect_context_requirements`, `inspect_test_context` | Exact missing evidence, conflicts, redactions, and unresolved items |
| Collect evidence | External read-only Code/DB MCP, or bounded user artifact | Versioned typed observations; no raw repository, credentials, database rows, or executable content |
| Ingest evidence | `ingest_external_evidence`, `ingest_java_evidence`, `ingest_database_evidence` | New Context revision and evidence references owned by the same project |
| Plan | `plan_integration_test`, `validate_integration_plan` | Deterministic operations, bindings, data/oracles, cleanup, and validation diagnostics |
| Compile | `compile_integration_flowspec`, `explain_compiler_diagnostics`, `validate_flowspec` | Traceable FlowSpec and compilation fingerprint; zero static errors |
| Dry run | `propose_flow_draft` with dry-run enabled | Proposed change summary without persistent proposal side effects |
| Propose | `propose_flow_draft`, `inspect_flow_proposal` | One or more explicitly requested bounded review-only proposals, each independently recoverable in the existing Visual Review flow |
| Preview, optional | `inspect_flow_proposal`, then `preview_flow_proposal` | Current accepted and unapplied proposal, explicit test-environment approval, bounded execution, cleanup evidence |

## Evidence routing

- Code MCP: request only pinned symbol, route, DTO, validation, and call-relationship facts. Convert the result to the Java or generic external Evidence schema before ingest.
- Database MCP: request schema, relationship, constraint, index, enum summary, and aggregate profile facts. Use only a small necessary row sample when that capture is already authorized; follow the effective redaction policy and never issue write SQL.
- No external MCP: ask the user for an exported, redacted, bounded artifact and ingest it through the same typed contract.
- Conflict: retain both evidence references and stop. Do not select the more convenient claim.

## Revision and approval rules

- Pass the exact current Context revision returned by the previous operation.
- If FlowTest reports a stale revision, re-read the Context and show the change; do not overwrite it.
- Proposal creation is not Review, Apply, Publish, or Preview approval.
- When correlated proposals are explicitly requested, use separate idempotency keys and a
  shared task reference. Treat partial success as partial success; never imply an atomic batch.
  For the RuoYi announcement A/B scenario, A retains its created-data handoff and B must stop on
  missing, ambiguous, or unmatched ownership evidence. Do not use a global notice ID.
- Visual Review and Apply remain user actions in FlowTest. End the normal workflow after opening or linking to Visual Review.
- Preview is a separate optional branch. Immediately before requesting approval or executing it, call `inspect_flow_proposal` again and require the proposal and item to be accepted, current, and unapplied (`applied=false`). Stop when review is incomplete, the proposal is stale, or it was already applied. Only then require the `mcp:preview:execute` scope, a fresh one-time approval bound to the service account and proposal, and a target explicitly classified as test.

## Failure reporting

Return the failed stage, FlowTest error code and trace ID, relevant safe object IDs, and the missing evidence or user action. Do not include request bodies, response bodies, tokens, Secret values, cookies, connection strings, or raw external MCP output.
