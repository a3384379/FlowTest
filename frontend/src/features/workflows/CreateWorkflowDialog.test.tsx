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
})
