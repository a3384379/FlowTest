import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import { App } from 'antd'
import type { ReactNode } from 'react'
import { http, HttpResponse } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import * as services from './test-engineering-service'
import type { TestEngineeringProposal } from './test-engineering-service'

import { server } from '../../test/server'
import { useTestEngineering } from './use-test-engineering'

const scope = vi.hoisted(() => ({ projectId: 'first-project' }))
vi.mock('../projects/use-project-context', () => ({ useProjectContext: () => scope }))

describe('test engineering project isolation', () => {
  it('discards a delayed preview from the previous project and never creates a proposal automatically', async () => {
    let releasePreview: (() => void) | undefined
    const ready = new Promise<void>((resolve) => {
      releasePreview = resolve
    })
    let started = false
    let proposals = 0
    server.use(
      http.get('/api/v1/projects/:projectId/apis', () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 100 }),
      ),
      http.get('/api/v1/projects/:projectId/environments', () => HttpResponse.json([])),
      http.post('/api/v1/projects/first-project/test-engineering/generate', async () => {
        started = true
        await ready
        return HttpResponse.json({
          fingerprint: 'old-preview',
          persisted: false,
          design: {},
          contract_completeness: 'complete',
          contract_fingerprint: 'old-contract',
        })
      }),
      http.post('/api/v1/projects/:projectId/test-engineering/proposals', () => {
        proposals += 1
        return HttpResponse.json({})
      }),
    )
    scope.projectId = 'first-project'
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    const { result, rerender } = renderHook(() => useTestEngineering(), {
      wrapper: ({ children }: { children: ReactNode }) => (
        <App>
          <QueryClientProvider client={client}>{children}</QueryClientProvider>
        </App>
      ),
    })
    let pending: Promise<boolean> | undefined
    act(() => {
      pending = result.current.generateDesign('old-api')
    })
    await waitFor(() => expect(started).toBe(true))
    scope.projectId = 'second-project'
    rerender()
    await act(async () => {
      releasePreview!()
      await pending
    })
    expect(result.current.projectId).toBe('second-project')
    expect(result.current.generation).toBeNull()
    expect(result.current.proposal).toBeNull()
    expect(proposals).toBe(0)
  })
})

const proposal: TestEngineeringProposal = {
  change_set_id: 'saved-proposal',
  status: 'accepted',
  review_status: 'accepted',
  fingerprint: 'saved-fingerprint',
  scenario_ids: [],
  applied: false,
  contract_completeness: 'complete',
  contract_fingerprint: 'c'.repeat(64),
  design: {
    schema_version: '1.0',
    intent: {
      key: 'orders',
      objective: 'owned design',
      acceptance_criteria: [],
      evidence_refs: [],
      confidence: 1,
      deterministic: true,
    },
    scenarios: [],
    oracles: [],
    coverage: { entries: [] },
    evidence_refs: [],
    warnings: [],
    confidence: 1,
    review_requirements: [],
  },
}
const receipt = {
  change_set_id: proposal.change_set_id,
  test_design_id: 'saved-design',
  workflow_ids: ['original-workflow'],
  test_case_ids: ['original-case'],
  assets: [],
  references_complete: true,
}

function designHarness() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const rendered = renderHook(({ id }: { id: string | null }) => useTestEngineering(id), {
    initialProps: { id: proposal.change_set_id as string | null },
    wrapper: ({ children }: { children: ReactNode }) => (
      <App>
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      </App>
    ),
  })
  return { ...rendered, client }
}

function installDesignReads() {
  server.use(
    http.get('/api/v1/projects/:projectId/apis', () =>
      HttpResponse.json({ items: [], total: 0, page: 1, page_size: 100 }),
    ),
    http.get('/api/v1/projects/:projectId/environments', () => HttpResponse.json([])),
    http.get('/api/v1/projects/:projectId/test-engineering/proposals/:id', ({ params }) =>
      params.projectId === 'first-project' && params.id === proposal.change_set_id
        ? HttpResponse.json(proposal)
        : HttpResponse.json(
            {
              error: {
                code: 'NOT_FOUND',
                message: '合成记录不在当前范围',
                trace_id: 'scope-not-found',
              },
            },
            { status: 404 },
          ),
    ),
  )
}

describe('test design materialization ownership', () => {
  beforeEach(() => {
    scope.projectId = 'first-project'
    installDesignReads()
  })
  afterEach(() => vi.restoreAllMocks())
  it('does not mark a failed Apply as complete and keeps the exact successful receipt and asset caches', async () => {
    let requests = 0
    server.use(
      http.post(
        '/api/v1/projects/first-project/test-engineering/proposals/saved-proposal/apply',
        () => {
          requests++
          return requests === 1
            ? HttpResponse.json(
                {
                  error: {
                    code: 'UNAVAILABLE',
                    message: '合成生成暂不可用',
                    trace_id: 'apply-failure',
                  },
                },
                { status: 503 },
              )
            : HttpResponse.json(receipt)
        },
      ),
    )
    const { result, client } = designHarness()
    client.setQueryData(['workflows', 'first-project'], ['previous-workflow'])
    client.setQueryData(['test-cases', 'first-project'], ['previous-case'])
    await waitFor(() =>
      expect(
        result.current.canEdit && result.current.proposal?.change_set_id === proposal.change_set_id,
      ).toBe(true),
    )
    expect(requests).toBe(0)
    await act(async () => expect(await result.current.applyProposal()).toBe(false))
    expect(result.current.proposal?.applied).toBe(false)
    expect(result.current.proposal?.materialization).toBeUndefined()
    await act(async () => expect(await result.current.applyProposal()).toBe(true))
    expect(result.current.proposal?.materialization).toEqual(receipt)
    expect(
      client.getQueryData(['test-engineering-proposal', 'first-project', proposal.change_set_id]),
    ).toMatchObject({ applied: true, materialization: receipt })
    expect(client.getQueryState(['workflows', 'first-project'])?.isInvalidated).toBe(true)
    expect(client.getQueryState(['test-cases', 'first-project'])?.isInvalidated).toBe(true)
    expect(requests).toBe(2)
  })

  it.each(['project-success', 'project-error', 'proposal-success', 'proposal-error'])(
    'ignores a late Apply after %s context changes',
    async (mode) => {
      let complete!: (value: typeof receipt) => void
      let fail!: (error: Error) => void
      const response = new Promise<typeof receipt>((resolve, reject) => {
        complete = resolve
        fail = reject
      })
      const applied = vi.spyOn(services, 'applyTestDesignProposal').mockReturnValue(response)
      const { result, rerender } = designHarness()
      await waitFor(() =>
        expect(
          result.current.canEdit &&
            result.current.proposal?.change_set_id === proposal.change_set_id,
        ).toBe(true),
      )
      let pending!: Promise<boolean>
      act(() => {
        pending = result.current.applyProposal()
      })
      await waitFor(() =>
        expect(applied).toHaveBeenCalledWith('first-project', proposal.change_set_id),
      )
      if (mode.startsWith('project')) scope.projectId = 'second-project'
      rerender({ id: mode.startsWith('proposal') ? 'other-proposal' : proposal.change_set_id })
      await act(async () => {
        if (mode.endsWith('success')) complete(receipt)
        else fail(new Error('obsolete-design-error'))
        expect(await pending).toBe(false)
      })
      expect(result.current.proposal).toBeNull()
      expect(result.current.error).toBeNull()
      expect(screen.queryByText('obsolete-design-error')).not.toBeInTheDocument()
      expect(screen.queryByText(/已生成草稿：/)).not.toBeInTheDocument()
    },
  )

  it('starts a new preview from a saved proposal and keeps it when the old proposal URL is cleared', async () => {
    server.use(
      http.post('/api/v1/projects/first-project/test-engineering/generate', () =>
        HttpResponse.json({
          fingerprint: 'new-preview',
          persisted: false,
          design: proposal.design,
          contract_completeness: 'complete',
          contract_fingerprint: 'new-contract',
        }),
      ),
    )
    const { result, rerender } = designHarness()
    await waitFor(() => expect(result.current.proposal?.change_set_id).toBe(proposal.change_set_id))
    await act(async () => expect(await result.current.generateDesign('selected-api')).toBe(true))
    expect(result.current.proposal).toBeNull()
    expect(result.current.generation?.fingerprint).toBe('new-preview')
    rerender({ id: null })
    expect(result.current.proposal).toBeNull()
    expect(result.current.generation?.fingerprint).toBe('new-preview')
  })
})
