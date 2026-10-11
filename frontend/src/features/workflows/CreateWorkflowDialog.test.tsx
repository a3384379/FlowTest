import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { apiDefinition, project } from '../../test/fixtures'
import { server } from '../../test/server'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import CreateWorkflowDialog from './CreateWorkflowDialog'

describe('CreateWorkflowDialog', () => {
  it.each([
    { state: 'outside the loaded catalog', known: [] },
    { state: 'newer than the loaded catalog', known: [apiDefinition] },
  ])('creates a template with the displayed API version $state', async ({ known }) => {
    const onCreate = vi.fn(async () => {})
    server.use(
      http.get(`/api/v1/projects/${project.id}/apis`, () =>
        HttpResponse.json({
          items: [{ ...apiDefinition, name: '目录之外的接口', current_version: 7 }],
          total: 1,
          page: 1,
          page_size: 20,
        }),
      ),
    )
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <CreateWorkflowDialog
          projectId={project.id}
          open
          submitting={false}
          apis={known}
          onClose={() => {}}
          onCreate={onCreate}
        />
      </QueryClientProvider>,
    )
    const browser = userEvent.setup()
    await browser.type(screen.getByLabelText('名称'), '远端接口流程')
    await browser.click(screen.getByRole('combobox', { name: '初始 API 节点' }))

    await browser.click(
      await screen.findByText(/目录之外的接口/, {
        selector: '.ant-select-item-option-content .api-resource-option-name',
      }),
    )
    expect(screen.getByText('v7', { selector: '.ant-select-content .ant-tag' })).toHaveTextContent(
      'v7',
    )
    await browser.click(screen.getByRole('button', { name: '创建草稿' }))
    await waitFor(() =>
      expect(onCreate).toHaveBeenCalledWith(
        expect.objectContaining({ apiId: apiDefinition.id, apiVersion: 7 }),
      ),
    )
  })

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
        apiVersion: 2,
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
        apiVersion: 2,
        submitApiId: submit.id,
        submitApiVersion: 2,
        template: 'async_poll',
      }),
    )
  })

  it('marks the cleanup template as unfinished until a real cleanup step is configured', async () => {
    const user = userEvent.setup()
    render(
      <CreateWorkflowDialog
        open
        submitting={false}
        apis={[]}
        onClose={() => {}}
        onCreate={async () => {}}
      />,
    )
    await user.click(screen.getByLabelText('起始模板'))
    await user.click(screen.getByText(/请求与清理（需配置）/))
    expect(screen.getByText(/不会清理外部资源/)).toBeInTheDocument()
  })
})
