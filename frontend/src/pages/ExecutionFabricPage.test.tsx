import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App as AntdApp } from 'antd'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'

import { useAuthStore } from '../features/auth/auth-store'
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
  beforeEach(() => {
    useAuthStore.setState({ user, initialized: true, token: 'test-token' })
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

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <AntdApp>
      <QueryClientProvider client={queryClient}>
        <ExecutionFabricPage />
      </QueryClientProvider>
    </AntdApp>,
  )
}
