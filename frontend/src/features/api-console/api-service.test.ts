import { http, HttpResponse } from 'msw'
import { describe, expect, it, vi } from 'vitest'

import { apiDefinition, environment, executionDetail, project } from '../../test/fixtures'
import { server } from '../../test/server'
import { apiClient } from '../../lib/api'
import {
  createApi,
  createApiVersion,
  createEnvironment,
  createProject,
  discoverApiDocumentUrl,
  downloadArtifact,
  executeApi,
  exportApis,
  getApiDetail,
  mergeApiImport,
  listApis,
  listArtifacts,
  listEnvironments,
  listExecutions,
  listProjects,
  previewApiDocument,
  previewApiDocumentUrl,
  previewApi,
  updateApiDefinition,
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
    const bodyKinds: string[] = []
    server.use(
      http.get(`/api/v1/projects/${project.id}/apis`, () =>
        HttpResponse.json({ items: [apiDefinition], total: 1, page: 1, page_size: 100 }),
      ),
      http.post(`/api/v1/projects/${project.id}/apis`, async ({ request }) => {
        const payload = (await request.json()) as { request: { body_kind: string } }
        bodyKinds.push(payload.request.body_kind)
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
    expect(
      await createApi(project.id, {
        name: '无 Body 请求',
        description: '',
        method: 'GET',
        path: '/health',
        body: null,
      }),
    ).toEqual(apiDefinition)
    expect(bodyKinds).toEqual(['json', 'none'])
    expect(await executeApi(project.id, apiDefinition.id, environment.id, 200)).toEqual(
      executionDetail,
    )
    expect(
      await executeApi(project.id, apiDefinition.id, environment.id, 201, [
        { kind: 'status_code', operator: 'equals', target: null, expected: 201 },
      ]),
    ).toEqual(executionDetail)
    expect((await listExecutions(project.id)).items).toEqual([executionDetail.execution])
  })

  it('loads, versions, previews, and exports an API workbench document', async () => {
    const previewPayloads: unknown[] = []
    const version = {
      id: 'version-1',
      api_definition_id: apiDefinition.id,
      version: 1,
      method: 'POST' as const,
      path: '/orders',
      query_parameters: [{ name: 'region', value: 'cn', enabled: true }],
      headers: { 'X-Trace': '{{trace_id}}' },
      body_kind: 'json' as const,
      body: { amount: 99 },
      auth_kind: 'bearer' as const,
      auth_config: { token: '{{secret.API_TOKEN}}' },
      extraction_rules: [{ name: 'order_id', kind: 'jsonpath' as const, expression: '$.id' }],
      assertions: [{ kind: 'status_code', operator: 'equals', target: null, expected: 201 }],
      created_at: '2026-08-09T00:00:00Z',
    }
    const detail = { definition: apiDefinition, version }
    const preview = {
      method: 'POST',
      url: 'http://mock-target:8080/orders?region=cn',
      headers: [{ name: 'Authorization', value: '***', source: 'api' }],
      body: { amount: 99 },
    }
    server.use(
      http.get(`/api/v1/projects/${project.id}/apis/${apiDefinition.id}`, () =>
        HttpResponse.json(detail),
      ),
      http.patch(`/api/v1/projects/${project.id}/apis/${apiDefinition.id}`, async ({ request }) => {
        expect(await request.json()).toEqual({ name: '查询订单详情' })
        return HttpResponse.json({ ...apiDefinition, name: '查询订单详情' })
      }),
      http.post(
        `/api/v1/projects/${project.id}/apis/${apiDefinition.id}/versions`,
        async ({ request }) => {
          expect(await request.json()).toMatchObject({ path: '/orders' })
          return HttpResponse.json({ ...version, version: 2 }, { status: 201 })
        },
      ),
      http.post(
        `/api/v1/projects/${project.id}/apis/${apiDefinition.id}/preview`,
        async ({ request }) => {
          previewPayloads.push(await request.json())
          return HttpResponse.json(preview)
        },
      ),
    )

    expect(await getApiDetail(project.id, apiDefinition.id)).toEqual(detail)
    expect(
      await updateApiDefinition(project.id, apiDefinition.id, { name: '查询订单详情' }),
    ).toMatchObject({ name: '查询订单详情' })
    expect(
      await createApiVersion(project.id, apiDefinition.id, {
        method: version.method,
        path: version.path,
        query_parameters: version.query_parameters,
        headers: version.headers,
        body_kind: version.body_kind,
        body: version.body,
        auth: { kind: version.auth_kind, values: version.auth_config },
        extraction_rules: version.extraction_rules,
        assertions: version.assertions,
      }),
    ).toMatchObject({ version: 2 })
    expect(await previewApi(project.id, apiDefinition.id, environment.id)).toEqual(preview)
    expect(
      await previewApi(project.id, apiDefinition.id, environment.id, {
        version: 1,
        queryParametersOverride: [],
        headersOverride: { 'X-Node': 'custom' },
        bodyOverride: { amount: 100 },
        useBodyOverride: true,
      }),
    ).toEqual(preview)
    expect(previewPayloads).toEqual([
      {
        environment_id: environment.id,
        runtime_variables: {},
        runtime_headers: {},
      },
      {
        environment_id: environment.id,
        runtime_variables: {},
        runtime_headers: {},
        version: 1,
        query_parameters_override: [],
        headers_override: { 'X-Node': 'custom' },
        body_override: { amount: 100 },
        use_body_override: true,
      },
    ])

    const createObjectUrl = vi.fn(() => 'blob:export')
    const revokeObjectUrl = vi.fn()
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createObjectUrl })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: revokeObjectUrl })
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
    const get = vi
      .spyOn(apiClient, 'get')
      .mockResolvedValueOnce({
        data: 'har-export',
        headers: { 'content-disposition': 'attachment; filename="apis.har"' },
      } as never)
      .mockResolvedValueOnce({ data: 'curl-export', headers: {} } as never)
    await exportApis(project.id, 'har')
    await exportApis(project.id, 'curl')
    expect(click).toHaveBeenCalledTimes(2)
    expect(createObjectUrl).toHaveBeenCalledTimes(2)
    expect(revokeObjectUrl).toHaveBeenCalledWith('blob:export')
    get.mockRestore()
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
      source_kind: 'file' as const,
      source_key: 'file:openapi.json',
      source_type: 'openapi3' as const,
      source_name: 'openapi.json',
      source_url: null,
      document_url: null,
      source_sha256: 'source-digest',
      added: 1,
      changed: 0,
      deleted: 0,
      unchanged: 0,
      results: [],
      status: 'preview' as const,
      applied_keys: [],
      applied_at: null,
      created_at: '2026-08-09T00:00:00Z',
    }
    server.use(
      http.post(`/api/v1/projects/${project.id}/imports/preview`, async ({ request }) => {
        const form = await request.formData()
        expect((form.get('document') as Blob).size).toBeGreaterThan(0)
        expect(form.get('source_type')).toBe('auto')
        return HttpResponse.json(importRun, { status: 201 })
      }),
      http.post(`/api/v1/projects/${project.id}/imports/url/discover`, async ({ request }) => {
        expect(await request.json()).toEqual({
          url: 'https://api.example.com/swagger-ui/index.html',
        })
        return HttpResponse.json({
          source_url: 'https://api.example.com/swagger-ui/index.html',
          source_kind: 'swagger_ui',
          documents: [
            {
              id: 'a'.repeat(64),
              name: '用户服务',
              url: 'https://api.example.com/v3/api-docs/users',
            },
          ],
        })
      }),
      http.post(`/api/v1/projects/${project.id}/imports/url/preview`, async ({ request }) => {
        expect(await request.json()).toEqual({
          url: 'https://api.example.com/openapi.json',
          source_type: 'openapi3',
          document_id: 'a'.repeat(64),
        })
        return HttpResponse.json(
          {
            ...importRun,
            source_kind: 'url',
            source_key: 'url:digest',
            source_url: 'https://api.example.com/openapi.json',
            document_url: 'https://api.example.com/openapi.json',
          },
          { status: 201 },
        )
      }),
      http.post(
        `/api/v1/projects/${project.id}/imports/${importRun.id}/merge`,
        async ({ request }) => {
          expect(await request.json()).toEqual({ selected_keys: ['api-key'] })
          return HttpResponse.json({
            ...importRun,
            status: 'applied',
            applied_keys: ['api-key'],
            applied_at: '2026-08-09T00:01:00Z',
          })
        },
      ),
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
      await previewApiDocument(
        project.id,
        new File(['{}'], 'openapi.json', { type: 'application/json' }),
      ),
    ).toEqual(importRun)
    expect(
      await discoverApiDocumentUrl(project.id, 'https://api.example.com/swagger-ui/index.html'),
    ).toMatchObject({ source_kind: 'swagger_ui', documents: [{ name: '用户服务' }] })
    expect(
      await previewApiDocumentUrl(
        project.id,
        'https://api.example.com/openapi.json',
        'openapi3',
        'a'.repeat(64),
      ),
    ).toMatchObject({ source_kind: 'url', source_key: 'url:digest' })
    expect((await mergeApiImport(project.id, importRun.id, ['api-key'])).status).toBe('applied')
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
