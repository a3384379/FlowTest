import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App, ConfigProvider } from 'antd'
import { createMemoryRouter, Link, RouterProvider } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import EnvironmentTemplateDialog from './EnvironmentTemplateDialog'
import { defaultEnvironmentManifest } from './environment-template-manifest'
import type { EnvironmentTemplateInput, EnvironmentTemplateVersion } from './environment-service'

function renderDialog(props: Partial<React.ComponentProps<typeof EnvironmentTemplateDialog>> = {}) {
  const submit = vi
    .fn<(input: EnvironmentTemplateInput) => Promise<boolean>>()
    .mockResolvedValue(false)
  const close = vi.fn()
  const router = createMemoryRouter([
    {
      path: '/',
      element: (
        <>
          <Link to="/other">离开环境页</Link>
          <EnvironmentTemplateDialog
            submitting={false}
            onClose={close}
            onSubmit={submit}
            {...props}
          />
        </>
      ),
    },
    { path: '/other', element: <div>其他页面</div> },
  ])
  render(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <App>
        <RouterProvider router={router} />
      </App>
    </ConfigProvider>,
  )
  return { submit, close, router }
}
function serviceCard(number: number) {
  return within(
    screen.getByText(`服务 ${number}`, { exact: true }).closest('.ant-card') as HTMLElement,
  )
}
function baseTemplate(): EnvironmentTemplateVersion {
  return {
    id: 'old-v1',
    template_id: 'template',
    template_key: 'platform.web',
    display_name: '原始模板',
    description: '原始描述',
    status: 'active',
    version: 1,
    manifest: defaultEnvironmentManifest(),
    manifest_sha256: 'a'.repeat(64),
    signature: 'b'.repeat(64),
    signature_algorithm: 'hmac-sha256-v1',
    signed_by_id: 'admin',
    created_at: '2026-10-21T00:00:00Z',
  }
}
describe('EnvironmentTemplateDialog', () => {
  it('edits two services, dependencies and seeds, preserves all fields after a rejected save, and shows fixed-version differences', async () => {
    const base = baseTemplate()
    const { submit, close } = renderDialog({ base })
    const browser = userEvent.setup()
    await browser.click(screen.getByRole('button', { name: '添加服务（最多5个）' }))
    const second = serviceCard(2)
    fireEvent.change(second.getByLabelText('服务名称'), { target: { value: 'api' } })
    await browser.click(second.getByLabelText('依赖服务'))
    const activeDropdown = document.querySelector(
      '.ant-select-dropdown:not(.ant-select-dropdown-hidden)',
    ) as HTMLElement
    await browser.click(
      within(activeDropdown).getByText('web', { selector: '.ant-select-item-option-content' }),
    )
    await browser.click(screen.getByRole('button', { name: '添加 HTTP GET Seed（最多10个）' }))
    await browser.click(screen.getByRole('tab', { name: /与 v1 差异/ }))
    expect(await screen.findByText('services.1.name')).toBeVisible()
    await browser.click(screen.getByRole('button', { name: 'OK' }))
    await waitFor(() => expect(submit).toHaveBeenCalledTimes(1))
    const payload = submit.mock.calls[0][0]
    expect(payload.manifest.services).toHaveLength(2)
    expect(payload.manifest.services[1]).toMatchObject({
      name: 'api',
      depends_on: ['web'],
      health_check: base.manifest.services[0].health_check,
      environment: base.manifest.services[0].environment,
      no_new_privileges: true,
    })
    expect(payload.manifest.seeds).toHaveLength(2)
    expect(close).not.toHaveBeenCalled()
    await browser.click(screen.getByRole('tab', { name: '可视化配置' }))
    expect(serviceCard(2).getByLabelText('服务名称')).toHaveValue('api')
    await browser.click(screen.getByRole('button', { name: 'OK' }))
    await waitFor(() => expect(submit).toHaveBeenCalledTimes(2))
    expect(submit.mock.calls[1][0]).toEqual(payload)
  })

  it('requires explicit JSON application, rejects untrusted fields and cyclic dependencies, and keeps the form intact', async () => {
    const { submit } = renderDialog()
    const browser = userEvent.setup()
    await browser.click(screen.getByRole('tab', { name: '高级 JSON' }))
    const original = defaultEnvironmentManifest()
    fireEvent.change(screen.getByLabelText('完整声明式模板'), {
      target: { value: JSON.stringify({ ...original, command: 'forbidden' }) },
    })
    await browser.click(screen.getByRole('button', { name: '校验并应用 JSON' }))
    expect(await screen.findByText('模板不支持字段 command')).toBeVisible()
    await browser.click(screen.getByRole('button', { name: 'OK' }))
    expect(await screen.findByText(/高级JSON尚未应用/)).toBeVisible()
    expect(submit).not.toHaveBeenCalled()
    const cycle = structuredClone(original)
    cycle.services[0].depends_on = ['web']
    fireEvent.change(screen.getByLabelText('完整声明式模板'), {
      target: { value: JSON.stringify(cycle) },
    })
    await browser.click(screen.getByRole('button', { name: '校验并应用 JSON' }))
    expect(await screen.findByText('服务依赖存在循环')).toBeVisible()
    await browser.click(screen.getByRole('button', { name: '放弃 JSON 修改' }))
    await browser.click(screen.getByRole('tab', { name: '可视化配置' }))
    expect(serviceCard(1).getByLabelText('服务名称')).toHaveValue('web')
    await browser.click(screen.getByRole('button', { name: 'OK' }))
    await waitFor(() =>
      expect(submit).toHaveBeenCalledWith(expect.objectContaining({ manifest: original })),
    )
  })

  it('validates field errors before submission and protects both modal close and project navigation', async () => {
    const { submit, close, router } = renderDialog()
    const browser = userEvent.setup()
    fireEvent.change(screen.getByLabelText('白名单镜像（必须固定 Digest）'), {
      target: { value: 'nginx:latest' },
    })
    await browser.click(screen.getByRole('button', { name: 'OK' }))
    expect(await screen.findByText('模板尚未提交')).toBeVisible()
    expect(submit).not.toHaveBeenCalled()
    const unload = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(unload)
    expect(unload.defaultPrevented).toBe(true)
    await browser.click(screen.getByRole('button', { name: 'Cancel' }))
    await waitFor(() =>
      expect(screen.getByText('关闭将放弃当前表单和未应用的JSON修改。')).toBeVisible(),
    )
    await browser.click(screen.getByRole('button', { name: '继续编辑' }))
    expect(close).not.toHaveBeenCalled()
    await browser.click(screen.getByRole('link', { name: '离开环境页' }))
    await waitFor(() =>
      expect(screen.getByText('离开将放弃此模板的表单和未应用的JSON修改。')).toBeVisible(),
    )
    await browser.click(screen.getByRole('button', { name: '继续编辑' }))
    expect(router.state.location.pathname).toBe('/')
    expect(screen.getByLabelText('白名单镜像（必须固定 Digest）')).toHaveValue('nginx:latest')
    await browser.click(screen.getByRole('link', { name: '离开环境页' }))
    await browser.click(screen.getByRole('button', { name: '放弃修改并离开' }))
    expect(await screen.findByText('其他页面')).toBeVisible()
  })
})
