import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import { apiDefinition, environment, executionDetail, project } from '../../test/fixtures'
import { server } from '../../test/server'
import {
  createApi,
  createEnvironment,
  createProject,
  executeApi,
  listApis,
  listEnvironments,
  listExecutions,
  listProjects,
} from './api-service'

describe('API console service', () => {
  it('maps project and environment resources', async () => {
    server.use(
      http.get('/api/v1/projects', () =>
        HttpResponse.json({ items: [project], total: 1, page: 1, page_size: 100 }),
      ),
      http.post('/api/v1/projects', () => HttpResponse.json(project, { status: 201 })),
      http.get(`/api/v1/projects/${project.id}/environments`, () =>
        HttpResponse.json([environment]),
      ),
      http.post(`/api/v1/projects/${project.id}/environments`, () =>
        HttpResponse.json(environment, { status: 201 }),
      ),
    )

    expect((await listProjects()).items).toEqual([project])
    expect(await createProject({ name: project.name, description: '' })).toEqual(project)
    expect(await listEnvironments(project.id)).toEqual([environment])
    expect(
      await createEnvironment(project.id, {
        name: environment.name,
        base_url: environment.base_url,
        variables: {},
        headers: {},
      }),
    ).toEqual(environment)
  })

  it('maps API definitions, execution, and history', async () => {
    server.use(
      http.get(`/api/v1/projects/${project.id}/apis`, () =>
        HttpResponse.json({ items: [apiDefinition], total: 1, page: 1, page_size: 100 }),
      ),
      http.post(`/api/v1/projects/${project.id}/apis`, async ({ request }) => {
        const payload = (await request.json()) as { request: { body_kind: string } }
        expect(payload.request.body_kind).toBe('json')
        return HttpResponse.json({ definition: apiDefinition }, { status: 201 })
      }),
      http.post(`/api/v1/projects/${project.id}/apis/${apiDefinition.id}/execute`, () =>
        HttpResponse.json(executionDetail),
      ),
      http.get(`/api/v1/projects/${project.id}/executions`, () =>
        HttpResponse.json({
          items: [executionDetail.execution],
          total: 1,
          page: 1,
          page_size: 20,
        }),
      ),
    )

    expect((await listApis(project.id)).items).toEqual([apiDefinition])
    expect(
      await createApi(project.id, {
        name: apiDefinition.name,
        description: '',
        method: 'POST',
        path: '/orders',
        body: { amount: 99 },
      }),
    ).toEqual(apiDefinition)
    expect(await executeApi(project.id, apiDefinition.id, environment.id, 200)).toEqual(
      executionDetail,
    )
    expect((await listExecutions(project.id)).items).toEqual([executionDetail.execution])
  })
})
