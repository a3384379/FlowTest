import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import { App as AntdApp, ConfigProvider } from 'antd'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { listImpactRuns } from '../impact/impact-service'
import { useProjectContext } from '../projects/use-project-context'
import { listReleaseRisks } from '../quality/quality-service'
import {
  createAIChangeSet,
  getAIChangeSet,
  listAIChangeSets,
  reviewAIChangeItem,
  type AIChangeSetDetail,
  type AIChangeSetSummary,
} from './ai-change-set-service'
import { useAIChangeSets } from './use-ai-change-sets'

vi.mock('../impact/impact-service')
vi.mock('../projects/use-project-context')
vi.mock('../quality/quality-service')
vi.mock('./ai-change-set-service')

let projectId = 'project-1'

describe('useAIChangeSets', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    projectId = 'project-1'
    vi.mocked(useProjectContext).mockImplementation(() => ({ projectId }) as never)
    vi.mocked(listAIChangeSets).mockImplementation(async (currentProjectId) => {
      const item = summary(`change-set-${currentProjectId}`, currentProjectId)
      return { items: [item], total: 1, page: 1, page_size: 100 }
    })
    vi.mocked(getAIChangeSet).mockImplementation(async (changeSetId) =>
      detail(changeSetId, changeSetId.replace('change-set-', '')),
    )
    vi.mocked(listImpactRuns).mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      page_size: 20,
    })
    vi.mocked(listReleaseRisks).mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      page_size: 100,
    })
    vi.mocked(createAIChangeSet).mockResolvedValue(summary('created', projectId))
    vi.mocked(reviewAIChangeItem).mockResolvedValue({} as never)
  })

  it('does not retain or fetch the previous project selection after switching projects', async () => {
    const rendered = renderChangeSetsHook()
    await waitFor(() => expect(rendered.result.current.activeId).toBe('change-set-project-1'))
    await waitFor(() => expect(rendered.result.current.detail.data?.project_id).toBe('project-1'))

    act(() => rendered.result.current.select('change-set-project-1'))
    vi.mocked(getAIChangeSet).mockClear()
    projectId = 'project-2'
    rendered.rerender()

    expect(rendered.result.current.activeId).not.toBe('change-set-project-1')
    await waitFor(() => expect(rendered.result.current.activeId).toBe('change-set-project-2'))
    await waitFor(() => expect(rendered.result.current.detail.data?.project_id).toBe('project-2'))
    expect(getAIChangeSet).not.toHaveBeenCalledWith('change-set-project-1')
    expect(getAIChangeSet).toHaveBeenCalledWith('change-set-project-2')
  })
})

function renderChangeSetsHook() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return renderHook(() => useAIChangeSets(), {
    wrapper: ({ children }: { children: ReactNode }) => (
      <ConfigProvider theme={{ token: { motion: false } }}>
        <AntdApp>
          <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
        </AntdApp>
      </ConfigProvider>
    ),
  })
}

function summary(id: string, currentProjectId: string): AIChangeSetSummary {
  return {
    id,
    project_id: currentProjectId,
    impact_run_id: `impact-${currentProjectId}`,
    release_risk_id: `risk-${currentProjectId}`,
    ai_job_id: `job-${currentProjectId}`,
    title: `${currentProjectId} 变更集`,
    status: 'draft',
    source_fingerprint: 'a'.repeat(64),
    created_by_id: 'user-1',
    created_at: '2026-08-13T01:00:00Z',
    updated_at: '2026-08-13T01:00:00Z',
  }
}

function detail(id: string, currentProjectId: string): AIChangeSetDetail {
  return { ...summary(id, currentProjectId), source_snapshot: {}, items: [] }
}
