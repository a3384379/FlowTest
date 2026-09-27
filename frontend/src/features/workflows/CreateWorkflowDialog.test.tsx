import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import CreateWorkflowDialog from './CreateWorkflowDialog'

describe('CreateWorkflowDialog', () => {
  it('passes the selected control template into draft creation', async () => {
    const user = userEvent.setup()
    const onCreate = vi.fn(async () => {})
    render(
      <CreateWorkflowDialog
        open
        submitting={false}
        apis={[
          {
            id: '00000000-0000-0000-0000-000000000001',
            project_id: '00000000-0000-0000-0000-000000000002',
            folder_id: null,
            name: '查询接口',
            description: '',
            current_version: 2,
            is_active: true,
          },
        ]}
        onClose={() => {}}
        onCreate={onCreate}
      />,
    )
    await user.type(screen.getByLabelText('名称'), '分页检查')
    await user.click(screen.getByLabelText('起始模板'))
    await user.click(screen.getByText(/分页查询 · page 从 1 到 3/))
    await user.click(screen.getByLabelText('初始 API 节点'))
    await user.click(screen.getByText('查询接口'))
    await user.click(screen.getByRole('button', { name: '创建草稿' }))

    await waitFor(() =>
      expect(onCreate).toHaveBeenCalledWith({
        name: '分页检查',
        description: '',
        apiId: '00000000-0000-0000-0000-000000000001',
        template: 'pagination',
      }),
    )
  })

  it('requires separate submit and query APIs for the asynchronous polling template', async () => {
    const user = userEvent.setup()
    const onCreate = vi.fn(async () => {})
    const query = {
      id: '00000000-0000-0000-0000-000000000001',
      project_id: '00000000-0000-0000-0000-000000000002',
      folder_id: null,
      name: '查询状态',
      description: '',
      current_version: 2,
      is_active: true,
    }
    const submit = { ...query, id: '00000000-0000-0000-0000-000000000003', name: '提交任务' }
    render(
      <CreateWorkflowDialog
        open
        submitting={false}
        apis={[query, submit]}
        onClose={() => {}}
        onCreate={onCreate}
      />,
    )
    await user.type(screen.getByLabelText('名称'), '异步任务')
    await user.click(screen.getByLabelText('起始模板'))
    await user.click(screen.getByText(/异步状态轮询 · 提交一次任务/))
    await user.click(screen.getByLabelText('状态查询 API（GET）'))
    await user.click(screen.getByText('查询状态'))
    await user.click(screen.getByLabelText('任务提交 API（POST）'))
    await user.click(screen.getAllByText('提交任务').at(-1)!)
    await user.click(screen.getByRole('button', { name: '创建草稿' }))
    await waitFor(() =>
      expect(onCreate).toHaveBeenCalledWith({
        name: '异步任务',
        description: '',
        apiId: query.id,
        submitApiId: submit.id,
        template: 'async_poll',
      }),
    )
  })
})
