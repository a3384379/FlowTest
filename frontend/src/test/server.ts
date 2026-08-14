import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'

import { project } from './fixtures'

export const server = setupServer(
  http.get('/api/v1/projects/:projectId', ({ params }) => {
    if (params.projectId === project.id) return HttpResponse.json(project)
    return HttpResponse.json(
      { error: { code: 'PROJECT_NOT_FOUND', message: '项目不存在', trace_id: 'test-trace' } },
      { status: 404 },
    )
  }),
)
