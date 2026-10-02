import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { App as AntdApp } from 'antd'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import type { CreatedTestPlan, TestPlanRun } from '../../lib/api'
import { runTestPlan } from '../task-plans/task-plan-service'
import { createAssetPlan } from './asset-workspace-service'
import AssetPlanDialog from './AssetPlanDialog'

vi.mock('./asset-workspace-service')
vi.mock('../task-plans/task-plan-service')

const targets = [{ kind: 'case' as const, id: 'case-1', name: '订单校验', version: 1 }]
const plan = {
  id: 'plan-1',
  name: '固定版本回归',
  webhook_secret: 'once-only-secret',
} as CreatedTestPlan

beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(createAssetPlan).mockResolvedValue(plan)
  vi.mocked(runTestPlan).mockResolvedValue({ id: 'run-1' } as TestPlanRun)
})

function renderDialog(execute: boolean) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <MemoryRouter>
      <AntdApp>
        <QueryClientProvider client={client}>
          <AssetPlanDialog
            projectId="project-1"
            targets={targets}
            execute={execute}
            onClose={vi.fn()}
          />
        </QueryClientProvider>
      </AntdApp>
    </MemoryRouter>,
  )
  fireEvent.change(screen.getByLabelText('计划名称'), { target: { value: '固定版本回归' } })
}

it('does not write during review and creates a frozen plan without automatically running it', async () => {
  renderDialog(false)
  expect(createAssetPlan).not.toHaveBeenCalled()
  expect(runTestPlan).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: '创建计划' }))
  await screen.findByText('测试计划已创建')
  expect(createAssetPlan).toHaveBeenCalledWith('project-1', '固定版本回归', targets)
  expect(runTestPlan).not.toHaveBeenCalled()
  expect(screen.queryByText(plan.webhook_secret)).not.toBeInTheDocument()
  expect(screen.getByRole('link', { name: `查看 ${plan.name}` })).toHaveAttribute(
    'href',
    '/projects/project-1/tasks?focus=plan-1',
  )
})

it('retries enqueue on the same created plan and idempotency key instead of creating duplicate plans', async () => {
  vi.mocked(runTestPlan).mockRejectedValueOnce(new Error('队列暂不可用'))
  renderDialog(true)
  fireEvent.click(screen.getByRole('button', { name: '创建计划并执行' }))
  await screen.findByText('计划已创建，执行入队失败')
  fireEvent.click(screen.getByRole('button', { name: '重试执行' }))
  await screen.findByText('计划已进入执行队列')
  expect(createAssetPlan).toHaveBeenCalledTimes(1)
  expect(runTestPlan).toHaveBeenCalledTimes(2)
  expect(vi.mocked(runTestPlan).mock.calls[0]).toEqual(vi.mocked(runTestPlan).mock.calls[1])
  expect(runTestPlan).toHaveBeenCalledWith('project-1', plan.id, expect.any(String))
})

it('keeps a failed create reviewable and never enqueues it', async () => {
  vi.mocked(createAssetPlan).mockRejectedValueOnce(new Error('版本不存在'))
  renderDialog(true)
  fireEvent.click(screen.getByRole('button', { name: '创建计划并执行' }))
  await screen.findByText('创建计划失败')
  expect(runTestPlan).not.toHaveBeenCalled()
  await waitFor(() => expect(screen.getByRole('button', { name: '创建计划并执行' })).toBeEnabled())
  expect(screen.getByLabelText('计划名称')).toHaveValue('固定版本回归')
})
