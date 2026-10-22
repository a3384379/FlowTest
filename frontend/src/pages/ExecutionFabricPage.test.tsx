import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within, waitFor, act, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App as AntdApp } from 'antd'
import { http, HttpResponse } from 'msw'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useAuthStore } from '../features/auth/auth-store'
import { authenticateTestUser } from '../test/auth'
import type {
  FabricEvent,
  FabricPool,
  FabricTask,
} from '../features/execution-fabric/execution-fabric-service'
import { user } from '../test/fixtures'
import { server } from '../test/server'
import ExecutionFabricPage from './ExecutionFabricPage'

const pool: FabricPool = {
  id: '00000000-0000-4000-8000-000000000501',
  name: 'General ARM64',
  runner_type: 'general',
  runtime: 'docker',
  network_zone: 'default',
  labels: ['arm64'],
  capabilities: ['flow.workflow'],
  max_concurrency: 20,
  lease_timeout_seconds: 30,
  heartbeat_timeout_seconds: 90,
  enabled: true,
  created_at: '2026-08-12T01:00:00Z',
  runners: [
    {
      id: '00000000-0000-4000-8000-000000000502',
      pool_id: '00000000-0000-4000-8000-000000000501',
      name: 'runner-a',
      status: 'online',
      runtime: 'docker',
      agent_version: '3.0.0-beta.3',
      architecture: 'arm64',
      labels: ['arm64'],
      capabilities: ['flow.workflow'],
      max_concurrency: 4,
      current_load: 1,
      last_seen_at: new Date().toISOString(),
      draining_requested_at: null,
      disabled_at: null,
    },
  ],
}

const tasks: FabricTask[] = [
  task('queued', 'general', 1),
  task('leased', 'general', 2),
  task('failed', 'protocol', 3),
]

const events: FabricEvent[] = [
  event('lease_acquired', 'Runner 已认领执行 Lease', 2),
  event('lease_expired', 'Runner Lease 已过期并触发 Fence', 1),
  event('lease_fenced', '旧 Worker 写入被拒绝', 1),
  event('lease_completed', 'Runner Lease 已写入唯一终态', 2),
]

describe('ExecutionFabricPage', () => {
  it('does not request administrator execution data when the fabric feature is closed', async () => {
    let reads = 0
    installHandlers()
    server.use(
      http.get('/api/v1/v3/features', () => HttpResponse.json({ runner_fabric: false })),
      http.get('/api/v1/execution-fabric/*', () => {
        reads += 1
        return HttpResponse.json({})
      }),
    )
    renderPage()
    expect(await screen.findByText('分布式执行面尚未启用')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /新建 Worker Pool/ })).not.toBeInTheDocument()
    expect(reads).toBe(0)
  })

  beforeEach(() => {
    authenticateTestUser(user)
  })

  it('blocks regular users before requesting administrator data', () => {
    useAuthStore.setState({ user: { ...user, is_system_admin: false } })
    renderPage()
    expect(screen.getByText('仅系统管理员可管理分布式执行面')).toBeVisible()
  })

  it('shows workers, queues, fencing evidence and operates drain and registration', async () => {
    let action = ''
    installHandlers({
      onAction: (value) => {
        action = value
      },
    })
    renderPage()
    const browser = userEvent.setup()

    expect(await screen.findByText('PostgreSQL 是任务、Lease 与 Fence 的唯一真相源')).toBeVisible()
    expect(await screen.findByText('runner-a')).toBeVisible()
    expect(screen.getByText('排队 1 · 运行 1 · 失败 0')).toBeVisible()
    expect(screen.getByText('排队 0 · 运行 0 · 失败 1')).toBeVisible()
    expect(screen.getByText('已回收')).toBeVisible()
    expect(screen.getByText('已拒绝')).toBeVisible()
    expect(screen.getByText('已接管')).toBeVisible()
    expect(screen.getByText('唯一终态')).toBeVisible()

    await browser.click(screen.getByRole('button', { name: 'Drain' }))
    expect(action).toBe('drain')
    expect(await screen.findByText('Runner 状态已更新')).toBeInTheDocument()

    await browser.click(screen.getByRole('button', { name: /General ARM64 · 签发注册令牌/ }))
    expect(await screen.findByText('令牌只显示一次')).toBeInTheDocument()
    expect(screen.getByText('ftrreg_once-only-token')).toBeInTheDocument()
    const registrationDialog = screen.getByRole('dialog', { name: '一次性 Runner 注册令牌' })
    await browser.click(within(registrationDialog).getByRole('button', { name: 'Close' }))

    await browser.click(screen.getByLabelText('Expand row'))
    expect(await screen.findByText('PostgreSQL 单调递增')).toBeVisible()
  })

  it('uses the server aggregate and reaches Pool 101 without counting a task sample', async () => {
    installHandlers()
    const pages: string[] = []
    server.use(
      http.get('/api/v1/execution-fabric/queue', () =>
        HttpResponse.json({
          generated_at: '2026-10-21T01:00:00Z',
          scope: 'all_organizations',
          organization_id: null,
          groups: [{ runner_type: 'general', queued: 150, leased: 12, failed: 9 }],
        }),
      ),
      http.get('/api/v1/execution-fabric/pools', ({ request }) => {
        const number = new URL(request.url).searchParams.get('page') ?? '1'
        pages.push(number)
        return HttpResponse.json({
          items: [
            {
              ...pool,
              id: `pool-${number}`,
              name: number === '6' ? 'Pool 101' : pool.name,
              runners: [],
            },
          ],
          total: 101,
          page: Number(number),
          page_size: 20,
        })
      }),
    )
    renderPage()
    expect(await screen.findByText('排队 150 · 运行 12 · 失败 9')).toBeVisible()
    expect(screen.getByText(/服务端全量聚合/)).toBeVisible()
    await userEvent.click(screen.getByTitle('6'))
    expect(await screen.findByRole('button', { name: 'Pool 101 · 签发注册令牌' })).toBeVisible()
    expect(pages).toEqual(['1', '6'])
  })

  it('loads an exact task outside the directory and distinguishes old Lease fences', async () => {
    installHandlers()
    const current = {
      ...tasks[1],
      last_lease_id: 'lease-current',
      fencing_token: 2,
      selected_runner_id: pool.runners[0].id,
    }
    const lease = {
      id: 'lease-current',
      task_id: current.id,
      runner_id: current.selected_runner_id,
      fencing_token: 2,
      status: 'active',
      acquired_at: '2026-10-21T01:00:00Z',
      expires_at: '2099-10-21T01:00:00Z',
      last_renewed_at: '2026-10-21T01:01:00Z',
      completed_at: null,
    }
    server.use(
      http.get('/api/v1/execution-fabric/tasks', () => page([])),
      http.get('/api/v1/execution-fabric/tasks/:id', () => HttpResponse.json(current)),
      http.get('/api/v1/execution-fabric/leases', ({ request }) => {
        expect(new URL(request.url).searchParams.get('task_id')).toBe(current.id)
        return page([
          lease,
          { ...lease, id: 'lease-old', fencing_token: 1, expires_at: '2026-01-01T00:00:00Z' },
        ])
      }),
    )
    const view = renderPage(`/execution-fabric?task=${current.id}`)
    expect(await screen.findByText('当前有效 Lease')).toBeVisible()
    expect(screen.getByText('已过期，等待回收')).toBeVisible()
    expect(screen.getByRole('link', { name: '查看执行报告' })).toHaveAttribute(
      'href',
      expect.stringContaining(`execution=${current.execution_id}`),
    )
    expect(screen.getByRole('link', { name: '查看工作流执行' })).toHaveAttribute(
      'href',
      expect.stringContaining(current.project_id),
    )
    await waitFor(() => expect(view.queryClient.isFetching()).toBe(0))
    server.use(
      http.get('/api/v1/execution-fabric/leases', () =>
        HttpResponse.json(
          { error: { code: 'OFFLINE', message: 'Lease 暂不可用' } },
          { status: 503 },
        ),
      ),
    )
    await userEvent.click(screen.getByRole('button', { name: '刷新执行面' }))
    expect(
      await screen.findByText('部分详情刷新失败，保留的 Lease、事件或 Worker 数据可能过期'),
    ).toBeVisible()
    expect(screen.queryByText('当前有效 Lease')).not.toBeInTheDocument()
    expect(screen.getAllByText('有效性待刷新核对')).toHaveLength(2)
  })

  it('opens the resolved task and exact Lease from a lease-only progress event without writes', async () => {
    installHandlers()
    const leaseId = '00000000-0000-4000-8000-000000000699'
    const current = {
      ...tasks[1],
      last_lease_id: leaseId,
      fencing_token: 7,
      selected_runner_id: pool.runners[0].id,
    }
    const progress = {
      ...event('lease_renewed', '真实 Lease-only 进度', 7),
      task_id: null,
      resolved_task_id: current.id,
      lease_id: leaseId,
      details: { progress_percent: 42 },
    }
    const purePool = {
      ...event('registered', '纯 Pool 注册事件', 0),
      task_id: null,
      resolved_task_id: null,
      lease_id: null,
    }
    const unresolved = {
      ...event('lease_renewed', '无法解析的历史事件', 0),
      task_id: 'missing-task',
      resolved_task_id: null,
    }
    const direct = {
      ...event('lease_acquired', '原始 Task 事件', 7),
      task_id: current.id,
      resolved_task_id: current.id,
    }
    let writes = 0
    const exactReads: string[] = []
    server.use(
      http.get('/api/v1/execution-fabric/tasks', () => page([])),
      http.get('/api/v1/execution-fabric/tasks/:id', ({ params }) => {
        exactReads.push(String(params.id))
        return HttpResponse.json(current)
      }),
      http.get('/api/v1/execution-fabric/events', ({ request }) => {
        const taskId = new URL(request.url).searchParams.get('task_id')
        if (taskId) expect(taskId).toBe(current.id)
        return page(taskId ? [progress, direct] : [progress, purePool, unresolved, direct])
      }),
      http.get('/api/v1/execution-fabric/leases', ({ request }) => {
        expect(new URL(request.url).searchParams.get('task_id')).toBe(current.id)
        return page([
          {
            id: leaseId,
            task_id: current.id,
            runner_id: current.selected_runner_id,
            fencing_token: 7,
            status: 'active',
            acquired_at: '2026-10-22T01:00:00Z',
            expires_at: '2099-10-22T01:00:00Z',
            last_renewed_at: '2026-10-22T01:01:00Z',
            completed_at: null,
          },
        ])
      }),
      http.post('/api/v1/execution-fabric/*', () => {
        writes++
        return HttpResponse.json({})
      }),
    )
    renderPage()
    const progressRow = (await screen.findByText(progress.message)).closest('tr')!
    const taskLink = within(progressRow).getByRole('button')
    expect(taskLink).toBeVisible()
    expect(
      within(screen.getByText(purePool.message).closest('tr')!).queryByRole('button'),
    ).toBeNull()
    expect(
      within(screen.getByText(unresolved.message).closest('tr')!).queryByRole('button'),
    ).toBeNull()
    expect(
      within(screen.getByText(direct.message).closest('tr')!).getByRole('button'),
    ).toBeVisible()
    await userEvent.setup().click(taskLink)
    const drawer = (await screen.findByText('任务与 Lease 只读证据')).closest<HTMLElement>(
      '[role="dialog"]',
    )!
    expect(drawer).toHaveRole('dialog')
    expect(drawer).toBeVisible()
    await waitFor(() => expect(within(drawer).getByText('当前有效 Lease')).toBeVisible())
    const taskIdCell = within(drawer).getByText('任务 ID').closest('td')!
    expect(within(taskIdCell).getByText(current.id)).toBeVisible()
    expect(within(drawer).getAllByText(leaseId).length).toBeGreaterThan(0)
    const leaseRow = within(drawer).getByText('当前有效 Lease').closest('tr')!
    expect(within(leaseRow).getByText('7')).toBeVisible()
    expect(screen.getByTestId('fabric-location')).toHaveTextContent(`task=${current.id}`)
    expect(exactReads).toEqual([current.id])
    expect(writes).toBe(0)
  })

  it('retains old data on refresh failure without performing a state action', async () => {
    let writes = 0
    installHandlers({
      onAction: () => {
        writes += 1
      },
    })
    const view = renderPage()
    await screen.findByText('runner-a')
    await waitFor(() => expect(view.queryClient.isFetching()).toBe(0))
    server.use(
      http.get('/api/v1/execution-fabric/queue', () =>
        HttpResponse.json(
          { error: { code: 'OFFLINE', message: '聚合暂不可用', trace_id: 'fabric-trace' } },
          { status: 503 },
        ),
      ),
    )
    await userEvent.click(screen.getByRole('button', { name: '刷新执行面' }))
    expect(await screen.findByText('读取失败，已显示的数据可能过期；请刷新后核对')).toBeVisible()
    expect(screen.getByText('排队 1 · 运行 1 · 失败 0')).toBeVisible()
    expect(screen.getByText(/fabric-trace/)).toBeVisible()
    await waitFor(() => expect(writes).toBe(0))
  })

  it('does not show a late task from the previous organization', async () => {
    installHandlers()
    let finish: (value: Response) => void = () => undefined
    let reads = 0
    server.use(
      http.get('/api/v1/execution-fabric/tasks/:id', () => {
        reads += 1
        if (reads === 1)
          return new Promise<Response>((resolve) => {
            finish = resolve
          })
        return HttpResponse.json(
          { error: { code: 'RUNNER_TASK_NOT_FOUND', message: '当前组织任务不存在' } },
          { status: 404 },
        )
      }),
    )
    renderPage(`/execution-fabric?task=${tasks[0].id}`)
    await waitFor(() => expect(reads).toBe(1))
    act(() => {
      useAuthStore.setState({ organizationId: 'other-organization' })
    })
    expect(await screen.findByText('当前组织任务不存在')).toBeVisible()
    await act(async () => {
      finish(HttpResponse.json(tasks[0]))
    })
    expect(screen.queryByText(tasks[0].execution_id)).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: '查看执行报告' })).not.toBeInTheDocument()
  })

  it('polls visible pages and pauses while the page is hidden', async () => {
    let reads = 0
    installHandlers()
    server.use(
      http.get('/api/v1/execution-fabric/overview', () => {
        reads += 1
        return HttpResponse.json({
          pools: 1,
          runners_online: reads,
          runners_offline: 0,
          runners_draining: 0,
          queued_tasks: 1,
          active_leases: 1,
          completed_tasks: 4,
          failed_tasks: 1,
        })
      }),
    )
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    const visibility = vi.spyOn(document, 'visibilityState', 'get')
    try {
      renderPage()
      await screen.findByText('runner-a')
      await waitFor(() => expect(reads).toBe(1))
      visibility.mockReturnValue('hidden')
      act(() => {
        fireEvent(document, new Event('visibilitychange'))
      })
      await act(async () => {
        await vi.advanceTimersByTimeAsync(30_000)
      })
      expect(reads).toBe(1)
      visibility.mockReturnValue('visible')
      act(() => {
        fireEvent(document, new Event('visibilitychange'))
      })
      await act(async () => {
        await vi.advanceTimersByTimeAsync(15_000)
      })
      await waitFor(() => expect(reads).toBe(2))
    } finally {
      visibility.mockRestore()
      vi.useRealTimers()
    }
  })

  it('creates a constrained worker pool and reports query failure', async () => {
    let submitted: Record<string, unknown> | undefined
    installHandlers({
      onPool: (value) => {
        submitted = value
      },
    })
    renderPage()
    const browser = userEvent.setup()
    await screen.findByText('runner-a')
    await browser.click(screen.getByRole('button', { name: /新建 Worker Pool/ }))
    const dialog = await screen.findByRole('dialog', { name: '新建 Worker Pool' })
    await browser.type(within(dialog).getByLabelText('Pool 名称'), 'Protocol Pool')
    await browser.type(within(dialog).getByLabelText('必需标签（逗号分隔）'), 'arm64, zone.cn')
    await browser.click(within(dialog).getByRole('button', { name: '创建 Pool' }))
    expect(await screen.findByText('Worker Pool 已创建')).toBeInTheDocument()
    expect(submitted).toMatchObject({
      name: 'Protocol Pool',
      runner_type: 'general',
      runtime: 'docker',
      labels: ['arm64', 'zone.cn'],
      capabilities: ['flow.workflow'],
    })

    server.use(
      http.get('/api/v1/execution-fabric/overview', () =>
        HttpResponse.json({ error: 'down' }, { status: 503 }),
      ),
    )
    renderPage()
    expect(await screen.findByText('执行面数据加载失败')).toBeVisible()
  })
})

function installHandlers({
  onAction,
  onPool,
}: {
  onAction?: (action: string) => void
  onPool?: (payload: Record<string, unknown>) => void
} = {}) {
  server.use(
    http.get('/api/v1/v3/features', () => HttpResponse.json({ runner_fabric: true })),
    http.get('/api/v1/execution-fabric/overview', () =>
      HttpResponse.json({
        pools: 1,
        runners_online: 1,
        runners_offline: 0,
        runners_draining: 0,
        queued_tasks: 1,
        active_leases: 1,
        completed_tasks: 4,
        failed_tasks: 1,
      }),
    ),
    http.get('/api/v1/execution-fabric/queue', () =>
      HttpResponse.json({
        generated_at: '2026-10-21T01:00:00Z',
        scope: 'all_organizations',
        organization_id: null,
        groups: [
          { runner_type: 'general', queued: 1, leased: 1, failed: 0 },
          { runner_type: 'protocol', queued: 0, leased: 0, failed: 1 },
        ],
      }),
    ),
    http.get('/api/v1/execution-fabric/pools', () => page([pool])),
    http.get('/api/v1/execution-fabric/tasks', () => page(tasks)),
    http.get('/api/v1/execution-fabric/leases', () => page([])),
    http.get('/api/v1/execution-fabric/events', () => page(events)),
    http.post('/api/v1/execution-fabric/runners/:runnerId/actions', async ({ request }) => {
      const payload = (await request.json()) as { action: string }
      onAction?.(payload.action)
      return HttpResponse.json({ ...pool.runners[0], status: 'draining' })
    }),
    http.post('/api/v1/execution-fabric/pools/:poolId/registration-tokens', () =>
      HttpResponse.json({
        id: '00000000-0000-4000-8000-000000000510',
        pool_id: pool.id,
        token: 'ftrreg_once-only-token',
        expires_at: '2026-08-12T01:15:00Z',
      }),
    ),
    http.post('/api/v1/execution-fabric/pools', async ({ request }) => {
      const payload = (await request.json()) as Record<string, unknown>
      onPool?.(payload)
      return HttpResponse.json(
        { ...pool, ...payload, id: 'new-pool', runners: [] },
        { status: 201 },
      )
    }),
  )
}

function task(status: FabricTask['status'], runnerType: string, index: number): FabricTask {
  return {
    id: `00000000-0000-4000-8000-00000000060${index}`,
    execution_id: `00000000-0000-4000-8000-00000000061${index}`,
    project_id: '00000000-0000-4000-8000-000000000620',
    required_runner_type: runnerType,
    required_labels: [],
    required_capabilities: ['flow.workflow'],
    status,
    priority: 5,
    attempts: status === 'queued' ? 0 : 1,
    max_attempts: 3,
    fencing_token: status === 'queued' ? 0 : 1,
    available_at: '2026-08-12T01:00:00Z',
    selected_runner_id: null,
    last_lease_id: null,
    error_code: status === 'failed' ? 'RUNNER_FAILED' : null,
    error_message: null,
    completed_at: status === 'failed' ? '2026-08-12T01:01:00Z' : null,
    created_at: '2026-08-12T01:00:00Z',
  }
}

function event(kind: string, message: string, fence: number): FabricEvent {
  return {
    id: crypto.randomUUID(),
    pool_id: pool.id,
    runner_id: pool.runners[0].id,
    task_id: '00000000-0000-4000-8000-000000000601',
    lease_id: '00000000-0000-4000-8000-000000000602',
    kind,
    message,
    details: { fencing_token: fence },
    created_at: '2026-08-12T01:00:00Z',
  }
}

function page<T>(items: T[]) {
  return HttpResponse.json({ items, total: items.length, page: 1, page_size: 100 })
}

function renderPage(entry = '/execution-fabric') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const view = render(
    <AntdApp>
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[entry]}>
          <ExecutionFabricPage />
          <FabricLocation />
        </MemoryRouter>
      </QueryClientProvider>
    </AntdApp>,
  )
  return { ...view, queryClient }
}

function FabricLocation() {
  return (
    <span data-testid="fabric-location" hidden>
      {useLocation().search}
    </span>
  )
}
