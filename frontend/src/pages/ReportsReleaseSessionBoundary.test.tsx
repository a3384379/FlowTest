import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, screen, waitFor } from '@testing-library/react'
import { App, ConfigProvider } from 'antd'
import { http, HttpResponse } from 'msw'
import type { ReactNode } from 'react'
import { afterEach, expect, it } from 'vitest'

import { useAuthStore } from '../features/auth/auth-store'
import {
  listReleaseDecisions,
  type ReleaseDecision,
} from '../features/release-gate/release-gate-service'
import { useReleaseGate } from '../features/release-gate/use-release-gate'
import { listNotificationWebhooks } from '../features/reports/report-service'
import { useReports } from '../features/reports/use-reports'
import {
  SessionBoundaryError,
  setOrganizationId,
  type NotificationWebhook,
  type Page,
} from '../lib/api'
import { authenticateTestUser } from '../test/auth'
import { project, user } from '../test/fixtures'
import ProjectTestProvider from '../test/ProjectTestProvider'
import { server } from '../test/server'

type Command = 'create-webhook' | 'toggle-webhook' | 'create-decision'
const commands: Command[] = ['create-webhook', 'toggle-webhook', 'create-decision']
const secondProject = { ...project, id: '00000000-0000-4000-8000-000000000802' }
const organizationId = '00000000-0000-4000-8000-000000000801'
const date = '2026-10-22T00:00:00Z'
const secret = 'synthetic-once-only-boundary-secret'
const webhook: NotificationWebhook = {
  id: 'boundary-webhook',
  project_id: project.id,
  name: '边界通知',
  url: 'https://notify.example.test/boundary',
  events: ['workflow.completed'],
  enabled: true,
  created_by_id: user.id,
  created_at: date,
  updated_at: date,
}
const decision: ReleaseDecision = {
  id: 'boundary-decision',
  project_id: project.id,
  release_policy_id: 'boundary-policy',
  candidate_ref: 'boundary-ref',
  status: 'pass',
  policy_snapshot: {
    snapshot_version: '1',
    policy_id: 'boundary-policy',
    policy_updated_at: date,
    name: '边界策略',
    quality_gate_id: null,
    require_quality_gate: false,
    require_contract_compatibility: false,
    require_impact_evidence: false,
    min_impact_coverage_percent: 0,
    require_release_risk: false,
    max_release_risk_score: 100,
    require_performance_evidence: false,
    require_runner_evidence: false,
  },
  evidence_snapshot: {
    snapshot_version: '1',
    quality_gate: null,
    contract_compatibility: null,
    impact: null,
    release_risk: null,
    performance: null,
    runner: null,
  },
  reasons: [],
  fingerprint: 'a'.repeat(64),
  test_plan_run_id: null,
  deployment_check_id: null,
  impact_run_id: null,
  release_risk_id: null,
  performance_run_id: null,
  runner_task_id: null,
  created_by_id: user.id,
  created_at: date,
}
const emptyPage: Page<ReleaseDecision> = { items: [], total: 0, page: 1, page_size: 20 }
const webhookKey = (id = project.id) => ['notification-webhooks', id]
const decisionKey = (id = project.id, page = 1) => ['release-decisions', id, '', 'catalog', page]
const latestKey = (id = project.id) => ['release-latest-decision', id]

afterEach(() => {
  setOrganizationId(null)
  useAuthStore.setState({ user: null })
})

function pendingResponse() {
  let release!: () => void
  let notify!: () => void
  const pending = new Promise<void>((resolve) => {
    release = resolve
  })
  const started = new Promise<void>((resolve) => {
    notify = resolve
  })
  return { pending, started, release, notify }
}

function useCommands() {
  return { reports: useReports(), release: useReleaseGate() }
}

function renderCommands(client: QueryClient, projectId = project.id) {
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <ConfigProvider theme={{ token: { motion: false } }}>
        <App>
          <QueryClientProvider client={client}>
            <ProjectTestProvider
              section="reports"
              initialEntry={`/projects/${projectId}/reports?reportFrom=2026-10-20&reportTo=2026-10-22`}
            >
              {children}
            </ProjectTestProvider>
          </QueryClientProvider>
        </App>
      </ConfigProvider>
    )
  }
  return renderHook(useCommands, { wrapper: Wrapper })
}

function runCommand(command: Command, current: ReturnType<typeof useCommands>) {
  if (command === 'create-decision')
    return current.release.evaluate({
      release_policy_id: decision.release_policy_id,
      candidate_ref: decision.candidate_ref,
    })
  if (command === 'toggle-webhook') return current.reports.setWebhookEnabled(webhook.id, false)
  return current.reports.addWebhook({
    name: webhook.name,
    url: webhook.url,
    events: webhook.events,
  })
}

function setup(command: Command, holdRefresh = false, outcome: 'success' | 'failure' = 'success') {
  authenticateTestUser(user)
  setOrganizationId(null)
  const receipt = pendingResponse()
  const refresh = pendingResponse()
  const oldRead = pendingResponse()
  const reads: { projectId: string; organizationId: string | null }[] = []
  let writes = 0
  let applied = false
  let holdRead = false
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 15_000 }, mutations: { retry: false } },
  })
  for (const id of [project.id, secondProject.id]) {
    client.setQueryData(webhookKey(id), command === 'toggle-webhook' ? [webhook] : [])
    client.setQueryData(decisionKey(id), emptyPage)
    client.setQueryData(decisionKey(id, 2), { ...emptyPage, page: 2 })
    client.setQueryData(latestKey(id), { ...emptyPage, page_size: 1 })
  }
  async function trackRead(projectId: string, request: Request) {
    reads.push({ projectId, organizationId: request.headers.get('X-Organization-Id') })
    if (holdRead) {
      holdRead = false
      oldRead.notify()
      await oldRead.pending
    }
    if (holdRefresh && applied) {
      refresh.notify()
      await refresh.pending
    }
  }
  async function writeResponse() {
    writes += 1
    receipt.notify()
    await receipt.pending
    if (outcome === 'failure')
      return HttpResponse.json(
        {
          error: {
            code: 'SERVICE_UNAVAILABLE',
            message: '合成服务暂不可用',
            trace_id: 'synthetic-boundary-failure',
          },
        },
        { status: 503 },
      )
    applied = true
    if (command === 'create-decision') return HttpResponse.json(decision, { status: 201 })
    if (command === 'toggle-webhook') return HttpResponse.json({ ...webhook, enabled: false })
    return HttpResponse.json({ ...webhook, secret }, { status: 201 })
  }
  server.use(
    http.get('/api/v1/projects', () =>
      HttpResponse.json({ items: [project, secondProject], total: 2, page: 1, page_size: 100 }),
    ),
    http.get('/api/v1/projects/:projectId', ({ params }) =>
      HttpResponse.json(params.projectId === secondProject.id ? secondProject : project),
    ),
    http.get('/api/v1/projects/:projectId/permissions', () =>
      HttpResponse.json({
        effective_role: 'owner',
        capabilities: ['read', 'edit', 'manage_members'],
        matrix: {},
      }),
    ),
    http.get('/api/v1/projects/:projectId/reports/executions', () => HttpResponse.json(emptyPage)),
    http.get('/api/v1/projects/:projectId/reports/trends', () =>
      HttpResponse.json({ summary: { pending: 0 }, points: [], failures: [] }),
    ),
    http.get('/api/v1/projects/:projectId/notification-deliveries', () =>
      HttpResponse.json(emptyPage),
    ),
    http.get('/api/v1/projects/:projectId/quality-gates', () => HttpResponse.json([])),
    http.get('/api/v1/projects/:projectId/release-policies', () => HttpResponse.json([])),
    http.get('/api/v1/projects/:projectId/notification-webhooks', async ({ params, request }) => {
      const items = applied
        ? [{ ...webhook, enabled: command !== 'toggle-webhook' }]
        : command === 'toggle-webhook'
          ? [webhook]
          : []
      await trackRead(String(params.projectId), request)
      return HttpResponse.json(items)
    }),
    http.get('/api/v1/projects/:projectId/release-decisions', async ({ params, request }) => {
      const snapshot = {
        ...emptyPage,
        page_size: Number(new URL(request.url).searchParams.get('page_size')),
        items: applied ? [decision] : [],
        total: applied ? 1 : 0,
      }
      await trackRead(String(params.projectId), request)
      return HttpResponse.json(snapshot)
    }),
    http.get(`/api/v1/projects/${project.id}/release-decisions/${decision.id}`, () =>
      HttpResponse.json(decision),
    ),
    http.post(`/api/v1/projects/${project.id}/notification-webhooks`, writeResponse),
    http.patch(`/api/v1/projects/${project.id}/notification-webhooks/${webhook.id}`, writeResponse),
    http.post(`/api/v1/projects/${project.id}/release-decisions`, writeResponse),
  )
  return {
    client,
    receipt,
    refresh,
    reads,
    oldRead,
    holdRead: () => {
      holdRead = true
    },
    writes: () => writes,
    applied: () => applied,
  }
}

function affectedKeys(command: Command) {
  return command === 'create-decision'
    ? [decisionKey(), decisionKey(project.id, 2), latestKey()]
    : [webhookKey()]
}

async function ready(view: ReturnType<typeof renderCommands>) {
  await waitFor(() => {
    expect(view.result.current.reports.canManageNotifications).toBe(true)
    expect(view.result.current.release.canEdit).toBe(true)
  })
}

it.each([
  { command: 'create-webhook', latest: false },
  { command: 'toggle-webhook', latest: false },
  { command: 'create-decision', latest: false },
  { command: 'create-decision', latest: true },
] as const)(
  'does not let a pre-write $command GET overwrite authoritative data after a scope roundtrip (latest=$latest)',
  async ({ command, latest }) => {
    const state = setup(command)
    const original = renderCommands(state.client)
    await ready(original)
    const heldKey =
      command === 'create-decision' ? (latest ? latestKey() : decisionKey()) : webhookKey()
    state.holdRead()
    let transport!: Promise<NotificationWebhook[] | Page<ReleaseDecision>>
    let background!: Promise<unknown>
    act(() => {
      background = state.client
        .fetchQuery<NotificationWebhook[] | Page<ReleaseDecision>>({
          queryKey: heldKey,
          staleTime: 0,
          queryFn: () => {
            transport =
              command === 'create-decision'
                ? listReleaseDecisions(project.id, 1, latest ? 1 : 20)
                : listNotificationWebhooks(project.id)
            return transport
          },
        })
        .catch((error: unknown) => error)
    })
    await state.oldRead.started
    let operation!: Promise<void | boolean>
    act(() => {
      operation = runCommand(command, original.result.current)
    })
    await state.receipt.started
    try {
      original.unmount()
      act(() => setOrganizationId(organizationId))
      await act(async () => {
        state.receipt.release()
        await operation
      })
      expect(state.client.getMutationCache().getAll().at(-1)?.state.error).toBeInstanceOf(
        SessionBoundaryError,
      )
      expect(state.client.getQueryState(heldKey)?.isInvalidated).toBe(true)
      for (const key of [
        webhookKey(secondProject.id),
        decisionKey(secondProject.id),
        latestKey(secondProject.id),
      ])
        expect(state.client.getQueryState(key)?.isInvalidated).toBe(false)
      act(() => setOrganizationId(null))
      const returned = renderCommands(state.client)
      await ready(returned)
      const expectAuthoritative = () => {
        if (command === 'create-decision') {
          expect(returned.result.current.release.decisions.data?.items).toEqual([decision])
          expect(returned.result.current.release.latestDecision.data?.items).toEqual([decision])
        } else
          expect(returned.result.current.reports.webhooks.data).toEqual([
            { ...webhook, enabled: command !== 'toggle-webhook' },
          ])
      }
      await expect.soft(waitFor(expectAuthoritative)).resolves.toBeUndefined()
      // Wait for the real SDK promise as well: the query promise can settle on cancellation
      // while its deliberately non-abortable transport still returns the old snapshot later.
      await act(async () => {
        state.oldRead.release()
        await transport
        await background
      })
      expectAuthoritative()
      expect(state.writes()).toBe(1)
      expect(state.reads.every((read) => read.organizationId === null)).toBe(true)
      expect(returned.result.current.reports.revealedSecret).toBeNull()
    } finally {
      state.receipt.release()
      state.oldRead.release()
      await Promise.allSettled([transport, background])
    }
  },
)

it.each(commands.flatMap((command) => [true, false].map((unmount) => ({ command, unmount }))))(
  'reconciles only the original $command scope after a real organization boundary (unmount=$unmount)',
  async ({ command, unmount }) => {
    const state = setup(command)
    const original = renderCommands(state.client)
    await ready(original)
    let operation!: Promise<void | boolean>
    act(() => {
      operation = runCommand(command, original.result.current)
    })
    await state.receipt.started
    try {
      if (unmount) original.unmount()
      act(() => setOrganizationId(organizationId))
      const foreign = renderCommands(state.client, secondProject.id)
      await ready(foreign)
      await act(async () => {
        state.receipt.release()
        await operation
      })
      expect(state.applied()).toBe(true)
      expect(state.writes()).toBe(1)
      expect(state.client.isMutating()).toBe(0)
      expect(state.client.getMutationCache().getAll().at(-1)?.state.error).toBeInstanceOf(
        SessionBoundaryError,
      )
      for (const key of affectedKeys(command))
        expect.soft(state.client.getQueryState(key)?.isInvalidated).toBe(true)
      for (const key of [
        webhookKey(secondProject.id),
        decisionKey(secondProject.id),
        decisionKey(secondProject.id, 2),
        latestKey(secondProject.id),
      ])
        expect(state.client.getQueryState(key)?.isInvalidated).toBe(false)
      expect(state.reads.filter((read) => read.projectId === project.id)).toEqual([])
      expect(foreign.result.current.reports.revealedSecret).toBeNull()
      expect(foreign.result.current.release.decisionId).toBeNull()
      expect(screen.queryByText('通知 Webhook 已创建')).not.toBeInTheDocument()
      expect(screen.queryByText('发布判断：PASS')).not.toBeInTheDocument()
      expect(
        JSON.stringify(
          state.client
            .getQueryCache()
            .getAll()
            .map((query) => query.state.data),
        ),
      ).not.toContain(secret)
      expect(
        JSON.stringify(
          state.client
            .getMutationCache()
            .getAll()
            .map((mutation) => mutation.state.data),
        ),
      ).not.toContain(secret)
      if (!unmount) {
        expect(original.result.current.reports.revealedSecret).toBeNull()
        original.unmount()
      }
      foreign.unmount()
      act(() => setOrganizationId(null))
      const returned = renderCommands(state.client)
      await ready(returned)
      await waitFor(() => {
        if (command === 'create-decision') {
          expect(returned.result.current.release.decisions.data?.items).toEqual([decision])
          expect(returned.result.current.release.latestDecision.data?.items).toEqual([decision])
        } else
          expect(returned.result.current.reports.webhooks.data).toEqual([
            { ...webhook, enabled: command !== 'toggle-webhook' },
          ])
      })
      expect(state.reads.filter((read) => read.projectId === project.id).length).toBeGreaterThan(0)
      expect(state.reads.every((read) => read.organizationId === null)).toBe(true)
      expect(returned.result.current.reports.revealedSecret).toBeNull()
      expect(state.writes()).toBe(1)
    } finally {
      state.receipt.release()
    }
  },
)

it.each(commands)(
  'reconciles a successful %s after ordinary unmount without revealing its result elsewhere',
  async (command) => {
    const state = setup(command)
    const original = renderCommands(state.client)
    await ready(original)
    let operation!: Promise<void | boolean>
    act(() => {
      operation = runCommand(command, original.result.current)
    })
    await state.receipt.started
    try {
      original.unmount()
      const foreign = renderCommands(state.client, secondProject.id)
      await ready(foreign)
      await act(async () => {
        state.receipt.release()
        await operation
      })
      for (const key of affectedKeys(command))
        expect(state.client.getQueryState(key)?.isInvalidated).toBe(true)
      expect(state.client.getMutationCache().getAll().at(-1)?.state.error).toBeNull()
      expect(state.writes()).toBe(1)
      expect(foreign.result.current.reports.revealedSecret).toBeNull()
      expect(foreign.result.current.release.decisionId).toBeNull()
      expect(screen.queryByText('通知 Webhook 已创建')).not.toBeInTheDocument()
      expect(screen.queryByText('发布判断：PASS')).not.toBeInTheDocument()
    } finally {
      state.receipt.release()
    }
  },
)

it.each(commands)(
  'does not invalidate caches or retry a %s on an ordinary service error',
  async (command) => {
    const state = setup(command, false, 'failure')
    const view = renderCommands(state.client)
    await ready(view)
    let operation!: Promise<void | boolean>
    act(() => {
      operation = runCommand(command, view.result.current)
    })
    await state.receipt.started
    await act(async () => {
      state.receipt.release()
      await operation
    })
    expect(state.applied()).toBe(false)
    expect(state.writes()).toBe(1)
    expect(state.client.isMutating()).toBe(0)
    const error = state.client.getMutationCache().getAll().at(-1)?.state.error
    expect(error).toBeInstanceOf(Error)
    expect(error).not.toBeInstanceOf(SessionBoundaryError)
    for (const key of affectedKeys(command))
      expect(state.client.getQueryState(key)?.isInvalidated).toBe(false)
    expect(view.result.current.reports.revealedSecret).toBeNull()
    expect(view.result.current.release.decisionId).toBeNull()
    expect(screen.getByText(/合成服务暂不可用/)).toBeVisible()
  },
)

it.each(commands)(
  'keeps a successful %s pending until its original active queries refresh',
  async (command) => {
    const state = setup(command, true)
    const view = renderCommands(state.client)
    await ready(view)
    let operation!: Promise<void | boolean>
    act(() => {
      operation = runCommand(command, view.result.current)
    })
    await state.receipt.started
    try {
      await act(async () => state.receipt.release())
      await state.refresh.started
      expect(state.client.isMutating()).toBe(1)
      if (command === 'create-webhook') {
        await waitFor(() => expect(view.result.current.reports.creatingWebhook).toBe(true))
        expect(view.result.current.reports.revealedSecret).toBeNull()
      }
      if (command === 'create-decision')
        await waitFor(() => expect(view.result.current.release.evaluating).toBe(true))
      await act(async () => {
        state.refresh.release()
        await operation
      })
      expect(state.client.isMutating()).toBe(0)
      expect(state.writes()).toBe(1)
      expect(state.client.getMutationCache().getAll().at(-1)?.state.error).toBeNull()
      if (command === 'create-webhook')
        expect(view.result.current.reports.revealedSecret).toBe(secret)
      if (command === 'toggle-webhook')
        expect(view.result.current.reports.webhooks.data?.[0].enabled).toBe(false)
      if (command === 'create-decision') {
        expect(view.result.current.release.decisions.data?.items).toEqual([decision])
        expect(view.result.current.release.latestDecision.data?.items).toEqual([decision])
      }
    } finally {
      state.receipt.release()
      state.refresh.release()
    }
  },
)
