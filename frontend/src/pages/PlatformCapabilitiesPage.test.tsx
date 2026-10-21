import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within, waitFor, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App as AntdApp } from 'antd'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { Capability, Plugin, RunnerPool } from '../features/capabilities/capability-service'
import { useAuthStore } from '../features/auth/auth-store'
import { authenticateTestUser } from '../test/auth'
import { user } from '../test/fixtures'
import { server } from '../test/server'
import PlatformCapabilitiesPage from './PlatformCapabilitiesPage'

const capability: Capability = {
  id: 'builtin.http.request',
  version: '2.0.0',
  category: 'protocol',
  display_name: 'HTTP 请求',
  description: '兼容 V2 HTTP 节点',
  runner_type: 'general',
  network_access: 'project_allowlist',
  schema_hash: '0123456789abcdef0123456789abcdef',
  source: 'builtin',
  enabled: true,
  plugin_id: null,
  plugin_digest: null,
  manifest: {
    id: 'builtin.http.request',
    version: '2.0.0',
    category: 'protocol',
    display_name: 'HTTP 请求',
    description: '兼容 V2 HTTP 节点',
    credential_types: ['http_auth'],
    runner_type: 'general',
    network_policy: {
      access: 'project_allowlist',
      protocols: ['http', 'https'],
      dns_revalidation: true,
    },
    timeout_policy: { default_seconds: 30, maximum_seconds: 300 },
    snapshot_policy: {
      include_configuration: true,
      include_schema_hash: true,
      pin_plugin_digest: true,
      credential_material: 'encrypted_reference',
    },
    redaction_policy: {
      sensitive_paths: [],
      redact_credentials: true,
      redact_headers: true,
      redact_artifacts: true,
    },
    plugin_id: null,
    plugin_digest: null,
    input_schema: { type: 'object' },
    output_schema: { type: 'object' },
    configuration_schema: { type: 'object' },
  },
}

const plugin: Plugin = {
  id: '00000000-0000-4000-8000-000000000301',
  plugin_key: 'internal.signature',
  version: '2.0.1',
  display_name: '内部签名能力',
  oci_repository: 'registry.example/flowtest/signature',
  oci_digest: `sha256:${'a'.repeat(64)}`,
  signature_identity: 'flowtest@example.com',
  status: 'active',
  created_at: '2026-08-12T01:00:00Z',
  updated_at: '2026-08-12T01:00:00Z',
}

const runnerPool: RunnerPool = {
  id: '00000000-0000-4000-8000-000000000302',
  name: 'General Pool',
  runner_type: 'general',
  network_zone: 'default',
  labels: ['arm64'],
  max_concurrency: 20,
  enabled: true,
  runners: [
    {
      id: '00000000-0000-4000-8000-000000000303',
      pool_id: '00000000-0000-4000-8000-000000000302',
      name: 'runner-1',
      status: 'online',
      labels: ['arm64'],
      capabilities: ['builtin.http.request'],
      current_load: 1,
      last_seen_at: '2026-08-12T01:01:00Z',
    },
  ],
}

describe('PlatformCapabilitiesPage', () => {
  it('reports failed inventory reads without inventing zero capability counts', async () => {
    installHandlers({ capabilitySdk: true })
    server.use(
      http.get('/api/v1/capabilities', () =>
        HttpResponse.json(
          {
            error: {
              code: 'UNAVAILABLE',
              message: '能力目录读取失败',
              trace_id: 'capability-trace',
            },
          },
          { status: 503 },
        ),
      ),
    )
    renderPage()
    expect(await screen.findByText('能力目录读取失败')).toBeInTheDocument()
    expect(screen.getByText(/当前目录共 未提供/)).toBeVisible()
    expect(screen.getByRole('button', { name: '重试' })).toBeEnabled()
    await userEvent.click(screen.getByTitle('插件'))
    await screen.findByRole('button', { name: plugin.display_name })
    expect(screen.queryByText('能力目录读取失败')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '重试' })).not.toBeInTheDocument()
  })

  beforeEach(() => {
    authenticateTestUser(user)
  })

  it('shows versioned capabilities and their pinned security contract', async () => {
    installHandlers({ capabilitySdk: false })
    renderPage()

    expect(await screen.findByText('HTTP 请求')).toBeVisible()
    expect(screen.getByText('Capability SDK 当前处于兼容预览模式')).toBeVisible()
    await userEvent.click(screen.getByRole('button', { name: 'HTTP 请求' }))
    expect(await screen.findByText(capability.schema_hash)).toBeVisible()
    expect(screen.getByText('最大超时')).toBeVisible()
    expect(screen.getByText('300 秒')).toBeVisible()
    expect(screen.getByRole('button', { name: '安装签名插件' })).toBeDisabled()
  })

  it('lets administrators inspect plugin and runner inventory', async () => {
    installHandlers({ capabilitySdk: true })
    renderPage()
    const browser = userEvent.setup()

    expect(await screen.findByText('HTTP 请求')).toBeVisible()
    expect(screen.queryByText('Capability SDK 当前处于兼容预览模式')).not.toBeInTheDocument()

    await browser.click(screen.getByText('插件'))
    expect(await screen.findByText('内部签名能力')).toBeVisible()
    await browser.click(screen.getByRole('button', { name: plugin.display_name }))
    expect(await within(inspector()).findByText(plugin.oci_digest)).toBeVisible()
    expect(within(inspector()).getByText(plugin.signature_identity)).toBeVisible()

    await browser.click(screen.getByTitle('Runner'))
    expect(await screen.findByText('General Pool')).toBeVisible()
    expect(screen.getByText('1 个')).toBeVisible()
    expect(within(inspector()).queryByText('插件详情')).not.toBeInTheDocument()
    await browser.click(screen.getByRole('button', { name: 'General Pool' }))
    expect(await within(inspector()).findByText('Runner Pool 详情')).toBeVisible()
    expect(within(inspector()).getByText('runner-1')).toBeVisible()
  })

  it('clears a capability inspector when switching to an empty plugin inventory', async () => {
    installHandlers({ capabilitySdk: true })
    server.use(
      http.get('/api/v1/plugins', () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 }),
      ),
    )
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: 'HTTP 请求' }))
    await within(inspector()).findByText(`${capability.id}@${capability.version}`)
    await userEvent.click(screen.getByTitle('插件'))
    expect(
      within(inspector()).queryByText(`${capability.id}@${capability.version}`),
    ).not.toBeInTheDocument()
    expect(within(inspector()).getByText('选择当前库存对象查看详情')).toBeVisible()
    expect(await screen.findByText(/尚未安装管理员签名插件/)).toBeVisible()
  })

  it('copies each complete schema and shows current policies without changing the manifest', async () => {
    installHandlers({ capabilitySdk: true })
    const schemas = {
      input_schema: {
        type: 'object',
        properties: { ticket: { type: 'string', description: '票据' } },
        required: ['ticket'],
      },
      output_schema: { type: 'object', properties: { accepted: { type: 'boolean' } } },
      configuration_schema: { type: 'object', properties: { zone: { type: 'string' } } },
    }
    const record = { ...capability, manifest: { ...capability.manifest, ...schemas } }
    server.use(
      http.get('/api/v1/capabilities/:id/versions/:version', () => HttpResponse.json(record)),
    )
    const browser = userEvent.setup()
    const copy = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue()
    renderPage()
    await browser.click(await screen.findByRole('button', { name: 'HTTP 请求' }))
    await within(inspector()).findByText(capability.schema_hash)
    for (const [label, value] of [
      ['输入 Schema', schemas.input_schema],
      ['输出 Schema', schemas.output_schema],
      ['配置 Schema', schemas.configuration_schema],
    ] as const) {
      await browser.click(screen.getByRole('tab', { name: label }))
      const reader = within(inspector()).getByRole('region', { name: label })
      await browser.click(within(reader).getByRole('button', { name: '复制完整内容' }))
      expect(copy).toHaveBeenLastCalledWith(JSON.stringify(value, null, 2))
      await browser.type(within(reader).getByLabelText(`${label}搜索内容`), 'type')
      expect(within(reader).getByText(/匹配/)).toBeVisible()
    }
    await browser.click(screen.getByRole('tab', { name: '策略与来源' }))
    expect(within(inspector()).getByText('DNS 重新校验')).toBeVisible()
    expect(within(inspector()).getByText('http、https')).toBeVisible()
    expect(within(inspector()).getByText('encrypted_reference')).toBeVisible()
    expect(capability.manifest.input_schema).toEqual({ type: 'object' })
  })

  it('restores an exact version outside the current page and retains it while searching', async () => {
    installHandlers({ capabilitySdk: true })
    let searched = ''
    server.use(
      http.get('/api/v1/capabilities', ({ request }) => {
        searched = new URL(request.url).searchParams.get('search') ?? ''
        return HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 })
      }),
    )
    renderPage(`/platform?mode=capability&id=${capability.id}&version=2.0.0`)
    expect(await within(inspector()).findByText(capability.schema_hash)).toBeVisible()
    await userEvent.type(screen.getByLabelText('搜索平台库存'), 'page-101{Enter}')
    await waitFor(() => expect(searched).toBe('page-101'))
    expect(within(inspector()).getByText(`${capability.id}@2.0.0`)).toBeVisible()
  })

  it('ignores a late capability response after switching to plugin details', async () => {
    installHandlers({ capabilitySdk: true })
    let finish: (value: Response) => void = () => undefined
    let requested = false
    server.use(
      http.get('/api/v1/capabilities/:id/versions/:version', () => {
        requested = true
        return new Promise<Response>((resolve) => {
          finish = resolve
        })
      }),
    )
    renderPage(`/platform?id=${capability.id}&version=2.0.0`)
    await waitFor(() => expect(requested).toBe(true))
    await userEvent.click(screen.getByTitle('插件'))
    await userEvent.click(await screen.findByRole('button', { name: plugin.display_name }))
    await within(inspector()).findByText('插件详情')
    await act(async () => {
      finish(HttpResponse.json(capability))
    })
    expect(within(inspector()).queryByText('能力契约检查器')).not.toBeInTheDocument()
    expect(within(inspector()).getByText(plugin.signature_identity)).toBeVisible()
  })

  it.each(['future-policy', 'constructor', '__proto__'])(
    'degrades missing schema and unknown policy %s without claiming a safe result',
    async (policy) => {
      installHandlers({ capabilitySdk: true })
      server.use(
        http.get('/api/v1/capabilities/:id/versions/:version', () =>
          HttpResponse.json({ ...capability, network_access: policy, manifest: {} }),
        ),
      )
      renderPage(`/platform?id=${capability.id}&version=2.0.0`)
      expect(await within(inspector()).findByText(`未知策略：${policy}`)).toBeVisible()
      expect(within(inspector()).getAllByText('未提供').length).toBeGreaterThan(2)
      await userEvent.click(screen.getByRole('tab', { name: '输入 Schema' }))
      expect(within(inspector()).getByText('Schema 未提供')).toBeVisible()
      expect(within(inspector()).queryByText('安全边界')).not.toBeInTheDocument()
    },
  )

  it.each([
    { mode: 'plugin', id: plugin.id, title: '插件详情', name: plugin.signature_identity },
    { mode: 'runnerPool', id: runnerPool.id, title: 'Runner Pool 详情', name: 'runner-1' },
  ])('restores a $mode URL outside an empty catalog', async ({ mode, id, title, name }) => {
    installHandlers({ capabilitySdk: true })
    server.use(
      http.get('/api/v1/plugins', () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 }),
      ),
      http.get('/api/v1/runner-pools', () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 }),
      ),
    )
    renderPage(`/platform?mode=${mode}&id=${id}`)
    expect(await within(inspector()).findByText(title)).toBeVisible()
    expect(within(inspector()).getByText(name)).toBeVisible()
    await userEvent.click(screen.getByRole('button', { name: '刷新库存' }))
    expect(within(inspector()).getByText(title)).toBeVisible()
  })

  it('keeps the selected plugin while reaching page 101 of its directory', async () => {
    installHandlers({ capabilitySdk: true })
    const pages: string[] = []
    server.use(
      http.get('/api/v1/plugins', ({ request }) => {
        const page = new URL(request.url).searchParams.get('page') ?? '1'
        pages.push(page)
        return HttpResponse.json({
          items: [{ ...plugin, id: `plugin-${page}`, display_name: `插件目录第${page}页` }],
          total: 101,
          page: Number(page),
          page_size: 20,
        })
      }),
    )
    renderPage(`/platform?mode=plugin&id=${plugin.id}`)
    await within(inspector()).findByText('插件详情')
    await userEvent.click(screen.getByTitle('6'))
    expect(await screen.findByRole('button', { name: '插件目录第6页' })).toBeVisible()
    expect(within(inspector()).getByText(plugin.signature_identity)).toBeVisible()
    expect(pages).toEqual(['1', '6'])
  })

  it('discards a late old version after another version is selected', async () => {
    installHandlers({ capabilitySdk: true })
    const newer = {
      ...capability,
      version: '3.0.0',
      display_name: '新版 HTTP 请求',
      schema_hash: 'version-three-hash',
    }
    let finish: (value: Response) => void = () => undefined
    let requested = false
    server.use(
      http.get('/api/v1/capabilities', () =>
        HttpResponse.json({ items: [capability, newer], total: 2, page: 1, page_size: 20 }),
      ),
      http.get('/api/v1/capabilities/:id/versions/:version', ({ params }) => {
        if (params.version === '3.0.0') return HttpResponse.json(newer)
        requested = true
        return new Promise<Response>((resolve) => {
          finish = resolve
        })
      }),
    )
    renderPage(`/platform?id=${capability.id}&version=2.0.0`)
    await waitFor(() => expect(requested).toBe(true))
    await userEvent.click(await screen.findByRole('button', { name: '新版 HTTP 请求' }))
    expect(await within(inspector()).findByText('version-three-hash')).toBeVisible()
    await act(async () => {
      finish(HttpResponse.json(capability))
    })
    expect(within(inspector()).queryByText(capability.schema_hash)).not.toBeInTheDocument()
    expect(within(inspector()).getByText(`${capability.id}@3.0.0`)).toBeVisible()
  })

  it('hides a late detail response from the previous organization', async () => {
    installHandlers({ capabilitySdk: true })
    let finish: (value: Response) => void = () => undefined
    let reads = 0
    server.use(
      http.get('/api/v1/plugins/:id', () => {
        reads += 1
        if (reads === 1)
          return new Promise<Response>((resolve) => {
            finish = resolve
          })
        return HttpResponse.json(
          { error: { code: 'PLUGIN_NOT_FOUND', message: '当前组织无此对象' } },
          { status: 404 },
        )
      }),
    )
    renderPage(`/platform?mode=plugin&id=${plugin.id}`)
    await waitFor(() => expect(reads).toBe(1))
    act(() => {
      useAuthStore.setState({ organizationId: 'another-organization' })
    })
    expect(await within(inspector()).findByText('当前组织无此对象')).toBeVisible()
    await act(async () => {
      finish(HttpResponse.json(plugin))
    })
    expect(within(inspector()).queryByText(plugin.signature_identity)).not.toBeInTheDocument()
    expect(within(inspector()).queryByText('插件详情')).not.toBeInTheDocument()
  })

  it('does not retain administrator details after the same user loses that role', async () => {
    installHandlers({ capabilitySdk: true })
    renderPage(`/platform?mode=plugin&id=${plugin.id}`)
    await within(inspector()).findByText('插件详情')
    act(() => {
      useAuthStore.setState({ user: { ...user, is_system_admin: false } })
    })
    expect(within(inspector()).queryByText(plugin.signature_identity)).not.toBeInTheDocument()
    expect(within(inspector()).getByText('当前角色不能读取此类库存详情')).toBeVisible()
    expect(screen.getByText(/当前目录共 未提供/)).toBeVisible()
  })

  it('does not request or expose administrator inventory to regular users', async () => {
    useAuthStore.setState({ user: { ...user, is_system_admin: false } })
    installHandlers({ capabilitySdk: true, rejectAdminRequests: true })
    renderPage()
    const browser = userEvent.setup()

    expect(await screen.findByText('HTTP 请求')).toBeVisible()
    await browser.click(screen.getByText('插件'))
    expect(screen.getByText('仅系统管理员可查看插件清单')).toBeVisible()
    await browser.click(screen.getByTitle('Runner'))
    expect(screen.getByText('仅系统管理员可查看执行面')).toBeVisible()
  })
})

function installHandlers({
  capabilitySdk,
  rejectAdminRequests = false,
}: {
  capabilitySdk: boolean
  rejectAdminRequests?: boolean
}) {
  server.use(
    http.get('/api/v1/v3/features', () =>
      HttpResponse.json({
        capability_sdk: capabilitySdk,
        plugin_registry: false,
        runner_fabric: false,
        multi_protocol: false,
        event_protocols: false,
        performance_lab: false,
        environment_lab: false,
      }),
    ),
    http.get('/api/v1/capabilities', () =>
      HttpResponse.json({ items: [capability], total: 1, page: 1, page_size: 100 }),
    ),
    http.get('/api/v1/capabilities/:id/versions/:version', () => HttpResponse.json(capability)),
    http.get('/api/v1/plugins/:id', () => HttpResponse.json(plugin)),
    http.get('/api/v1/runner-pools/:id', () => HttpResponse.json(runnerPool)),
    http.get('/api/v1/plugins', () => {
      if (rejectAdminRequests) throw new Error('regular users must not request plugins')
      return HttpResponse.json({ items: [plugin], total: 1, page: 1, page_size: 100 })
    }),
    http.get('/api/v1/runner-pools', () => {
      if (rejectAdminRequests) throw new Error('regular users must not request runner pools')
      return HttpResponse.json({ items: [runnerPool], total: 1, page: 1, page_size: 100 })
    }),
  )
}

function inspector() {
  return screen.getByLabelText('平台对象检查器')
}

function renderPage(entry = '/platform') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <AntdApp>
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[entry]}>
          <PlatformCapabilitiesPage />
        </MemoryRouter>
      </QueryClientProvider>
    </AntdApp>,
  )
}
