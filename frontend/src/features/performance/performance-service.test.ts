import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { server } from '../../test/server'
import {
  getPerformanceRun,
  getPerformanceScenario,
  runPerformanceScenario,
} from './performance-service'
describe('performance response identity', () => {
  it.each([
    { project_id: 'foreign', scenario_id: 'scene' },
    { project_id: 'owned', scenario_id: 'other' },
  ])('rejects a queued run for a substituted source %o', async (response) => {
    server.use(
      http.post('/api/v1/projects/owned/performance-scenarios/scene/runs', () =>
        HttpResponse.json({ ...response, id: 'new-run' }, { status: 202 }),
      ),
    )
    await expect(runPerformanceScenario('owned', 'scene')).rejects.toThrow('与当前项目或场景不符')
  })
  it.each(['performance-runs', 'performance-scenarios'])(
    'rejects a substituted exact %s read',
    async (resource) => {
      server.use(
        http.get(`/api/v1/projects/owned/${resource}/original`, () =>
          HttpResponse.json({ id: 'substituted', project_id: 'owned' }),
        ),
      )
      await expect(
        resource === 'performance-runs'
          ? getPerformanceRun('owned', 'original')
          : getPerformanceScenario('owned', 'original'),
      ).rejects.toThrow('与当前项目或ID不符')
    },
  )
})
