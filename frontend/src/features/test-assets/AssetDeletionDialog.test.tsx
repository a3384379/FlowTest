import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { App as AntdApp, ConfigProvider } from 'antd'
import { createIceTheme } from '../../theme/ice-theme'
import { http, HttpResponse } from 'msw'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { apiClient } from '../../lib/api'
import { project, user } from '../../test/fixtures'
import { authenticateTestUser } from '../../test/auth'
import { server } from '../../test/server'
import { useAuthStore } from '../auth/auth-store'
import AssetDeletionDialog from './AssetDeletionDialog'
import { deleteTestAssets, type AssetDeletionPreview } from './asset-deletion-service'

const root = `/api/v1/projects/${project.id}/test-cases`
const target = {
  id: 'asset-1',
  expected_name: '准备移除的用例',
  expected_draft_fingerprint: 'a'.repeat(64),
  expected_version: 2,
  expected_updated_at: '2026-10-03T00:00:00Z',
}
const preview: AssetDeletionPreview = {
  targets: [{ asset: target, archived: false, references: [] }],
}

beforeEach(() => authenticateTestUser(user))
afterEach(() => {
  useAuthStore.setState({ user: null })
  vi.restoreAllMocks()
})

async function showDeletion(props: Partial<Parameters<typeof AssetDeletionDialog>[0]> = {}) {
  const onClose = vi.fn()
  const onDeleted = vi.fn()
  render(
    <ConfigProvider theme={createIceTheme(true)}>
      <AntdApp>
        <QueryClientProvider
          client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
        >
          <AssetDeletionDialog
            projectId={project.id}
            kind="case"
            ids={[target.id]}
            canEdit
            onClose={onClose}
            onDeleted={onDeleted}
            {...props}
          />
        </QueryClientProvider>
      </AntdApp>
    </ConfigProvider>,
  )
  await waitFor(() => expect(screen.getByRole('dialog')).toBeVisible())
  return { onClose, onDeleted }
}

it('previews the exact asset and cancellation performs no deletion', async () => {
  const writes = vi.spyOn(apiClient, 'delete')
  server.use(http.post(root + '/deletion-preview', () => HttpResponse.json(preview)))
  const { onClose, onDeleted } = await showDeletion()
  expect(await screen.findByText(target.expected_name)).toBeVisible()
  expect(screen.getByText(target.id)).toBeVisible()
  expect(screen.getByText('已发布 v2')).toBeVisible()
  await waitFor(() => expect(screen.getByRole('button', { name: '确认删除 1 项' })).toBeEnabled())
  fireEvent.click(screen.getByRole('button', { name: /取\s*消/ }))
  expect(onClose).toHaveBeenCalledOnce()
  expect(onDeleted).not.toHaveBeenCalled()
  expect(writes).not.toHaveBeenCalled()
})

it('submits the frozen preview only after explicit confirmation and verifies returned scope', async () => {
  const submitted = vi.fn()
  server.use(
    http.post(root + '/deletion-preview', () => HttpResponse.json(preview)),
    http.delete(root + '/' + target.id, async ({ request }) => {
      submitted(await request.json())
      return HttpResponse.json({ archived_ids: [target.id], historical_data_retained: true })
    }),
  )
  const { onDeleted } = await showDeletion()
  await screen.findByText(target.expected_name)
  expect(submitted).not.toHaveBeenCalled()
  const confirm = screen.getByRole('button', { name: '确认删除 1 项' })
  await waitFor(() => expect(confirm).toBeEnabled())
  fireEvent.click(confirm)
  await waitFor(() => expect(onDeleted).toHaveBeenCalledWith([target.id]))
  expect(submitted).toHaveBeenCalledExactlyOnceWith(target)
})

it('blocks the entire batch when any selected asset still has a frozen reference', async () => {
  const writes = vi.spyOn(apiClient, 'delete')
  server.use(
    http.post(root + '/deletion-preview', () =>
      HttpResponse.json({
        targets: [
          ...preview.targets,
          {
            asset: { ...target, id: 'asset-2', expected_name: '被套件引用的用例' },
            archived: false,
            references: [{ kind: 'test_suite', id: 'suite-1', name: '发布回归套件', version: 3 }],
          },
        ],
      }),
    ),
  )
  await showDeletion({ ids: [target.id, 'asset-2'] })
  expect(await screen.findByText('选中资产仍有引用，整批不能删除')).toBeVisible()
  expect(screen.getByText('测试套件：发布回归套件 · v3')).toBeVisible()
  const confirm = screen.getByRole('button', { name: '确认删除 2 项' })
  expect(confirm).toBeDisabled()
  fireEvent.click(confirm)
  expect(writes).not.toHaveBeenCalled()
})

it('blocks an unexpected preview range', async () => {
  const reads = vi.fn()
  server.use(
    http.post(root + '/deletion-preview', () => {
      reads()
      return HttpResponse.json(preview)
    }),
  )
  await showDeletion({ ids: ['other-asset'] })
  expect(await screen.findByText('预览范围与选择不一致，请刷新预览')).toBeVisible()
  expect(screen.getByRole('button', { name: '确认删除 1 项' })).toBeDisabled()
})

it('does not request a deletion preview or allow confirmation without edit capability', async () => {
  const reads = vi.spyOn(apiClient, 'post')
  await showDeletion({ canEdit: false })
  expect(screen.getByText('当前成员没有资产编辑权限')).toBeVisible()
  expect(screen.getByRole('button', { name: '确认删除 1 项' })).toBeDisabled()
  expect(screen.getByRole('button', { name: '刷新删除预览' })).toBeDisabled()
  expect(reads).not.toHaveBeenCalled()
})

it('keeps the confirmation open on a stale asset and requires a refreshed preview', async () => {
  server.use(
    http.post(root + '/deletion-preview', () => HttpResponse.json(preview)),
    http.delete(root + '/' + target.id, () =>
      HttpResponse.json(
        {
          error: {
            code: 'TEST_ASSET_DELETE_STALE',
            message: '测试资产已变化, 请重新查看删除预览',
            trace_id: 'delete-trace',
          },
        },
        { status: 409 },
      ),
    ),
  )
  const { onDeleted } = await showDeletion()
  await screen.findByText(target.expected_name)
  const confirm = screen.getByRole('button', { name: '确认删除 1 项' })
  await waitFor(() => expect(confirm).toBeEnabled())
  fireEvent.click(confirm)
  await waitFor(() => expect(screen.getByText('删除未完成')).toBeVisible())
  expect(screen.getByText(/测试资产已变化/)).toBeVisible()
  expect(onDeleted).not.toHaveBeenCalled()
  await waitFor(() => expect(confirm).toBeDisabled())
})

it('uses one atomic bulk request and rejects a mismatched successful response', async () => {
  const post = vi
    .spyOn(apiClient, 'post')
    .mockResolvedValue({ data: { archived_ids: ['unselected'], historical_data_retained: true } })
  const targets = [target, { ...target, id: 'asset-2' }]
  await expect(deleteTestAssets(project.id, 'suite', targets)).rejects.toThrow(
    '删除结果与确认范围不一致',
  )
  expect(post).toHaveBeenCalledExactlyOnceWith(`/projects/${project.id}/test-suites/bulk-delete`, {
    assets: targets,
  })
})
