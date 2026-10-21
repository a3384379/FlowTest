import { http, HttpResponse } from 'msw'
import { expect, it } from 'vitest'
import { server } from '../../test/server'
import {
  createAIJob,
  getAIJob,
  getAISource,
  listAISuggestions,
  listAISources,
  reviewAISuggestion,
} from './ai-service'

it('rejects mismatched job, suggestion and review response identities', async () => {
  server.use(
    http.get('/api/v1/ai/jobs/:id', () =>
      HttpResponse.json({ id: 'other', project_id: 'foreign' }),
    ),
    http.post('/api/v1/ai/jobs', () => HttpResponse.json({ id: 'job', project_id: 'foreign' })),
    http.get('/api/v1/ai/jobs/:id/suggestions', () =>
      HttpResponse.json([{ id: 'suggestion', job_id: 'foreign' }]),
    ),
    http.post('/api/v1/ai/suggestions/:id/accept', () =>
      HttpResponse.json({ id: 'wrong', job_id: 'job' }),
    ),
  )
  await expect(getAIJob('project', 'job')).rejects.toThrow('身份')
  await expect(
    createAIJob({
      project_id: 'project',
      job_type: 'failure_analysis',
      metadata: { failure_summary: 'failed' },
    }),
  ).rejects.toThrow('身份')
  await expect(listAISuggestions('job')).rejects.toThrow('身份')
  await expect(reviewAISuggestion('suggestion', 'accept', { note: '' }, 'job')).rejects.toThrow(
    '身份',
  )
})
it('keeps project, search, pagination and fixed-version reads in the public-source contract', async () => {
  let catalog: URL | null = null,
    detail: URL | null = null
  server.use(
    http.get('/api/v1/ai/projects/project/sources', ({ request }) => {
      catalog = new URL(request.url)
      return HttpResponse.json({ items: [], total: 0, page: 2, page_size: 20 })
    }),
    http.get('/api/v1/ai/projects/project/sources/api/source', ({ request }) => {
      detail = new URL(request.url)
      return HttpResponse.json({
        project_id: 'project',
        metadata: { source_kind: 'api', source_id: 'source', version: 3 },
        schema_document: { path: '/v3' },
        notices: [],
      })
    }),
  )
  await listAISources('project', 'api', 2, '%_')
  expect(catalog!.searchParams.get('kind')).toBe('api')
  expect(catalog!.searchParams.get('page')).toBe('2')
  expect(catalog!.searchParams.get('search')).toBe('%_')
  const source = await getAISource('project', 'api', 'source', 3)
  expect(detail!.searchParams.get('version')).toBe('3')
  expect(source.schema_document).toEqual({ path: '/v3' })
})
it.each([
  { project_id: 'foreign', metadata: { source_kind: 'api', source_id: 'source', version: 3 } },
  {
    project_id: 'project',
    metadata: { source_kind: 'execution', source_id: 'source', version: 3 },
  },
  { project_id: 'project', metadata: { source_kind: 'api', source_id: 'other', version: 3 } },
  { project_id: 'project', metadata: { source_kind: 'api', source_id: 'source', version: 4 } },
])('rejects an unproven public-source response %#', async (payload) => {
  server.use(
    http.get('/api/v1/ai/projects/project/sources/api/source', () => HttpResponse.json(payload)),
  )
  await expect(getAISource('project', 'api', 'source', 3)).rejects.toThrow('不匹配')
})
