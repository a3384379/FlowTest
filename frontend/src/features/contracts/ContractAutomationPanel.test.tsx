import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { App as AntdApp } from 'antd'
import { HttpResponse, http } from 'msw'
import { describe, expect, it, vi } from 'vitest'

import type { ContractRun, GeneratedContractCase } from '../../lib/api'
import ProjectTestProvider from '../../test/ProjectTestProvider'
import { project } from '../../test/fixtures'
import { server } from '../../test/server'
import ContractAutomationPanel, {
  CaseReviewDialog,
  ContractRunTable,
  ContractSummary,
  GeneratedCaseTable,
} from './ContractAutomationPanel'

describe('ContractAutomationPanel views', () => {
  it('shows contract diff, coverage, and selects a run', () => {
    const onSelect = vi.fn()
    render(
      <AntdApp>
        <ContractRunTable
          items={[contractRun]}
          loading={false}
          selectedRunId={contractRun.id}
          onSelect={onSelect}
        />
        <ContractSummary run={contractRun} />
      </AntdApp>,
    )

    expect(screen.getByText('+1 / ~1 / -0')).toBeVisible()
    expect(screen.getByText('检测到破坏性变更')).toBeVisible()
    expect(screen.getByText('新增必填请求字段 query.limit')).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: /审核用例/ }))
    expect(onSelect).toHaveBeenCalledWith(contractRun.id)
  })

  it('dispatches generated case review decisions and disables reviewed rows', () => {
    const onAccept = vi.fn()
    const onReject = vi.fn()
    render(
      <AntdApp>
        <GeneratedCaseTable
          items={[generatedCase, { ...generatedCase, id: 'case-2', review_status: 'accepted' }]}
          loading={false}
          onAccept={onAccept}
          onReject={onReject}
        />
      </AntdApp>,
    )

    const pendingRow = screen.getAllByRole('row', { name: /边界用例 GET/ })[0]
    fireEvent.click(within(pendingRow).getByRole('button', { name: /编辑并接受/ }))
    fireEvent.click(within(pendingRow).getByRole('button', { name: /拒绝/ }))
    expect(onAccept).toHaveBeenCalledWith(generatedCase)
    expect(onReject).toHaveBeenCalledWith(generatedCase)
    expect(screen.getAllByRole('button', { name: /编辑并接受/ })[1]).toBeDisabled()
  })

  it('edits JSON before accepting a generated draft', async () => {
    const onSubmit = vi.fn()
    render(
      <AntdApp>
        <CaseReviewDialog
          item={generatedCase}
          submitting={false}
          onClose={vi.fn()}
          onSubmit={onSubmit}
        />
      </AntdApp>,
    )
    const dialog = screen.getByRole('dialog')
    fireEvent.change(within(dialog).getByLabelText('用例名称'), {
      target: { value: '审核后用例' },
    })
    fireEvent.change(within(dialog).getByLabelText('生成定义'), {
      target: { value: '{"confirmed":false,"checks":["schema"]}' },
    })
    fireEvent.change(within(dialog).getByLabelText('审核说明'), {
      target: { value: '人工确认' },
    })
    fireEvent.click(within(dialog).getByRole('button', { name: '接受草稿' }))
    await waitFor(() =>
      expect(onSubmit).toHaveBeenCalledWith({
        name: '审核后用例',
        definition: { confirmed: false, checks: ['schema'] },
        note: '人工确认',
      }),
    )
  })

  it('loads runs, reviews a draft, and uploads a new schema', async () => {
    const requests = { rejected: 0, uploaded: 0 }
    server.use(
      http.get('/api/v1/projects', () =>
        HttpResponse.json({ items: [project], total: 1, page: 1, page_size: 100 }),
      ),
      http.get(`/api/v1/projects/${project.id}/contract-runs`, () =>
        HttpResponse.json({ items: [contractRun], total: 1, page: 1, page_size: 100 }),
      ),
      http.get(
        `/api/v1/projects/${project.id}/contract-runs/${contractRun.id}/generated-cases`,
        () => HttpResponse.json({ items: [generatedCase], total: 1, page: 1, page_size: 100 }),
      ),
      http.post(
        `/api/v1/projects/${project.id}/contract-runs/${contractRun.id}/generated-cases/${generatedCase.id}/reject`,
        () => {
          requests.rejected += 1
          return HttpResponse.json({ ...generatedCase, review_status: 'rejected' })
        },
      ),
      http.post(`/api/v1/projects/${project.id}/contract-runs`, async ({ request }) => {
        const body = await request.formData()
        expect(body.get('source_name')).toBe('next.json')
        requests.uploaded += 1
        return HttpResponse.json(
          { ...contractRun, id: 'run-2', source_name: 'next.json' },
          { status: 201 },
        )
      }),
      http.get(`/api/v1/projects/${project.id}/contract-runs/run-2/generated-cases`, () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 100 }),
      ),
    )
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={queryClient}>
        <AntdApp>
          <ProjectTestProvider section="assets">
            <ContractAutomationPanel />
          </ProjectTestProvider>
        </AntdApp>
      </QueryClientProvider>,
    )

    const runButton = await screen.findByRole('button', { name: /审核用例/ })
    fireEvent.click(runButton)
    const reject = await screen.findByRole('button', { name: /拒绝/ })
    fireEvent.click(reject)
    await waitFor(() => expect(requests.rejected).toBe(1))

    const fileInput = document.querySelector<HTMLInputElement>('input[type="file"]')
    expect(fileInput).not.toBeNull()
    fireEvent.change(fileInput!, {
      target: { files: [new File(['{}'], 'next.json', { type: 'application/json' })] },
    })
    fireEvent.click(screen.getByRole('button', { name: /生成契约用例/ }))
    await waitFor(() => expect(requests.uploaded).toBe(1))
    expect(await screen.findByText('next.json')).toBeVisible()
  })
})

const timestamp = '2026-08-11T00:00:00Z'
const contractRun: ContractRun = {
  id: 'run-1',
  project_id: 'project-1',
  baseline_run_id: null,
  source_name: 'openapi.json',
  source_type: 'openapi3',
  source_sha256: 'a'.repeat(64),
  status: 'completed',
  diff_summary: { added: 1, changed: 1, deleted: 0, unchanged: 2 },
  breaking_changes: [
    {
      code: 'REQUEST_REQUIRED_ADDED',
      severity: 'breaking',
      operation_key: 'operation-1',
      path: 'request.required.query.limit',
      message: '新增必填请求字段 query.limit',
      before: null,
      after: 'query.limit',
    },
  ],
  coverage: {
    operations_total: 4,
    operations_generated: 4,
    operation_coverage_percent: 100,
    request_fields_total: 3,
    response_fields_total: 5,
    schema_fields_total: 8,
    schema_fields_covered: 8,
    schema_coverage_percent: 100,
  },
  generated_case_count: 12,
  provider_service_id: null,
  provider_version: null,
  created_by_id: 'user-1',
  created_at: timestamp,
  updated_at: timestamp,
}

const generatedCase: GeneratedContractCase = {
  id: 'case-1',
  contract_run_id: contractRun.id,
  operation_key: 'operation-1',
  operation_id: 'listUsers',
  method: 'GET',
  path: '/users',
  generation_kind: 'boundary',
  name: '边界用例',
  definition: { confirmed: false, checks: ['schema'] },
  review_status: 'pending',
  review_note: '',
  reviewed_by_id: null,
  reviewed_at: null,
  created_at: timestamp,
  updated_at: timestamp,
}
