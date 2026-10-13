import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App as AntdApp, ConfigProvider } from 'antd'
import { http, HttpResponse } from 'msw'
import { expect, it, vi } from 'vitest'
import { project } from '../../test/fixtures'
import { server } from '../../test/server'
import { AddApisToFolderDialog } from './ApiFolderActions'

it('selects across pages, shows membership, preserves selection on failure and submits once on retry', async () => {
  const folder = {
    id: 'orders',
    project_id: project.id,
    parent_id: null,
    name: '订单',
    created_at: '',
    updated_at: '',
    created_by_id: 'user-id',
  }
  const calls: unknown[] = []
  const onClose = vi.fn()
  server.use(
    http.get(`/api/v1/projects/${project.id}/folders`, () => HttpResponse.json([folder])),
    http.get(`/api/v1/projects/${project.id}/apis/directory`, ({ request }) => {
      const page = Number(new URL(request.url).searchParams.get('page'))
      return HttpResponse.json({
        items: [
          {
            id: `api-${page}`,
            name: `接口 ${page}`,
            folder_id: null,
            current_version: 1,
            method: 'GET',
            path: `/orders/${page}`,
          },
          {
            id: `in-${page}`,
            name: `已有 ${page}`,
            folder_id: folder.id,
            current_version: 1,
            method: 'GET',
            path: '/already',
          },
        ],
        total: 21,
        page,
        page_size: 20,
      })
    }),
    http.post(`/api/v1/projects/${project.id}/apis/bulk-move`, async ({ request }) => {
      calls.push(await request.json())
      return calls.length === 1
        ? HttpResponse.json({ error: { message: '失败', trace_id: 'trace' } }, { status: 409 })
        : HttpResponse.json({ moved_count: 2, items: [] })
    }),
  )
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <ConfigProvider theme={{ token: { motion: false } }}>
        <AntdApp>
          <AddApisToFolderDialog projectId={project.id} folder={folder} onClose={onClose} />
        </AntdApp>
      </ConfigProvider>
    </QueryClientProvider>,
  )
  const browser = userEvent.setup()
  expect(await screen.findByRole('checkbox', { name: '勾选接口 已有 1' })).toBeDisabled()
  await browser.click(screen.getByRole('checkbox', { name: '勾选接口 接口 1' }))
  await browser.click(screen.getByTitle('2'))
  await browser.click(await screen.findByRole('checkbox', { name: '勾选接口 接口 2' }))
  expect(screen.getByText('已选 2 个，本页 1 个，其他页 1 个')).toBeVisible()
  await browser.click(screen.getByRole('button', { name: '移入分组（2）' }))
  expect(await screen.findByText('移入失败，选择已保留，请刷新核对后重试。')).toBeVisible()
  expect(onClose).not.toHaveBeenCalled()
  await browser.click(screen.getByRole('button', { name: '移入分组（2）' }))
  await waitFor(() => expect(onClose).toHaveBeenCalledOnce())
  expect(calls).toEqual(Array(2).fill({ definition_ids: ['api-1', 'api-2'], folder_id: folder.id }))
})

it('refreshes a cached candidate directory when the shared API namespace is invalidated', async () => {
  const folder = {
    id: 'orders',
    project_id: project.id,
    parent_id: null,
    name: '订单',
    created_at: '',
    updated_at: '',
    created_by_id: 'user-id',
  }
  let name = '旧名称'
  let reads = 0
  server.use(
    http.get(`/api/v1/projects/${project.id}/folders`, () => HttpResponse.json([folder])),
    http.get(`/api/v1/projects/${project.id}/apis/directory`, () => {
      reads += 1
      return HttpResponse.json({
        items: [
          { id: 'api', name, folder_id: null, current_version: 1, method: 'GET', path: '/orders' },
        ],
        total: 1,
        page: 1,
        page_size: 20,
      })
    }),
  )
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 15000 } },
  })
  const view = render(
    <QueryClientProvider client={client}>
      <AntdApp>
        <AddApisToFolderDialog projectId={project.id} folder={folder} onClose={vi.fn()} />
      </AntdApp>
    </QueryClientProvider>,
  )
  expect(await screen.findByText('旧名称')).toBeInTheDocument()
  view.unmount()
  name = '新接口名称'
  await client.invalidateQueries({ queryKey: ['apis', project.id] })
  render(
    <QueryClientProvider client={client}>
      <AntdApp>
        <AddApisToFolderDialog projectId={project.id} folder={folder} onClose={vi.fn()} />
      </AntdApp>
    </QueryClientProvider>,
  )
  expect(await screen.findByText('新接口名称')).toBeInTheDocument()
  expect(reads).toBe(2)
})
