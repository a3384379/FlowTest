import { http, HttpResponse } from 'msw'
import { describe, expect, it, vi } from 'vitest'

import { apiDefinition, environment, executionDetail, project } from '../../test/fixtures'
import { server } from '../../test/server'
import { apiClient } from '../../lib/api'
import {
  createApi,
  createEnvironment,
  createProject,
  downloadArtifact,
  executeApi,
  importApiDocument,
  listApis,
  listArtifacts,
  listEnvironments,
  listExecutions,
  listProjects,
  uploadArtifact,
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

  it('uploads import documents and project artifacts', async () => {
    const artifact = {
      id: 'artifact-1',
      project_id: project.id,
      filename: 'payload.txt',
      content_type: 'text/plain',
      size_bytes: 7,
      sha256: 'digest',
      purpose: 'upload' as const,
      created_at: '2026-08-09T00:00:00Z',
    }
    const importRun = {
      id: 'import-1',
      project_id: project.id,
      source_type: 'openapi3' as const,
      source_name: 'openapi.json',
      source_sha256: 'source-digest',
      added: 1,
      changed: 0,
      deleted: 0,
      unchanged: 0,
      results: [],
      created_at: '2026-08-09T00:00:00Z',
    }
    server.use(
      http.post(`/api/v1/projects/${project.id}/imports`, async ({ request }) => {
        const form = await request.formData()
        expect((form.get('document') as Blob).size).toBeGreaterThan(0)
        expect(form.get('source_type')).toBe('auto')
        return HttpResponse.json(importRun, { status: 201 })
      }),
      http.get(`/api/v1/projects/${project.id}/files`, () =>
        HttpResponse.json({ items: [artifact], total: 1, page: 1, page_size: 100 }),
      ),
      http.post(`/api/v1/projects/${project.id}/files`, async ({ request }) => {
        const form = await request.formData()
        expect((form.get('file') as Blob).size).toBeGreaterThan(0)
        return HttpResponse.json(artifact, { status: 201 })
      }),
    )

    expect(
      await importApiDocument(
        project.id,
        new File(['{}'], 'openapi.json', { type: 'application/json' }),
      ),
    ).toEqual(importRun)
    expect((await listArtifacts(project.id)).items).toEqual([artifact])
    expect(
      await uploadArtifact(
        project.id,
        new File(['payload'], 'payload.txt', { type: 'text/plain' }),
      ),
    ).toEqual(artifact)

    const createObjectUrl = vi.fn(() => 'blob:artifact')
    const revokeObjectUrl = vi.fn()
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createObjectUrl })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: revokeObjectUrl })
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
    const get = vi
      .spyOn(apiClient, 'get')
      .mockResolvedValueOnce({ data: new Blob(['payload']) } as never)
    await downloadArtifact(project.id, artifact)
    expect(createObjectUrl).toHaveBeenCalled()
    expect(click).toHaveBeenCalled()
    expect(revokeObjectUrl).toHaveBeenCalledWith('blob:artifact')
    get.mockRestore()
  })
})
