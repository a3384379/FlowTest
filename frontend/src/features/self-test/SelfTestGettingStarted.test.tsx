import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App, ConfigProvider } from 'antd'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import QualityCenterPage from '../../pages/QualityCenterPage'
import ProjectTestProvider from '../../test/ProjectTestProvider'
import { authenticateTestUser } from '../../test/auth'
import { project, user } from '../../test/fixtures'
import { server } from '../../test/server'
import { useAuthStore } from '../auth/auth-store'
import { selfTestBinding, selfTestPage, selfTestTemplate } from './self-test-test-fixtures'

const base = `/api/v1/projects/${project.id}/self-tests`
function mount(bindingId?: string) {
  return render(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <App>
        <QueryClientProvider
          client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
        >
          <ProjectTestProvider
            section="quality"
            initialEntry={`/projects/${project.id}/quality?tab=selftest&mode=mcp_generation${bindingId ? `&binding=${bindingId}` : ''}`}
          >
            <QualityCenterPage />
          </ProjectTestProvider>
        </QueryClientProvider>
      </App>
    </ConfigProvider>,
  )
}
beforeEach(() => {
  authenticateTestUser(user)
  server.use(
    http.get('/api/v1/projects', () =>
      HttpResponse.json({ items: [project], total: 1, page: 1, page_size: 100 }),
    ),
    http.get(`${base}/bindings`, () => HttpResponse.json(selfTestPage([]))),
    http.get(`${base}/templates`, () => HttpResponse.json(selfTestPage([selfTestTemplate]))),
  )
})

describe('self-test onboarding', () => {
  it('offers deployment setup before initialization and copies the current project checklist without writing', async () => {
    const browser = userEvent.setup()
    const copied = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue()
    const writes = vi.fn()
    server.use(
      http.post(`${base}/*`, () => {
        writes()
        return new HttpResponse(null, { status: 403 })
      }),
    )
    mount()
    expect(await screen.findByRole('heading', { name: '先接入自测环境' })).toBeVisible()
    expect(screen.getByRole('button', { name: '初始化自测' })).toBeDisabled()
    await browser.click(screen.getByRole('button', { name: '配置自测环境' }))
    const drawer = within(screen.getByRole('dialog'))
    expect(drawer.getByRole('tab', { name: '部署登记' })).toHaveAttribute('aria-selected', 'true')
    expect(drawer.getByText('FLOWTEST_SELFTEST_BINDINGS')).toBeVisible()
    expect(drawer.getByText('FLOWTEST_SELFTEST_PRINCIPALS')).toBeVisible()
    await browser.click(drawer.getByRole('button', { name: '复制项目接入清单' }))
    expect(copied).toHaveBeenCalledWith(expect.stringContaining(project.id))
    expect(copied).toHaveBeenCalledWith(expect.stringContaining('allowed_project_ids'))
    expect(drawer.getByRole('link', { name: '下载完整部署说明' })).toHaveAttribute(
      'href',
      '/help/self-test-setup.md',
    )
    expect(writes).not.toHaveBeenCalled()
  })

  it('explains both run modes to a viewer while keeping execution disabled', async () => {
    server.use(
      http.get(`/api/v1/projects/${project.id}/permissions`, () =>
        HttpResponse.json({ effective_role: 'viewer', capabilities: ['read'], matrix: {} }),
      ),
    )
    mount()
    await screen.findByRole('heading', { name: '先接入自测环境' })
    await userEvent.click(screen.getByRole('button', { name: '使用指南' }))
    const drawer = within(screen.getByRole('dialog'))
    expect(drawer.getByRole('tab', { name: '如何自测' })).toHaveAttribute('aria-selected', 'true')
    expect(drawer.getByText(/运行固定基准/)).toBeVisible()
    expect(drawer.getByText(/审核并发布 Workflow 与 Case/)).toBeVisible()
    expect(screen.getByRole('button', { name: '初始化自测' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '创建 MCP 生成任务' })).toBeDisabled()
  })

  it('refreshes the authorized binding catalog after deployment registration', async () => {
    let registered = false
    let reads = 0
    server.use(
      http.get(`${base}/bindings`, () => {
        reads += 1
        return HttpResponse.json(selfTestPage(registered ? [selfTestBinding] : []))
      }),
    )
    mount()
    await screen.findByRole('heading', { name: '先接入自测环境' })
    await userEvent.click(screen.getByRole('button', { name: '配置自测环境' }))
    registered = true
    const drawer = within(screen.getByRole('dialog'))
    await userEvent.click(drawer.getByRole('button', { name: '重新检查接入' }))
    expect(await drawer.findByText('已登记 1 个可见绑定，请在页面选择')).toBeVisible()
    expect(reads).toBe(2)
    await userEvent.click(drawer.getByRole('button', { name: '返回自测工作台' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    await userEvent.click(screen.getByRole('combobox', { name: '自测绑定' }))
    await userEvent.click(screen.getByText(selfTestBinding.name))
    expect(await screen.findByRole('button', { name: '初始化自测' })).toBeEnabled()
  })

  it('keeps failed binding reads distinct from an unconfigured deployment', async () => {
    server.use(
      http.get(`${base}/bindings`, () =>
        HttpResponse.json(
          {
            error: {
              code: 'UNAVAILABLE',
              message: '登记状态读取失败',
              trace_id: 'setup-read-trace',
            },
          },
          { status: 503 },
        ),
      ),
    )
    mount()
    expect(await screen.findByText('登记状态读取失败')).toBeVisible()
    expect(screen.getByText('Trace ID: setup-read-trace')).toBeVisible()
    expect(screen.queryByRole('heading', { name: '先接入自测环境' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '配置自测环境' }))
    expect(within(screen.getByRole('dialog')).getByText('读取失败，请重新检查')).toBeVisible()
  })

  it('directs a selected binding with missing H/O identities to connect its agents', async () => {
    server.use(
      http.get(`${base}/bindings`, () =>
        HttpResponse.json(
          selfTestPage([
            {
              ...selfTestBinding,
              host_status: 'not_registered',
              observer_status: 'not_configured',
              actions: { ...selfTestBinding.actions, can_initialize: false },
            },
          ]),
        ),
      ),
    )
    mount(selfTestBinding.id)
    await userEvent.click(screen.getByRole('button', { name: '配置自测环境' }))
    const drawer = within(screen.getByRole('dialog'))
    expect(await drawer.findAllByText('尚未登记，请管理员启动并连接代理')).toHaveLength(2)
    expect(drawer.queryByText('尚未核实，请先选择绑定')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '初始化自测' })).toBeDisabled()
  })

  it('closes a project-specific setup checklist when the authorization epoch changes', async () => {
    mount()
    await screen.findByRole('heading', { name: '先接入自测环境' })
    await userEvent.click(screen.getByRole('button', { name: '配置自测环境' }))
    expect(screen.getByRole('dialog')).toBeVisible()
    act(() => useAuthStore.setState((state) => ({ epoch: state.epoch + 1 })))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })
})
