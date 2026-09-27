import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import {
  apiDefinition,
  environment,
  project,
  workflow,
  workflowExecutionDetail,
  workflowRunningExecution,
  workflowVersion,
} from '../../test/fixtures'
import { server } from '../../test/server'
import {
  createWorkflow,
  debugWorkflow,
  diffWorkflowVersions,
  executeWorkflow,
  getWorkflowExecution,
  linearWorkflow,
  listApis,
  listEnvironments,
  listProjects,
  listWorkflowExecutions,
  listWorkflows,
  publishWorkflow,
  replayWorkflowNode,
  updateWorkflowDraft,
} from './workflow-service'

describe('workflow service', () => {
  it('pins a read-only API and its equality assertion for the parallel template', async () => {
    server.use(
      http.get(`/api/v1/projects/${project.id}/apis/${apiDefinition.id}`, () =>
        HttpResponse.json({ definition: apiDefinition, version: { version: 3, method: 'GET' } }),
      ),
      http.post(`/api/v1/projects/${project.id}/workflows`, async ({ request }) => {
        const payload = (await request.json()) as { definition: ReturnType<typeof linearWorkflow> }
        const owner = payload.definition.nodes.find(
          (node) => node.capability_id === 'flow.control.parallel',
        )!
        expect(
          payload.definition.nodes.find((node) => node.type === 'assert')?.config,
        ).toMatchObject({
          source_node_id: owner.id,
          expected_source_node_id: owner.id,
        })
        expect(
          payload.definition.regions?.every((region) => region.nodes[0].config.api_version === 3),
        ).toBe(true)
        return HttpResponse.json(workflow, { status: 201 })
      }),
    )
    await expect(
      createWorkflow(project.id, {
        name: '并行一致性',
        description: '',
        apiId: apiDefinition.id,
        template: 'parallel_compare',
      }),
    ).resolves.toEqual(workflow)
  })

  it('rejects a write API before creating a parallel comparison draft', async () => {
    let created = false
    server.use(
      http.get(`/api/v1/projects/${project.id}/apis/${apiDefinition.id}`, () =>
        HttpResponse.json({ definition: apiDefinition, version: { version: 1, method: 'POST' } }),
      ),
      http.post(`/api/v1/projects/${project.id}/workflows`, () => {
        created = true
        return HttpResponse.json(workflow, { status: 201 })
      }),
    )
    await expect(
      createWorkflow(project.id, {
        name: '并行一致性',
        description: '',
        apiId: apiDefinition.id,
        template: 'parallel_compare',
      }),
    ).rejects.toThrow('并行一致性模板只能使用只读 GET 接口')
    expect(created).toBe(false)
  })

  it('pins separate POST submit and GET poll APIs before creating a polling draft', async () => {
    const submitId = '00000000-0000-4000-8000-000000000031'
    server.use(
      http.get(`/api/v1/projects/${project.id}/apis/${submitId}`, () =>
        HttpResponse.json({
          definition: { ...apiDefinition, id: submitId },
          version: { version: 2, method: 'POST' },
        }),
      ),
      http.get(`/api/v1/projects/${project.id}/apis/${apiDefinition.id}`, () =>
        HttpResponse.json({ definition: apiDefinition, version: { version: 1, method: 'GET' } }),
      ),
      http.post(`/api/v1/projects/${project.id}/workflows`, async ({ request }) => {
        const payload = (await request.json()) as { definition: ReturnType<typeof linearWorkflow> }
        expect(payload.definition.nodes.map((node) => node.id)).toEqual([
          'start',
          'submit',
          'api',
          'end',
        ])
        expect(payload.definition.nodes[1].config.api_version).toBe(2)
        expect(payload.definition.nodes[2].config.api_version).toBe(1)
        expect(payload.definition.edges[1].mappings[0].source.path).toBe('body.taskId')
        return HttpResponse.json(workflow, { status: 201 })
      }),
    )
    await expect(
      createWorkflow(project.id, {
        name: '异步任务',
        description: '',
        apiId: apiDefinition.id,
        submitApiId: submitId,
        template: 'async_poll',
      }),
    ).resolves.toEqual(workflow)
  })

  it('rejects a write API as the polling target before creating a draft', async () => {
    const submitId = '00000000-0000-4000-8000-000000000031'
    let created = false
    server.use(
      http.get(`/api/v1/projects/${project.id}/apis/${submitId}`, () =>
        HttpResponse.json({ definition: apiDefinition, version: { version: 2, method: 'POST' } }),
      ),
      http.get(`/api/v1/projects/${project.id}/apis/${apiDefinition.id}`, () =>
        HttpResponse.json({ definition: apiDefinition, version: { version: 1, method: 'POST' } }),
      ),
      http.post(`/api/v1/projects/${project.id}/workflows`, () => {
        created = true
        return HttpResponse.json(workflow, { status: 201 })
      }),
    )
    await expect(
      createWorkflow(project.id, {
        name: '异步任务',
        description: '',
        apiId: apiDefinition.id,
        submitApiId: submitId,
        template: 'async_poll',
      }),
    ).rejects.toThrow('状态轮询接口必须使用只读 GET 方法')
    expect(created).toBe(false)
  })

  it('maps workflow drafts, versions, and executions', async () => {
    server.use(
      http.get('/api/v1/projects', () =>
        HttpResponse.json({ items: [project], total: 1, page: 1, page_size: 100 }),
      ),
      http.get(`/api/v1/projects/${project.id}/environments`, () =>
        HttpResponse.json([environment]),
      ),
      http.get(`/api/v1/projects/${project.id}/apis`, () =>
        HttpResponse.json({ items: [apiDefinition], total: 1, page: 1, page_size: 100 }),
      ),
      http.get(`/api/v1/projects/${project.id}/workflows`, () =>
        HttpResponse.json({ items: [workflow], total: 1, page: 1, page_size: 100 }),
      ),
      http.post(`/api/v1/projects/${project.id}/workflows`, async ({ request }) => {
        const payload = (await request.json()) as { definition: { nodes: unknown[] } }
        expect(payload.definition.nodes).toHaveLength(3)
        return HttpResponse.json(workflow, { status: 201 })
      }),
      http.patch(`/api/v1/projects/${project.id}/workflows/${workflow.id}`, async ({ request }) => {
        const payload = (await request.json()) as { expected_revision: number }
        expect(payload.expected_revision).toBe(1)
        return HttpResponse.json({ ...workflow, draft_revision: 2 })
      }),
      http.post(`/api/v1/projects/${project.id}/workflows/${workflow.id}/versions`, () =>
        HttpResponse.json(workflowVersion),
      ),
      http.get(`/api/v1/projects/${project.id}/workflows/${workflow.id}/versions/1/diff/2`, () =>
        HttpResponse.json(versionDiff),
      ),
      http.post(
        `/api/v1/projects/${project.id}/workflows/${workflow.id}/debug`,
        async ({ request }) => {
          expect(await request.json()).toEqual({
            environment_id: environment.id,
            version: 1,
            breakpoint_node_id: 'api',
          })
          return HttpResponse.json(debugResult)
        },
      ),
      http.post(
        `/api/v1/projects/${project.id}/workflow-executions/${workflowRunningExecution.id}/nodes/api/replay`,
        () => HttpResponse.json({ ...debugResult, mode: 'replay' }),
      ),
      http.post(`/api/v1/projects/${project.id}/workflows/${workflow.id}/executions`, () =>
        HttpResponse.json(workflowRunningExecution, { status: 202 }),
      ),
      http.get(
        `/api/v1/projects/${project.id}/workflow-executions/${workflowRunningExecution.id}`,
        () => HttpResponse.json(workflowExecutionDetail),
      ),
      http.get(`/api/v1/projects/${project.id}/workflow-executions`, ({ request }) => {
        expect(new URL(request.url).searchParams.get('workflow_id')).toBe(workflow.id)
        return HttpResponse.json({
          items: [workflowExecutionDetail.execution],
          total: 1,
          page: 1,
          page_size: 20,
        })
      }),
    )

    expect((await listProjects()).items).toEqual([project])
    expect(await listEnvironments(project.id)).toEqual([environment])
    expect((await listApis(project.id)).items).toEqual([apiDefinition])
    expect((await listWorkflows(project.id)).items).toEqual([workflow])
    expect(
      await createWorkflow(project.id, {
        name: workflow.name,
        description: workflow.description,
        apiId: apiDefinition.id,
      }),
    ).toEqual(workflow)
    expect(
      await updateWorkflowDraft(project.id, workflow, workflow.draft_definition),
    ).toMatchObject({ draft_revision: 2 })
    expect(await publishWorkflow(project.id, workflow.id)).toEqual(workflowVersion)
    expect(await diffWorkflowVersions(project.id, workflow.id, 1, 2)).toEqual(versionDiff)
    expect(await debugWorkflow(project.id, workflow.id, environment.id, 1, 'api')).toEqual(
      debugResult,
    )
    expect(await replayWorkflowNode(project.id, workflowRunningExecution.id, 'api')).toMatchObject({
      mode: 'replay',
    })
    expect(await executeWorkflow(project.id, workflow.id, environment.id)).toEqual(
      workflowRunningExecution,
    )
    expect(await getWorkflowExecution(project.id, workflowRunningExecution.id)).toEqual(
      workflowExecutionDetail,
    )
    expect((await listWorkflowExecutions(project.id, workflow.id)).items).toEqual([
      workflowExecutionDetail.execution,
    ])
  })

  it('creates a stable Start to API to End definition', () => {
    const definition = linearWorkflow(apiDefinition.id, apiDefinition.current_version)

    expect(definition.nodes.map((node) => node.type)).toEqual(['start', 'api', 'end'])
    expect(definition.edges).toHaveLength(2)
    expect(definition.nodes[1].config.api_definition_id).toBe(apiDefinition.id)
    expect(definition.nodes[1].config.api_version).toBe(apiDefinition.current_version)
    expect(definition.nodes[1].config.request_overrides).toEqual({})
    expect(definition.nodes.map((node) => node.position.x)).toEqual([0, 320, 640])
  })
})

const versionDiff = {
  from_version: 1,
  to_version: 2,
  changes: [{ path: '$.nodes', before: [], after: [] }],
}

const debugResult = {
  status: 'passed',
  mode: 'breakpoint',
  target_node_id: 'api',
  context: {},
  nodes: [],
}
