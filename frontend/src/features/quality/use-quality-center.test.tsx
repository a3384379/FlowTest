import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, screen, waitFor } from '@testing-library/react'
import { App } from 'antd'
import { createMemoryRouter, RouterProvider, useParams } from 'react-router-dom'
import { http, HttpResponse } from 'msw'
import { afterEach, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import { server } from '../../test/server'
import * as services from './quality-service'
import { useQualityCenter } from './use-quality-center'

vi.mock('../projects/use-project-context', () => ({
  useProjectContext: () => ({ projectId: useParams().projectId }),
}))

function workspace() {
  server.use(
    http.get('/api/v1/v3/features', () =>
      HttpResponse.json({ quality_intelligence: true, impact_engine: false }),
    ),
    http.get('/api/v1/projects/:projectId/permissions', () =>
      HttpResponse.json({ effective_role: 'owner', capabilities: ['read', 'edit'] }),
    ),
    http.get('/api/v1/projects/:projectId/quality-gates', () => HttpResponse.json([])),
    http.get('/api/v1/projects/:projectId/:resource', () =>
      HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 }),
    ),
  )
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  let router: ReturnType<typeof createMemoryRouter>
  function Wrapper({ children }: { children: ReactNode }) {
    router ??= createMemoryRouter(
      [
        {
          path: '/projects/:projectId/*',
          element: (
            <App>
              <QueryClientProvider client={client}>{children}</QueryClientProvider>
            </App>
          ),
        },
      ],
      { initialEntries: ['/projects/first-project/quality'] },
    )
    return <RouterProvider router={router} />
  }
  const hook = renderHook(() => useQualityCenter(), { wrapper: Wrapper })
  return { ...hook, router: router! }
}

afterEach(() => vi.restoreAllMocks())

it.each(['gate', 'risk', 'quarantine'] as const)(
  'keeps an in-flight %s command current while the initial risk catalog resolves',
  async (mode) => {
    let resolveRisks!: (value: never) => void, complete!: (value: never) => void
    vi.spyOn(services, 'listReleaseRisks').mockReturnValue(
      new Promise<never>((resolve) => {
        resolveRisks = resolve
      }),
    )
    vi.spyOn(services, 'getReleaseRisk').mockResolvedValue({
      id: 'initial-risk',
      project_id: 'first-project',
    } as never)
    const operation =
      mode === 'gate'
        ? 'createQualityGate'
        : mode === 'risk'
          ? 'createReleaseRisk'
          : 'setFlakyQuarantine'
    const command = vi.spyOn(services, operation).mockReturnValue(
      new Promise<never>((resolve) => {
        complete = resolve
      }),
    )
    const { result, router } = workspace()
    await waitFor(() => expect(result.current.canEdit && result.current.riskEnabled).toBe(true))
    let pending!: Promise<unknown>
    act(() => {
      pending =
        mode === 'gate'
          ? result.current.addGate({
              name: 'Owned gate',
              enabled: true,
              min_pass_rate: 100,
              max_failed: 0,
              max_flaky: 0,
              max_duration_regression_percent: 20,
              require_no_breaking_changes: true,
            })
          : mode === 'risk'
            ? result.current.addRisk({
                impact_run_id: 'impact',
                title: 'New risk',
                window_days: 30,
              })
            : result.current.toggleQuarantine('record', true)
    })
    await waitFor(() => expect(command).toHaveBeenCalledOnce())
    await act(async () => {
      resolveRisks({
        items: [{ id: 'initial-risk', project_id: 'first-project' }],
        total: 1,
        page: 1,
        page_size: 20,
      } as never)
    })
    await waitFor(() => expect(result.current.risks.isSuccess).toBe(true))
    let outcome: unknown
    await act(async () => {
      complete({ id: 'created-risk', project_id: 'first-project' } as never)
      outcome = await pending
    })
    if (mode !== 'quarantine') expect(outcome).toBe(true)
    const feedback = {
      gate: '质量门禁已创建',
      risk: '发布风险分析已完成',
      quarantine: '已隔离 Flaky 资产',
    }[mode]
    await waitFor(() => expect(screen.getByText(feedback)).toBeVisible())
    await waitFor(() =>
      expect(new URLSearchParams(router.state.location.search).get('risk')).toBe(
        mode === 'risk' ? 'created-risk' : 'initial-risk',
      ),
    )
    expect(command).toHaveBeenCalledOnce()
  },
)

it.each([
  'gate-success',
  'gate-error',
  'risk-success',
  'risk-error',
  'quarantine-success',
  'quarantine-error',
] as const)('discards a delayed %s after navigating before React commits', async (mode) => {
  let complete!: (value: never) => void
  let reject!: (error: Error) => void
  const operation = mode.startsWith('gate')
    ? 'createQualityGate'
    : mode.startsWith('risk')
      ? 'createReleaseRisk'
      : 'setFlakyQuarantine'
  const command = vi.spyOn(services, operation).mockReturnValue(
    new Promise<never>((resolve, fail) => {
      complete = resolve
      reject = fail
    }),
  )
  const { result, router } = workspace()
  await waitFor(() => expect(result.current.canEdit && result.current.riskEnabled).toBe(true))
  let pending!: Promise<unknown>
  act(() => {
    pending = mode.startsWith('gate')
      ? result.current.addGate({
          name: 'Owned gate',
          enabled: true,
          min_pass_rate: 100,
          max_failed: 0,
          max_flaky: 0,
          max_duration_regression_percent: 20,
          require_no_breaking_changes: true,
        })
      : mode.startsWith('risk')
        ? result.current.addRisk({
            impact_run_id: 'original-impact',
            title: 'Owned risk',
            window_days: 30,
          })
        : result.current.toggleQuarantine('original-record', true)
  })
  await waitFor(() => expect(command).toHaveBeenCalledOnce())
  const destination = '/projects/second-project/quality'
  await act(async () => {
    await router.navigate(destination)
    if (mode.endsWith('error')) reject(new Error('obsolete-quality-error'))
    else complete({ id: 'created', project_id: 'first-project' } as never)
    await pending
  })
  expect(router.state.location.pathname + router.state.location.search).toBe(destination)
  expect(screen.queryByText('obsolete-quality-error')).not.toBeInTheDocument()
  for (const feedback of ['质量门禁已创建', '发布风险分析已完成', '已隔离 Flaky 资产'])
    expect(screen.queryByText(feedback)).not.toBeInTheDocument()
})

it('does not use stale edit permission after permission refresh fails', async () => {
  const { result } = workspace()
  await waitFor(() => expect(result.current.canEdit).toBe(true))
  server.use(
    http.get('/api/v1/projects/:projectId/permissions', () =>
      HttpResponse.json(
        {
          error: {
            code: 'UNAVAILABLE',
            message: '权限读取失败',
            trace_id: 'quality-permission-trace',
          },
        },
        { status: 503 },
      ),
    ),
  )
  let refreshFailed = false
  await act(async () => {
    refreshFailed = (await result.current.permissions.refetch()).isError
  })
  expect(refreshFailed).toBe(true)
  await waitFor(() => expect(result.current.canEdit).toBe(false))
})
