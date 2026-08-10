import { HttpResponse, http } from 'msw'
import { describe, expect, it } from 'vitest'

import type { Credential, MockRequestLog, MockRoute, MockService } from '../../lib/api'
import { project, user } from '../../test/fixtures'
import { server } from '../../test/server'
import {
  createCredential,
  createMockRoute,
  createMockService,
  deleteCredential,
  deleteMockRoute,
  listCredentials,
  listMockLogs,
  listMockRoutes,
  listMockServices,
  updateMockService,
} from './data-source-service'

describe('data source service', () => {
  it('maps write-only credential resources', async () => {
    let removedId = ''
    server.use(
      http.get('/api/v1/credentials', ({ request }) => {
        expect(new URL(request.url).searchParams.get('project_id')).toBe(project.id)
        return HttpResponse.json([credential])
      }),
      http.post('/api/v1/credentials', async ({ request }) => {
        expect(await request.json()).toMatchObject({
          project_id: project.id,
          name: '只读库',
          secret: 'write-only',
        })
        return HttpResponse.json(credential, { status: 201 })
      }),
      http.delete('/api/v1/credentials/:credentialId', ({ params }) => {
        removedId = String(params.credentialId)
        return new HttpResponse(null, { status: 204 })
      }),
    )

    expect(await listCredentials(project.id)).toEqual([credential])
    expect(
      await createCredential(project.id, {
        name: '只读库',
        kind: 'postgresql',
        host: 'db.internal',
        port: 5432,
        database_name: 'flowtest',
        username: 'reader',
        secret: 'write-only',
        tls_enabled: true,
      }),
    ).toEqual(credential)
    await deleteCredential(credential.id)
    expect(removedId).toBe(credential.id)
  })

  it('maps mock configuration and redacted logs', async () => {
    const removedRoutes: string[] = []
    server.use(
      http.get(`/api/v1/projects/${project.id}/mock-services`, () =>
        HttpResponse.json([mockService]),
      ),
      http.post(`/api/v1/projects/${project.id}/mock-services`, async ({ request }) => {
        expect(await request.json()).toEqual({
          name: mockService.name,
          slug: mockService.slug,
          description: mockService.description,
        })
        return HttpResponse.json(mockService, { status: 201 })
      }),
      http.patch(
        `/api/v1/projects/${project.id}/mock-services/${mockService.id}`,
        async ({ request }) => {
          expect(await request.json()).toEqual({ is_enabled: false })
          return HttpResponse.json({ ...mockService, is_enabled: false })
        },
      ),
      http.get(`/api/v1/projects/${project.id}/mock-services/${mockService.id}/routes`, () =>
        HttpResponse.json([mockRoute]),
      ),
      http.post(
        `/api/v1/projects/${project.id}/mock-services/${mockService.id}/routes`,
        async ({ request }) => {
          expect(await request.json()).toMatchObject({ path_pattern: '/users/{user_id}' })
          return HttpResponse.json(mockRoute, { status: 201 })
        },
      ),
      http.delete(
        `/api/v1/projects/${project.id}/mock-services/${mockService.id}/routes/:routeId`,
        ({ params }) => {
          removedRoutes.push(String(params.routeId))
          return new HttpResponse(null, { status: 204 })
        },
      ),
      http.get(
        `/api/v1/projects/${project.id}/mock-services/${mockService.id}/request-logs`,
        ({ request }) => {
          const query = new URL(request.url).searchParams
          expect(query.get('page')).toBe('1')
          expect(query.get('page_size')).toBe('50')
          return HttpResponse.json({ items: [mockLog], total: 1, page: 1, page_size: 50 })
        },
      ),
    )

    expect(await listMockServices(project.id)).toEqual([mockService])
    expect(
      await createMockService(project.id, {
        name: mockService.name,
        slug: mockService.slug,
        description: mockService.description,
      }),
    ).toEqual(mockService)
    expect(
      await updateMockService(project.id, mockService.id, { is_enabled: false }),
    ).toMatchObject({ is_enabled: false })
    expect(await listMockRoutes(project.id, mockService.id)).toEqual([mockRoute])
    expect(await createMockRoute(project.id, mockService.id, mockRouteInput)).toEqual(mockRoute)
    await deleteMockRoute(project.id, mockService.id, mockRoute.id)
    expect(removedRoutes).toEqual([mockRoute.id])
    expect((await listMockLogs(project.id, mockService.id)).items).toEqual([mockLog])
  })
})

const timestamp = '2026-08-10T00:00:00Z'
const credential: Credential = {
  id: 'credential-1',
  project_id: project.id,
  name: '只读库',
  kind: 'postgresql',
  host: 'db.internal',
  port: 5432,
  database_name: 'flowtest',
  username: 'reader',
  tls_enabled: true,
  created_by_id: user.id,
  created_at: timestamp,
  updated_at: timestamp,
}
const mockService: MockService = {
  id: 'mock-1',
  project_id: project.id,
  name: '用户 Mock',
  slug: 'user-mock',
  description: '用户契约',
  is_enabled: true,
  created_by_id: user.id,
  created_at: timestamp,
  updated_at: timestamp,
}
const mockRouteInput = {
  name: '查询用户',
  method: 'GET' as const,
  path_pattern: '/users/{user_id}',
  query_conditions: {},
  header_conditions: {},
  response_status: 200,
  response_headers: {},
  response_body: { id: '{{path.user_id}}' },
  delay_ms: 0,
  scenario: null,
  priority: 0,
  is_enabled: true,
}
const mockRoute: MockRoute = {
  id: 'route-1',
  mock_service_id: mockService.id,
  ...mockRouteInput,
  created_by_id: user.id,
  created_at: timestamp,
  updated_at: timestamp,
}
const mockLog: MockRequestLog = {
  id: 'log-1',
  mock_service_id: mockService.id,
  mock_route_id: mockRoute.id,
  method: 'GET',
  path: '/users/42',
  query_parameters: { token: '***' },
  headers: { authorization: '***' },
  body: null,
  matched: true,
  scenario: null,
  response_status: 200,
  duration_ms: 5,
  created_at: timestamp,
}
