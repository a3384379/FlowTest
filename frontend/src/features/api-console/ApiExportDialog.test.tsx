import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ConfigProvider } from 'antd'
import { beforeEach, expect, it, vi } from 'vitest'

import ApiExportDialog from './ApiExportDialog'
import { listApis } from './api-service'
import { listFolders } from '../projects/asset-service'

vi.mock('./api-service', () => ({ listApis: vi.fn() }))
vi.mock('../projects/asset-service', () => ({ listFolders: vi.fn() }))

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(listApis).mockImplementation(async (_project, options) => ({
    items: [],
    total: options?.folder === 'all' ? 120 : 7,
    page: 1,
    page_size: 1,
  }))
  vi.mocked(listFolders).mockResolvedValue([
    {
      id: 'folder',
      project_id: 'project',
      name: '订单',
      parent_id: null,
      created_by_id: 'author',
      created_at: '2026-10-20T00:00:00Z',
      updated_at: '2026-10-20T00:00:00Z',
    },
  ])
})

function setup(selectedIds: string[] = ['page-1', 'page-2'], folder = 'folder', exporting = false) {
  const onExport = vi.fn().mockResolvedValue(undefined)
  const onClose = vi.fn()
  render(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <ApiExportDialog
          projectId="project"
          folder={folder}
          selectedIds={selectedIds}
          exporting={exporting}
          onExport={onExport}
          onClose={onClose}
        />
      </QueryClientProvider>
    </ConfigProvider>,
  )
  return { onExport, onClose }
}

async function chooseScope(label: string) {
  fireEvent.mouseDown(screen.getByRole('combobox', { name: '导出范围' }))
  await userEvent.click(
    await screen.findByText(label, { selector: '.ant-select-item-option-content' }),
  )
}

it('counts the whole project on the server and explicitly excludes filters', async () => {
  const { onExport } = setup()
  await screen.findByText('整个项目 · 当前共 120 个接口')
  expect(listApis).toHaveBeenCalledWith('project', { pageSize: 1, folder: 'all' })
  await userEvent.click(screen.getByRole('button', { name: '导出整个项目' }))
  expect(onExport).toHaveBeenCalledWith({ scope: 'project', format: 'har' })
})

it('exports exactly the current folder or explicit cross-page selection', async () => {
  const { onExport } = setup()
  await screen.findByText('整个项目 · 当前共 120 个接口')
  await chooseScope('当前分组：订单（仅本级，不含子分组）')
  await screen.findByText('当前分组：订单（仅本级，不含子分组） · 当前共 7 个接口')
  await userEvent.click(screen.getByRole('button', { name: '导出指定范围' }))
  expect(onExport).toHaveBeenLastCalledWith({ scope: 'folder', folder_id: 'folder', format: 'har' })
  await chooseScope('已选接口（包含其他页保留的选择）')
  await screen.findByText('已选接口（包含其他页保留的选择） · 当前共 2 个接口')
  await userEvent.click(screen.getByRole('button', { name: '导出指定范围' }))
  expect(onExport).toHaveBeenLastCalledWith({
    scope: 'selected',
    definition_ids: ['page-1', 'page-2'],
    format: 'har',
  })
})

it('uses the unfiled scope and preserves the choice after a download error', async () => {
  const { onExport, onClose } = setup([], 'unfiled')
  onExport.mockRejectedValueOnce(new Error('download-failed'))
  await chooseScope('当前分组：未分组（仅本级，不含子分组）')
  const download = screen.getByRole('button', { name: '导出指定范围' })
  await waitFor(() => expect(download).toBeEnabled())
  await userEvent.click(download)
  await screen.findByText('download-failed')
  expect(onClose).not.toHaveBeenCalled()
  await userEvent.click(download)
  expect(onExport).toHaveBeenLastCalledWith({ scope: 'folder', unfiled: true, format: 'har' })
  expect(onClose).toHaveBeenCalledTimes(1)
})

it('does not enable empty selected export or submit while a download is pending', async () => {
  const { onExport, onClose } = setup([], 'all', true)
  await screen.findByText('整个项目 · 当前共 120 个接口')
  await userEvent.click(screen.getByRole('button', { name: '导出整个项目' }))
  expect(onExport).not.toHaveBeenCalled()
  expect(screen.getByRole('button', { name: '取消' })).toBeDisabled()
  expect(onClose).not.toHaveBeenCalled()
})

it('disables unavailable scopes and blocks an oversized explicit selection', async () => {
  const { onExport } = setup(
    Array.from({ length: 1001 }, (_, i) => `api-${i}`),
    'all',
  )
  fireEvent.mouseDown(screen.getByRole('combobox', { name: '导出范围' }))
  const folder = await screen.findByText('当前分组：未选择分组（仅本级，不含子分组）', {
    selector: '.ant-select-item-option-content',
  })
  expect(folder.closest('.ant-select-item-option')).toHaveClass('ant-select-item-option-disabled')
  await userEvent.click(
    screen.getByText('已选接口（包含其他页保留的选择）', {
      selector: '.ant-select-item-option-content',
    }),
  )
  expect(screen.getByRole('button', { name: '导出指定范围' })).toBeDisabled()
  expect(screen.getByRole('alert')).toHaveTextContent('1 至 1000')
  expect(onExport).not.toHaveBeenCalled()
})
