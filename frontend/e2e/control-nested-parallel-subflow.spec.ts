import { expect, test } from '@playwright/test'

import type { ApiDetail, WorkflowDefinition, WorkflowNode, WorkflowRegion } from '../src/lib/api'
import { publishAndRun, seedEditor } from './support/workflow-editor'

test('子流程内并行分支在单叶子许可下完成且 Cookie 互不串扰', async ({ page }) => {
  const fixture = await seedEditor(page)
  async function createApi(name: string, path: string): Promise<ApiDetail> {
    const response = await page.request.post(`/api/v1${fixture.root}/apis`, {
      headers: fixture.headers,
      data: { name, service_id: fixture.serviceId, request: { method: 'GET', path } },
    })
    expect(response.ok(), await response.text()).toBeTruthy()
    return (await response.json()) as ApiDetail
  }
  const branchApis = await Promise.all(
    (['a', 'b'] as const).flatMap((branch) =>
      (['start', 'check'] as const).map(async (part) => ({
        branch,
        part,
        api: await createApi(`${branch} ${part}`, `/control/branches/${branch}/${part}`),
      })),
    ),
  )
  function apiNode(branch: 'a' | 'b', part: 'start' | 'check'): WorkflowNode {
    const detail = branchApis.find((item) => item.branch === branch && item.part === part)!.api
    return {
      id: `${branch}_${part}`,
      type: 'api',
      name: `${branch} ${part}`,
      position: { x: part === 'start' ? 0 : 250, y: 0 },
      config: { api_definition_id: detail.definition.id, api_version: detail.version.version },
    }
  }
  const branches = (['a', 'b'] as const).map((branch) => ({
    id: branch,
    label: branch,
    body: { kind: 'inline', region_id: `region_${branch}` },
  }))
  const regions: WorkflowRegion[] = (['a', 'b'] as const).map((branch) => ({
    id: `region_${branch}`,
    owner_node_id: 'parallel',
    role: `branch:${branch}`,
    nodes: [apiNode(branch, 'start'), apiNode(branch, 'check')],
    edges: [
      {
        id: `${branch}-start-check`,
        source: `${branch}_start`,
        target: `${branch}_check`,
        condition: null,
        mappings: [],
      },
    ],
    entry_node_id: `${branch}_start`,
    exit_node_ids: [`${branch}_check`],
    inputs: {},
    outputs: {},
  }))
  const childDefinition: WorkflowDefinition = {
    schema_version: '4.0',
    variables: {},
    nodes: [
      fixture.workflow.draft_definition.nodes[0],
      {
        id: 'parallel',
        type: 'capability',
        name: '并行核对',
        position: { x: 260, y: 80 },
        config: {},
        capability_id: 'flow.control.parallel',
        capability_version: '1.0.0',
        configuration: {
          branches,
          policy: { concurrency: 2, timeout_seconds: 30, on_error: 'collect_all' },
        },
        bindings: [],
      },
      fixture.workflow.draft_definition.nodes[2],
    ],
    edges: [
      { id: 'start-parallel', source: 'start', target: 'parallel', condition: null, mappings: [] },
      { id: 'parallel-end', source: 'parallel', target: 'end', condition: null, mappings: [] },
    ],
    regions,
    settings: { fail_fast: true, concurrency: 1, default_timeout_seconds: 30 },
    run_policy: {
      request_budget: 10,
      max_runtime_seconds: 60,
      cleanup_request_budget: null,
      force_cancel_skips_cleanup: true,
    },
  }
  const childResponse = await page.request.post(`/api/v1${fixture.root}/workflows`, {
    headers: fixture.headers,
    data: { name: '并行子流程验收', definition: childDefinition },
  })
  expect(childResponse.ok(), await childResponse.text()).toBeTruthy()
  const child = (await childResponse.json()) as { id: string }
  const publishedChild = await page.request.post(
    `/api/v1${fixture.root}/workflows/${child.id}/versions`,
    { headers: fixture.headers },
  )
  expect(publishedChild.ok(), await publishedChild.text()).toBeTruthy()
  const childVersion = (await publishedChild.json()) as { version: number }
  const parentDefinition: WorkflowDefinition = {
    ...childDefinition,
    nodes: [
      fixture.workflow.draft_definition.nodes[0],
      {
        id: 'nested',
        type: 'subflow',
        name: '执行并行子流程',
        position: { x: 260, y: 80 },
        config: { workflow_id: child.id, workflow_version: childVersion.version },
      },
      fixture.workflow.draft_definition.nodes[2],
    ],
    edges: [
      { id: 'start-nested', source: 'start', target: 'nested', condition: null, mappings: [] },
      { id: 'nested-end', source: 'nested', target: 'end', condition: null, mappings: [] },
    ],
    regions: [],
  }
  const updated = await page.request.patch(
    `/api/v1${fixture.root}/workflows/${fixture.workflow.id}`,
    {
      headers: fixture.headers,
      data: { expected_revision: fixture.workflow.draft_revision, definition: parentDefinition },
    },
  )
  expect(updated.ok(), await updated.text()).toBeTruthy()
  await page.reload()
  await publishAndRun(page)

  const executions = await page.request.get(
    `/api/v1${fixture.root}/workflow-executions?workflow_id=${fixture.workflow.id}`,
    { headers: fixture.headers },
  )
  expect(executions.ok()).toBeTruthy()
  const execution = ((await executions.json()) as { items: Array<{ id: string }> }).items[0]
  const detailResponse = await page.request.get(
    `/api/v1${fixture.root}/workflow-executions/${execution.id}`,
    { headers: fixture.headers },
  )
  expect(detailResponse.ok()).toBeTruthy()
  const detail = (await detailResponse.json()) as {
    nodes: Array<{
      node_id: string
      output: {
        nodes: Array<{
          node_id: string
          output: {
            branches: Array<{
              branch_id: string
              status: string
              nodes: Array<{ node_id: string; instance_id: string }>
            }>
          }
        }>
      }
    }>
  }
  const nested = detail.nodes.find((node) => node.node_id === 'nested')!
  const parallel = nested.output.nodes.find((node) => node.node_id === 'parallel')!
  expect(parallel.output.branches.map((branch) => [branch.branch_id, branch.status])).toEqual([
    ['a', 'passed'],
    ['b', 'passed'],
  ])
  for (const branch of parallel.output.branches) {
    const check = branch.nodes.find((node) => node.node_id === `${branch.branch_id}_check`)
    expect(check).toBeDefined()
    const checkpointResponse = await page.request.get(
      `/api/v1${fixture.root}/workflow-executions/${execution.id}/instances/${check!.instance_id}`,
      { headers: fixture.headers },
    )
    expect(checkpointResponse.ok(), await checkpointResponse.text()).toBeTruthy()
    const checkpoint = (await checkpointResponse.json()) as {
      output: { body: Record<string, unknown> }
    }
    expect(checkpoint.output.body).toMatchObject({
      branch: branch.branch_id,
      observedCookie: branch.branch_id,
    })
  }
})
