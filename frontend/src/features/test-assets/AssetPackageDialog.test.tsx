import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { App as AntdApp, ConfigProvider } from 'antd'
import { http, HttpResponse } from 'msw'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { apiClient } from '../../lib/api'
import { authenticateTestUser } from '../../test/auth'
import { environment, project, user, workflow, workflowVersion } from '../../test/fixtures'
import { server } from '../../test/server'
import { createIceTheme } from '../../theme/ice-theme'
import { useAuthStore } from '../auth/auth-store'
import AssetPackageDialog from './AssetPackageDialog'
import {
  nativePackage,
  packageFile,
  packagePreview,
  packageResult,
} from './asset-package.test-fixtures'

const root = `/api/v1/projects/${project.id}/test-assets/import`
beforeEach(() => {
  authenticateTestUser(user)
  server.use(
    http.post(root + '/preview', () => HttpResponse.json(packagePreview)),
    http.get(`/api/v1/projects/${project.id}/workflows/${workflow.id}/versions`, () =>
      HttpResponse.json([{ ...workflowVersion, version: 1 }]),
    ),
  )
})
afterEach(() => {
  useAuthStore.setState({ user: null })
  vi.restoreAllMocks()
})

async function showImport(canEdit = true) {
  const onClose = vi.fn()
  const onImported = vi.fn()
  render(
    <ConfigProvider theme={createIceTheme(true)}>
      <AntdApp>
        <QueryClientProvider
          client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
        >
          <AssetPackageDialog
            projectId={project.id}
            canEdit={canEdit}
            resources={{ workflows: [workflow], environments: [environment], folders: [] }}
            onClose={onClose}
            onImported={onImported}
          />
        </QueryClientProvider>
      </AntdApp>
    </ConfigProvider>,
  )
  await waitFor(() => expect(screen.getByRole('dialog')).toBeVisible())
  return { onClose, onImported }
}

async function loadFile() {
  fireEvent.change(screen.getByLabelText('原生测试资产文件'), {
    target: { files: [packageFile()] },
  })
  await screen.findByText('预览通过，请核对下方范围')
  await waitFor(() => expect(screen.getByRole('checkbox')).toBeEnabled())
}

it('shows the exact assets and fixed versions, and cancellation performs no import', async () => {
  const imported = vi.fn()
  server.use(
    http.post(root + '/apply', () => {
      imported()
      return HttpResponse.json(packageResult)
    }),
  )
  const { onClose } = await showImport()
  await loadFile()
  expect(screen.getByText(/共 1 个用例、1 个套件/)).toBeVisible()
  expect(screen.getAllByText('原 v1 → v1（新增）')).toHaveLength(2)
  expect(screen.getByRole('button', { name: '确认导入' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: /取\s*消/ }))
  expect(onClose).toHaveBeenCalledOnce()
  expect(imported).not.toHaveBeenCalled()
})

it('requires an explicit review confirmation and submits the current preview fingerprint', async () => {
  const submitted = vi.fn()
  server.use(
    http.post(root + '/apply', async ({ request }) => {
      submitted(await request.json())
      return HttpResponse.json(packageResult)
    }),
  )
  const { onImported } = await showImport()
  await loadFile()
  expect(submitted).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('checkbox'))
  fireEvent.click(screen.getByRole('button', { name: '确认导入' }))
  await waitFor(() => expect(onImported).toHaveBeenCalledExactlyOnceWith(packageResult))
  expect(submitted).toHaveBeenCalledExactlyOnceWith({
    package: nativePackage,
    choices: [],
    bindings: {},
    expected_preview_fingerprint: packagePreview.fingerprint,
  })
})

it('invalidates the reviewed scope whenever the target name or binding changes', async () => {
  const writes = vi.spyOn(apiClient, 'post')
  await showImport()
  await loadFile()
  fireEvent.click(screen.getByRole('checkbox'))
  expect(screen.getByRole('button', { name: '确认导入' })).toBeEnabled()
  fireEvent.change(screen.getByRole('textbox', { name: '包用例目标名称' }), {
    target: { value: '另存用例' },
  })
  expect(screen.getByRole('button', { name: '确认导入' })).toBeDisabled()
  expect(screen.queryByText('预览通过，请核对下方范围')).not.toBeInTheDocument()
  expect(writes.mock.calls.every(([path]) => String(path).endsWith('/preview'))).toBe(true)
  fireEvent.click(screen.getByRole('button', { name: '重新预览导入' }))
  await screen.findByText('预览通过，请核对下方范围')
  expect(screen.getByRole('checkbox')).not.toBeChecked()
})

it('retains the file and chosen target after an obsolete preview is rejected', async () => {
  server.use(
    http.post(root + '/apply', () =>
      HttpResponse.json(
        {
          error: {
            code: 'TEST_ASSET_PACKAGE_PREVIEW_STALE',
            message: '资产已变化，请重新预览',
            trace_id: 'package-stale',
          },
        },
        { status: 409 },
      ),
    ),
  )
  const { onImported } = await showImport()
  await loadFile()
  fireEvent.click(screen.getByRole('checkbox'))
  fireEvent.click(screen.getByRole('button', { name: '确认导入' }))
  expect(await screen.findByText('导入未完成')).toBeVisible()
  expect(screen.getByRole('textbox', { name: '包用例目标名称' })).toHaveValue('包用例')
  expect(screen.getByRole('button', { name: '确认导入' })).toBeDisabled()
  expect(screen.getByRole('button', { name: '重新预览导入' })).toBeEnabled()
  expect(onImported).not.toHaveBeenCalled()
})

it('keeps unresolved references blocked and exposes the binding problem', async () => {
  server.use(
    http.post(root + '/preview', () =>
      HttpResponse.json({
        ...packagePreview,
        can_apply: false,
        dependencies: [
          {
            ...packagePreview.dependencies[0],
            target_id: null,
            target_name: null,
            problems: ['目标流程不可用，请选择固定版本'],
          },
        ],
      }),
    ),
  )
  await showImport()
  fireEvent.change(screen.getByLabelText('原生测试资产文件'), {
    target: { files: [packageFile()] },
  })
  expect(await screen.findByText('存在冲突或缺失绑定，当前不能导入')).toBeVisible()
  expect(screen.getByText(/目标流程不可用，请选择固定版本/)).toBeVisible()
  expect(screen.getByRole('checkbox')).toBeDisabled()
  expect(screen.getByRole('button', { name: '确认导入' })).toBeDisabled()
})

it('does not upload or apply a package without edit permission', async () => {
  const writes = vi.spyOn(apiClient, 'post')
  await showImport(false)
  expect(screen.getByLabelText('原生测试资产文件')).toBeDisabled()
  expect(screen.getByRole('button', { name: '确认导入' })).toBeDisabled()
  expect(writes).not.toHaveBeenCalled()
})
