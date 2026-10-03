import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { App as AntdApp, ConfigProvider } from 'antd'
import { http, HttpResponse } from 'msw'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { apiClient, type Folder } from '../../lib/api'
import { project, user, workflow } from '../../test/fixtures'
import { authenticateTestUser } from '../../test/auth'
import { server } from '../../test/server'
import { createIceTheme } from '../../theme/ice-theme'
import { useAuthStore } from '../auth/auth-store'
import { FolderManagementPanel } from './AssetManagementPanel'

const root = `/api/v1/projects/${project.id}/folders`
const folder: Folder = {
  id: 'folder-root',
  project_id: project.id,
  parent_id: null,
  name: '回归目录',
  created_by_id: user.id,
  created_at: workflow.created_at,
  updated_at: workflow.updated_at,
}
const child = { ...folder, id: 'folder-child', parent_id: folder.id, name: '子目录' }
const grandchild = { ...folder, id: 'folder-grandchild', parent_id: child.id, name: '孙目录' }

beforeEach(() => authenticateTestUser(user))
afterEach(() => {
  useAuthStore.setState({ user: null })
  vi.restoreAllMocks()
})

function showFolders(props: Partial<Parameters<typeof FolderManagementPanel>[0]> = {}) {
  render(
    <ConfigProvider theme={createIceTheme(true)}>
      <AntdApp>
        <QueryClientProvider
          client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
        >
          <FolderManagementPanel projectId={project.id} canEdit {...props} />
        </QueryClientProvider>
      </AntdApp>
    </ConfigProvider>,
  )
}

it('creates a directory in context without reading unrelated environments, secrets or configuration', async () => {
  const reads = vi.spyOn(apiClient, 'get')
  const submitted = vi.fn()
  let folders = [folder]
  server.use(
    http.get(root, () => HttpResponse.json(folders)),
    http.post(root, async ({ request }) => {
      submitted(await request.json())
      const created = { ...folder, id: 'created', name: '新增目录' }
      folders = [...folders, created]
      return HttpResponse.json(created, { status: 201 })
    }),
  )
  showFolders()
  await screen.findByText(folder.name)
  fireEvent.change(screen.getByRole('textbox', { name: '目录名称' }), {
    target: { value: '新增目录' },
  })
  fireEvent.click(screen.getByRole('button', { name: /新建目录/ }))
  expect(await screen.findByText('新增目录', { selector: 'td' })).toBeVisible()
  expect(submitted).toHaveBeenCalledWith({ name: '新增目录', parent_id: null })
  expect(reads.mock.calls.every(([path]) => path === `/projects/${project.id}/folders`)).toBe(true)
})

it('retains the rename form on failure and disallows choosing itself or descendants as its parent', async () => {
  server.use(
    http.get(root, () => HttpResponse.json([folder, child, grandchild])),
    http.patch(root + '/' + folder.id, () =>
      HttpResponse.json(
        { error: { code: 'NAME_EXISTS', message: '目录名称已存在', trace_id: 'folder-trace' } },
        { status: 409 },
      ),
    ),
  )
  showFolders()
  const row = (await screen.findByRole('button', { name: `删除目录 ${folder.name}` })).closest(
    'tr',
  )!
  fireEvent.click(within(row).getByRole('button', { name: '编辑目录' }))
  fireEvent.mouseDown(screen.getByRole('combobox', { name: '父目录' }))
  for (const name of [folder.name, child.name, grandchild.name]) {
    const option = await screen.findByText(name, { selector: '.ant-select-item-option-content' })
    expect(option.closest('.ant-select-item-option')).toHaveAttribute('aria-disabled', 'true')
  }
  fireEvent.change(screen.getByRole('textbox', { name: '目录名称' }), {
    target: { value: '保留失败输入' },
  })
  fireEvent.click(screen.getByRole('button', { name: /保存目录/ }))
  expect(await screen.findByText('目录保存失败')).toBeVisible()
  expect(screen.getByRole('textbox', { name: '目录名称' })).toHaveValue('保留失败输入')
})

it('lists the exact subtree before deletion and cancellation leaves every directory intact', async () => {
  const deletes = vi.spyOn(apiClient, 'delete')
  const removed = vi.fn()
  let folders = [folder, child, grandchild]
  server.use(
    http.get(root, () => HttpResponse.json(folders)),
    http.delete(root + '/' + folder.id, () => {
      folders = []
      return new HttpResponse(null, { status: 204 })
    }),
  )
  showFolders({ onRemoved: removed })
  const row = (await screen.findByRole('button', { name: `删除目录 ${folder.name}` })).closest(
    'tr',
  )!
  fireEvent.click(within(row).getByRole('button', { name: `删除目录 ${folder.name}` }))
  const confirmation = await screen.findByText('删除目录「回归目录」及 2 个子目录？')
  await waitFor(() => expect(confirmation).toBeVisible())
  expect(screen.getByText(/孙目录 · folder-grandchild/)).toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: /取\s*消/ }))
  expect(deletes).not.toHaveBeenCalled()
  expect(removed).not.toHaveBeenCalled()
  fireEvent.click(within(row).getByRole('button', { name: `删除目录 ${folder.name}` }))
  const confirm = await screen.findByRole('button', { name: '确认删除目录' })
  fireEvent.click(confirm)
  await waitFor(() => expect(removed).toHaveBeenCalledWith([folder.id, child.id, grandchild.id]))
  expect(deletes).toHaveBeenCalledExactlyOnceWith(`/projects/${project.id}/folders/${folder.id}`)
})

it('keeps directory management read-only without edit capability', async () => {
  const post = vi.spyOn(apiClient, 'post')
  const deletes = vi.spyOn(apiClient, 'delete')
  server.use(http.get(root, () => HttpResponse.json([folder])))
  showFolders({ canEdit: false })
  expect(await screen.findByText(folder.name, { selector: 'td' })).toBeVisible()
  expect(screen.queryByRole('textbox', { name: '目录名称' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: '编辑目录' })).not.toBeInTheDocument()
  expect(post).not.toHaveBeenCalled()
  expect(deletes).not.toHaveBeenCalled()
})

it('shows a directory read failure and reloads it explicitly', async () => {
  let failure = true
  server.use(
    http.get(root, () =>
      failure
        ? HttpResponse.json(
            {
              error: {
                code: 'READ_FAILED',
                message: '目录读取暂不可用',
                trace_id: 'folder-read-trace',
              },
            },
            { status: 503 },
          )
        : HttpResponse.json([folder]),
    ),
  )
  showFolders()
  expect(await screen.findByText('目录读取失败')).toBeVisible()
  failure = false
  fireEvent.click(screen.getByRole('button', { name: '重新加载目录' }))
  expect(await screen.findByText(folder.name, { selector: 'td' })).toBeVisible()
})
