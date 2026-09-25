# Native control-block proposals

Use this path only when the user asks to add an inline control block to an existing workflow. Read the exact current `draft_revision` and main edge ID from `flowtest.inspect_flow`. Confirm the capability and configuration schema through `flowtest.discover_control_capabilities`. The target edge must be unconditional and have no field mappings; the server rejects unsafe splits. Use fresh stable IDs for the control node, every region, and every child node. Keep a control body small and serial unless the requested semantics require parallel work.

`flowtest.propose_control_block` takes one `request` with `project_id`, `workflow_id`, and an `edit`. The `edit` includes `expected_revision`, `edge_id`, `node`, `regions`, and, when upgrading a legacy draft to schema 4.0, `request_budget`. Try/Finally additionally needs a cleanup budget if the draft has none. The server validates the complete resulting definition using the same publishability rules as the Workflow API. It creates a pending ChangeSet; it does not modify the draft, publish, or run it. Use a new idempotency key for each distinct proposal.

This bounded example expresses **Repeat 3 → wait 1 second**. Replace every placeholder ID with a real current project/workflow ID or a fresh unique node/region ID. Select the real edge ID returned by `inspect_flow`.

```json
{
  "project_id": "<project UUID>",
  "workflow_id": "<workflow UUID>",
  "edit": {
    "expected_revision": 7,
    "edge_id": "<existing safe main edge ID>",
    "request_budget": 20,
    "node": {
      "id": "control-repeat-<unique ID>",
      "type": "capability",
      "name": "重复检查三次",
      "position": { "x": 300, "y": 120 },
      "capability_id": "flow.control.repeat",
      "capability_version": "1.0.0",
      "configuration": {
        "count": 3,
        "body": { "kind": "inline", "region_id": "region-repeat-<unique ID>" }
      },
      "bindings": []
    },
    "regions": [{
      "id": "region-repeat-<unique ID>",
      "owner_node_id": "control-repeat-<unique ID>",
      "role": "body",
      "nodes": [{
        "id": "wait-<unique ID>",
        "type": "delay",
        "name": "等待一秒",
        "position": { "x": 0, "y": 0 },
        "config": { "seconds": 1 }
      }],
      "edges": [],
      "entry_node_id": "wait-<unique ID>",
      "exit_node_ids": ["wait-<unique ID>"]
    }]
  }
}
```

For a data-driven ForEach, use the actual bounded collection and pinned body assets. Set `policy.concurrency` to 1 by default, and declare `max_iterations`, `timeout_seconds`, and `on_error`. For an IF/Switch, use stable branch IDs and explicit default behavior. Do not invent a zero-second wait or duplicate flat steps to stand in for an unknown business body. Do not turn on parallelism merely to demonstrate the feature.

The returned `review_url` opens the existing human MCP ChangeSet review page. Report it with the proposal ID and base revision. The caller must not invoke its accept/reject/approve actions. A human may review and accept the change; a stale draft revision rejects acceptance without partial edits. Native control-block proposals are not FlowSpec proposals and cannot use `inspect_flow_proposal` or `preview_flow_proposal`.
