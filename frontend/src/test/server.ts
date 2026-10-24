import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'

import { project } from './fixtures'

export const server = setupServer(
  http.get('/api/v1/organizations', () => HttpResponse.json([])),
  http.get('/api/v1/v3/features', () =>
    HttpResponse.json({
      capability_sdk: true,
      plugin_registry: true,
      runner_fabric: true,
      multi_protocol: true,
      event_protocols: true,
      performance_lab: true,
      environment_lab: true,
      contract_hub: true,
      impact_engine: true,
      quality_intelligence: true,
      integration_flow: true,
      pact_broker: true,
    }),
  ),
  http.get('/api/v1/projects/:projectId/permissions', () =>
    HttpResponse.json({
      effective_role: 'owner',
      capabilities: ['read', 'edit', 'execute'],
      matrix: { owner: [], editor: [], viewer: [] },
    }),
  ),
  http.get('/api/v1/projects/:projectId', ({ params }) => {
    if (params.projectId === project.id) return HttpResponse.json(project)
    return HttpResponse.json(
      { error: { code: 'PROJECT_NOT_FOUND', message: '项目不存在', trace_id: 'test-trace' } },
      { status: 404 },
    )
  }),
  http.get('/api/v1/projects/:projectId/redaction-policy', ({ params }) => {
    if (params.projectId === project.id) {
      return HttpResponse.json({ mode: 'off', source: 'installation', policy_version: 1 })
    }
    return HttpResponse.json(
      { error: { code: 'PROJECT_NOT_FOUND', message: '项目不存在', trace_id: 'test-trace' } },
      { status: 404 },
    )
  }),
)
