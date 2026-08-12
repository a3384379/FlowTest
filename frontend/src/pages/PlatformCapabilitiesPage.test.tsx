import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App as AntdApp } from 'antd'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'

import type { Capability, Plugin, RunnerPool } from '../features/capabilities/capability-service'
import { useAuthStore } from '../features/auth/auth-store'
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
  beforeEach(() => {
    useAuthStore.setState({ user, initialized: true, token: 'test-token' })
  })

  it('shows versioned capabilities and their pinned security contract', async () => {
    installHandlers({ capabilitySdk: false })
    renderPage()

    expect(await screen.findByText('HTTP 请求')).toBeVisible()
    expect(screen.getByText('Capability SDK 当前处于兼容预览模式')).toBeVisible()
    expect(screen.getByText('0123456789abcdef…')).toBeVisible()
    expect(screen.getByText('固定 Schema 哈希')).toBeVisible()
    expect(screen.getByText(/插件不会获得 Secret 明文/)).toBeVisible()
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
    expect(screen.getByText(plugin.oci_digest)).toBeVisible()

    await browser.click(screen.getByTitle('Runner'))
    expect(await screen.findByText('General Pool')).toBeVisible()
    expect(screen.getByText('1 个')).toBeVisible()
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
      }),
    ),
    http.get('/api/v1/capabilities', () =>
      HttpResponse.json({ items: [capability], total: 1, page: 1, page_size: 100 }),
    ),
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

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <AntdApp>
      <QueryClientProvider client={queryClient}>
        <PlatformCapabilitiesPage />
      </QueryClientProvider>
    </AntdApp>,
  )
}
