import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import {
  apiDefinition,
  environment,
  project,
  workflow,
  workflowExecutionDetail,
  workflowVersion,
} from '../../test/fixtures'
import { server } from '../../test/server'
import {
  createWorkflow,
  executeWorkflow,
  linearWorkflow,
  listApis,
  listEnvironments,
  listProjects,
  listWorkflowExecutions,
  listWorkflows,
  publishWorkflow,
  updateWorkflowDraft,
} from './workflow-service'

describe('workflow service', () => {
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
      http.post(`/api/v1/projects/${project.id}/workflows/${workflow.id}/executions`, () =>
        HttpResponse.json(workflowExecutionDetail),
      ),
      http.get(`/api/v1/projects/${project.id}/workflow-executions`, () =>
        HttpResponse.json({
          items: [workflowExecutionDetail.execution],
          total: 1,
          page: 1,
          page_size: 20,
        }),
      ),
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
    expect(await executeWorkflow(project.id, workflow.id, environment.id)).toEqual(
      workflowExecutionDetail,
    )
    expect((await listWorkflowExecutions(project.id)).items).toEqual([
      workflowExecutionDetail.execution,
    ])
  })

  it('creates a stable Start to API to End definition', () => {
    const definition = linearWorkflow(apiDefinition.id)

    expect(definition.nodes.map((node) => node.type)).toEqual(['start', 'api', 'end'])
    expect(definition.edges).toHaveLength(2)
    expect(definition.nodes[1].config.api_definition_id).toBe(apiDefinition.id)
  })
})
