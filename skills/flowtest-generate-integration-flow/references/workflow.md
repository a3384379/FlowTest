# Workflow contract

Use this reference whenever the skill is invoked. The output of one stage is the input identity for the next stage; never reconstruct IDs or revisions from memory.

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
| Propose | `propose_flow_draft`, `inspect_flow_proposal` | Review-only proposal in the existing Visual Review flow |
| Preview, optional | `inspect_flow_proposal`, then `preview_flow_proposal` | Current accepted and unapplied proposal, explicit test-environment approval, bounded execution, cleanup evidence |

## Evidence routing

- Code MCP: request only pinned symbol, route, DTO, validation, and call-relationship facts. Convert the result to the Java or generic external Evidence schema before ingest.
- Database MCP: request only schema, relationship, constraint, index, enum summary, and redacted aggregate profile facts. Never request row data or write SQL.
- No external MCP: ask the user for an exported, redacted, bounded artifact and ingest it through the same typed contract.
- Conflict: retain both evidence references and stop. Do not select the more convenient claim.

## Revision and approval rules

- Pass the exact current Context revision returned by the previous operation.
- If FlowTest reports a stale revision, re-read the Context and show the change; do not overwrite it.
- Proposal creation is not Review, Apply, Publish, or Preview approval.
- Visual Review and Apply remain user actions in FlowTest. End the normal workflow after opening or linking to Visual Review.
- Preview is a separate optional branch. Immediately before requesting approval or executing it, call `inspect_flow_proposal` again and require the proposal and item to be accepted, current, and unapplied (`applied=false`). Stop when review is incomplete, the proposal is stale, or it was already applied. Only then require the `mcp:preview:execute` scope, a fresh one-time approval bound to the service account and proposal, and a target explicitly classified as test.

## Failure reporting

Return the failed stage, FlowTest error code and trace ID, relevant safe object IDs, and the missing evidence or user action. Do not include request bodies, response bodies, tokens, Secret values, cookies, connection strings, or raw external MCP output.
