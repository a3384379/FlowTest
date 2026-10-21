import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, screen, waitFor } from '@testing-library/react'
import { App as AntdApp } from 'antd'
import { http, HttpResponse } from 'msw'
import type { ReactNode } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { project, user } from '../../test/fixtures'
import ProjectTestProvider from '../../test/ProjectTestProvider'
import { server } from '../../test/server'
import type { ImpactRunDetail } from './impact-service'
import { useImpactAnalysis } from './use-impact-analysis'

const result: ImpactRunDetail = {
  id: 'created-impact',
  project_id: project.id,
  title: '冻结分析',
  source_ref: 'audit://impact',
  status: 'completed',
  source_fingerprint: 'a'.repeat(64),
  source_summary: {},
  change_count: 0,
  summary: {
    change_count: 0,
    breaking_change_count: 0,
    selected_asset_count: 0,
    covered_change_count: 0,
    gap_count: 0,
    coverage_percent: 100,
  },
  created_by_id: user.id,
  created_at: '2026-10-21T01:00:00Z',
  changes: [],
  graph: { nodes: [], edges: [] },
  selection: {
    id: 'selection',
    strategy: 'explicit_mapping_v1',
    selected_assets: [],
    explanations: [],
    created_at: '2026-10-21T01:00:00Z',
  },
  coverage: {
    id: 'coverage',
    total_changes: 0,
    covered_changes: 0,
    coverage_percent: 100,
    matrix: [],
    gaps: [],
    created_at: '2026-10-21T01:00:00Z',
  },
}

type Command = 'registerMapping' | 'deleteMapping' | 'analyze'
const cases = (['registerMapping', 'deleteMapping', 'analyze'] as const).flatMap((command) => [
  { command, failure: false },
  { command, failure: true },
])

describe('impact command ownership', () => {
  it.each(cases)(
    'keeps a late $command response scoped after navigation (failure=$failure)',
    async ({ command, failure }) => {
      installReads()
      let release!: () => void,
        posted = 0
      const barrier = new Promise<void>((resolve) => {
        release = resolve
      })
      const resource =
        command === 'analyze'
          ? 'runs'
          : command === 'deleteMapping'
            ? 'mappings/mapping-1'
            : 'mappings'
      const handler = command === 'deleteMapping' ? http.delete : http.post
      server.use(
        handler(`/api/v1/projects/${project.id}/impact/${resource}`, async () => {
          posted++
          await barrier
          if (failure)
            return HttpResponse.json(
              {
                error: {
                  code: 'UNAVAILABLE',
                  message: '旧上下文命令失败',
                  trace_id: 'old-impact-trace',
                },
              },
              { status: 503 },
            )
          if (command === 'deleteMapping') return new HttpResponse(null, { status: 204 })
          return HttpResponse.json(
            command === 'analyze' ? result : { id: 'mapping-1', project_id: project.id },
            { status: 201 },
          )
        }),
      )
      const client = new QueryClient({
        defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
      })
      const view = renderHook(
        () => ({ state: useImpactAnalysis(), navigate: useNavigate(), location: useLocation() }),
        {
          wrapper: ({ children }: { children: ReactNode }) => (
            <AntdApp>
              <QueryClientProvider client={client}>
                <ProjectTestProvider section="impact">{children}</ProjectTestProvider>
              </QueryClientProvider>
            </AntdApp>
          ),
        },
      )
      try {
        await waitFor(() => expect(view.result.current.state.canEdit).toBe(true))
        let pending!: Promise<boolean | void>
        act(() => {
          pending = invoke(view.result.current.state, command)
        })
        await waitFor(() => expect(posted).toBe(1))
        act(() => view.result.current.navigate('?run=another-run&change=new-change'))
        await act(async () => {
          release()
          await pending
        })
        expect(view.result.current.location.search).toBe('?run=another-run&change=new-change')
        expect(
          screen.queryByText(
            /影响资产映射已登记|影响资产映射已删除|影响分析完成，推荐集合与覆盖证据已保存|旧上下文命令失败/,
          ),
        ).not.toBeInTheDocument()
        expect(client.getQueryData(['impact-run', project.id, result.id])).toBeUndefined()
        expect(posted).toBe(1)
      } finally {
        release()
        view.unmount()
        client.clear()
      }
    },
  )

  it('disables commands when refreshed permissions are unavailable', async () => {
    installReads()
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const view = renderHook(() => useImpactAnalysis(), {
      wrapper: ({ children }: { children: ReactNode }) => (
        <AntdApp>
          <QueryClientProvider client={client}>
            <ProjectTestProvider section="impact">{children}</ProjectTestProvider>
          </QueryClientProvider>
        </AntdApp>
      ),
    })
    try {
      await waitFor(() => expect(view.result.current.canEdit).toBe(true))
      server.use(
        http.get(`/api/v1/projects/${project.id}/permissions`, () =>
          HttpResponse.json(
            {
              error: { code: 'UNAVAILABLE', message: '权限暂不可用', trace_id: 'permission-trace' },
            },
            { status: 503 },
          ),
        ),
      )
      await act(async () => {
        await client.invalidateQueries({ queryKey: ['project-permissions', project.id] })
      })
      await waitFor(() => expect(view.result.current.permissions.isError).toBe(true))
      expect(view.result.current.canEdit).toBe(false)
      expect(
        await view.result.current.registerMapping({
          source_kind: 'git',
          source_selector: 'audit/*',
          target_type: 'workflow',
          target_id: 'target-1',
        }),
      ).toBe(false)
    } finally {
      view.unmount()
      client.clear()
    }
  })
})

function invoke(state: ReturnType<typeof useImpactAnalysis>, command: Command) {
  if (command === 'deleteMapping') return state.deleteMapping('mapping-1')
  if (command === 'registerMapping')
    return state.registerMapping({
      source_kind: 'git',
      source_selector: 'audit/*',
      target_type: 'workflow',
      target_id: 'target-1',
    })
  return state.analyze({
    title: '人工分析',
    source_ref: 'audit://scope',
    git_diff: 'bounded fixture',
    openapi_diffs: [],
    schema_diffs: [],
  })
}

function installReads() {
  const empty = { items: [], total: 0, page: 1, page_size: 20 }
  server.use(
    http.get('/api/v1/v3/features', () => HttpResponse.json({ impact_engine: true })),
    http.get('/api/v1/projects', () =>
      HttpResponse.json({ items: [project], total: 1, page: 1, page_size: 100 }),
    ),
    ...['mappings', 'runs'].map((resource) =>
      http.get(`/api/v1/projects/${project.id}/impact/${resource}`, () => HttpResponse.json(empty)),
    ),
    http.get(`/api/v1/projects/${project.id}/impact/catalog`, () =>
      HttpResponse.json({ targets: [], schemas: [] }),
    ),
    http.get(`/api/v1/projects/${project.id}/impact/runs/:runId`, () =>
      HttpResponse.json(
        { error: { code: 'NOT_FOUND', message: '新分析尚不可访问', trace_id: 'new-run-trace' } },
        { status: 404 },
      ),
    ),
  )
}
