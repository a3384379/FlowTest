import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App as AntdApp, ConfigProvider } from 'antd'
import { http, HttpResponse } from 'msw'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { useAuthStore } from '../features/auth/auth-store'
import { authenticateTestUser } from '../test/auth'
import type {
  EnvironmentInstance,
  EnvironmentTemplateVersion,
} from '../features/environments/environment-service'
import ProjectTestProvider from '../test/ProjectTestProvider'
import { project, user } from '../test/fixtures'
import { server } from '../test/server'
import EnvironmentLabPage from './EnvironmentLabPage'

const fixtureImage =
  'cgr.dev/chainguard/nginx@sha256:a104d1995e56b7a15e8f152078dfbdb1ecbf9f9d1af311e7906e7b4c0c790cf2'

const template: EnvironmentTemplateVersion = {
  id: '00000000-0000-4000-8000-000000001001',
  template_id: '00000000-0000-4000-8000-000000001002',
  template_key: 'platform.web',
  display_name: '受控 Web 环境',
  description: 'S26 fixture',
  status: 'active',
  version: 1,
  manifest: {
    services: [
      {
        name: 'web',
        image: fixtureImage,
        internal_port: 8080,
        environment: [{ name: 'NGINX_PORT', value: '8080' }],
        depends_on: [],
        health_check: {
          kind: 'http',
          path: '/',
          expected_status: 200,
          interval_seconds: 1,
          timeout_seconds: 2,
          maximum_attempts: 30,
        },
        cpu_millicores: 250,
        memory_megabytes: 128,
        pids_limit: 64,
        user_id: 65532,
        group_id: 65532,
        read_only_root_filesystem: true,
        drop_all_capabilities: true,
        no_new_privileges: true,
      },
    ],
    seeds: [{ profile: 'http_get_v1', service: 'web', path: '/' }],
    default_ttl_seconds: 3600,
    maximum_ttl_seconds: 14400,
  },
  manifest_sha256: 'a'.repeat(64),
  signature: 'b'.repeat(64),
  signature_algorithm: 'hmac-sha256-v1',
  signed_by_id: user.id,
  created_at: '2026-08-12T07:00:00Z',
}

const instance: EnvironmentInstance = {
  id: '00000000-0000-4000-8000-000000001003',
  project_id: project.id,
  template_version_id: template.id,
  template_key: template.template_key,
  template_version: 1,
  status: 'ready',
  cleanup_status: 'none',
  runtime_name: 'flowtest-env-00000000000040008000000000001003',
  ttl_seconds: 3600,
  fencing_token: 1,
  endpoints: [{ service: 'web', url: 'http://environment-docker:49152', internal_port: 8080 }],
  seed_evidence: [{ profile: 'http_get_v1', service: 'web', path: '/', status_code: 200 }],
  error_code: null,
  error_message: null,
  cleanup_error_code: null,
  cleanup_attempts: 0,
  queued_at: '2026-08-12T07:00:00Z',
  started_at: '2026-08-12T07:00:01Z',
  ready_at: '2026-08-12T07:00:02Z',
  expires_at: '2026-08-12T08:00:00Z',
  cancellation_requested_at: null,
  cleanup_started_at: null,
  cleaned_at: null,
  created_by_id: user.id,
  created_at: '2026-08-12T07:00:00Z',
  updated_at: '2026-08-12T07:00:02Z',
}

describe('EnvironmentLabPage', () => {
  beforeEach(() => {
    authenticateTestUser({ ...user, is_system_admin: true })
  })

  afterEach(() => {
    useAuthStore.setState({ user: null })
  })

  it('shows signed evidence, provisions from a typed template, and submits cleanup', async () => {
    let provisionPayload: Record<string, unknown> | null = null
    let idempotencyKey = ''
    let cleaned = 0
    installHandlers()
    server.use(
      http.post(`/api/v1/projects/${project.id}/environment-instances`, async ({ request }) => {
        provisionPayload = (await request.json()) as Record<string, unknown>
        idempotencyKey = request.headers.get('Idempotency-Key') ?? ''
        return HttpResponse.json({ ...instance, status: 'queued' }, { status: 202 })
      }),
      http.post(
        `/api/v1/projects/${project.id}/environment-instances/${instance.id}/cleanup`,
        () => {
          cleaned += 1
          return HttpResponse.json({ ...instance, status: 'cancelled', cleanup_status: 'pending' })
        },
      ),
    )
    renderPage()
    const browser = userEvent.setup()

    expect(await screen.findByRole('heading', { name: '环境实验室' })).toBeVisible()
    expect(await screen.findByText('受控 Web 环境')).toBeVisible()
    expect(screen.getByText('已就绪')).toBeVisible()
    await browser.click(screen.getAllByRole('button', { name: 'Expand row' })[0])
    expect(await screen.findByText(template.manifest_sha256)).toBeVisible()
    await browser.click(screen.getAllByRole('button', { name: 'Expand row' }).at(-1)!)
    expect(await screen.findByText(/environment-docker:49152/)).toBeVisible()

    await browser.click(screen.getByLabelText('模板版本'))
    await browser.click(await screen.findByText('受控 Web 环境 · v1'))
    await browser.click(screen.getByRole('button', { name: 'Provision' }))
    await waitFor(() => expect(provisionPayload).not.toBeNull())
    expect(provisionPayload).toEqual({ template_version_id: template.id, ttl_seconds: 3600 })
    expect(idempotencyKey).toHaveLength(36)

    await browser.click(screen.getByRole('button', { name: /清理/ }))
    await browser.click(await screen.findByRole('button', { name: 'OK' }))
    await waitFor(() => expect(cleaned).toBe(1))
  })

  it('registers and versions structured templates without Compose or script fields', async () => {
    const registered: Array<Record<string, unknown>> = []
    const versioned: Array<Record<string, unknown>> = []
    installHandlers()
    server.use(
      http.post('/api/v1/environment-templates', async ({ request }) => {
        registered.push((await request.json()) as Record<string, unknown>)
        return HttpResponse.json(template, { status: 201 })
      }),
      http.post(
        `/api/v1/environment-templates/${template.template_id}/versions`,
        async ({ request }) => {
          versioned.push((await request.json()) as Record<string, unknown>)
          return HttpResponse.json({ ...template, version: 2 }, { status: 201 })
        },
      ),
    )
    renderPage()
    const browser = userEvent.setup()

    await browser.click(await screen.findByRole('button', { name: /注册环境模板/ }))
    await browser.click(screen.getByRole('button', { name: 'OK' }))
    await waitFor(() => expect(registered).toHaveLength(1))
    expect(registered[0]).toMatchObject({
      template_key: 'platform.web',
      manifest: {
        services: [
          {
            image: fixtureImage,
            read_only_root_filesystem: true,
            drop_all_capabilities: true,
            no_new_privileges: true,
          },
        ],
      },
    })
    const manifest = registered[0].manifest as { services: Array<Record<string, unknown>> }
    expect(manifest).not.toHaveProperty('compose')
    expect(manifest).not.toHaveProperty('script')
    expect(manifest.services[0]).not.toHaveProperty('command')
    expect(manifest.services[0]).not.toHaveProperty('volumes')

    await browser.click(screen.getByRole('button', { name: '新建版本' }))
    await browser.click(screen.getByRole('button', { name: 'OK' }))
    await waitFor(() => expect(versioned).toHaveLength(1))
    expect(versioned[0]).toHaveProperty('manifest')
    expect(versioned[0]).not.toHaveProperty('template_key')
  })

  it('hides administrator mutations and explains failed cleanup to regular users', async () => {
    useAuthStore.setState({ user: { ...user, is_system_admin: false } })
    installHandlers({
      templates: [{ ...template, status: 'disabled' }],
      instances: [
        {
          ...instance,
          status: 'failed',
          cleanup_status: 'failed',
          error_code: 'ENVIRONMENT_HEALTH_CHECK_FAILED',
          error_message: '环境服务 web 健康检查失败',
          cleanup_error_code: 'ENVIRONMENT_CLEANUP_FAILED',
        },
      ],
    })
    renderPage()

    expect(await screen.findByText('受控 Web 环境')).toBeVisible()
    expect(screen.queryByRole('button', { name: /注册环境模板/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '新建版本' })).not.toBeInTheDocument()
    expect(screen.getByText('失败')).toBeVisible()
    expect(screen.getByText('需重试')).toBeVisible()
    await userEvent.setup().click(screen.getAllByRole('button', { name: 'Expand row' })[1])
    expect(await screen.findByText(/ENVIRONMENT_HEALTH_CHECK_FAILED/)).toBeVisible()
  })
  it('opens an off-page instance with lifecycle and cleanup evidence without claiming ongoing health', async () => {
    const failed = {
      ...instance,
      status: 'failed',
      cleanup_status: 'failed',
      cleanup_attempts: 3,
      cleanup_error_code: 'CLEANUP_RETRY_REQUIRED',
    }
    installHandlers({ instances: [], templates: [] })
    server.use(
      http.get(`/api/v1/projects/${project.id}/environment-instances/${instance.id}`, () =>
        HttpResponse.json(failed),
      ),
    )
    renderPage(`/projects/${project.id}/environments?instance=${instance.id}`)
    expect(await screen.findByText(instance.id)).toBeVisible()
    expect(screen.getByText('CLEANUP_RETRY_REQUIRED')).toBeVisible()
    expect(screen.getByText(/未提供持续服务健康采样/)).toBeVisible()
    await userEvent.setup().click(screen.getByRole('tab', { name: '签名配置与资源' }))
    expect(await screen.findByText('此实例绑定的签名模板配置')).toBeVisible()
    expect(screen.getByText(/固定模板版本ID/)).toHaveTextContent(template.id)
  })

  it('preserves all services and seed configuration when creating a signed version', async () => {
    const full = {
      ...template.manifest,
      services: [
        ...template.manifest.services,
        { ...template.manifest.services[0], name: 'second-service', depends_on: ['web'] },
      ],
      seeds: [{ profile: 'http_get_v1' as const, service: 'second-service', path: '/seed-all' }],
    }
    let payload: unknown
    installHandlers({ templates: [{ ...template, manifest: full }] })
    server.use(
      http.post(
        `/api/v1/environment-templates/${template.template_id}/versions`,
        async ({ request }) => {
          payload = await request.json()
          return HttpResponse.json({ ...template, version: 2 }, { status: 201 })
        },
      ),
    )
    renderPage()
    const browser = userEvent.setup()
    await browser.click(await screen.findByRole('button', { name: '新建版本' }))
    await browser.click(screen.getByRole('button', { name: 'OK' }))
    await waitFor(() => expect(payload).toEqual({ manifest: full }))
  })

  it('keeps server pagination and mutation permissions separate from read-only evidence', async () => {
    useAuthStore.setState({ user: { ...user, is_system_admin: false } })
    const pages: number[] = []
    installHandlers()
    server.use(
      http.get(`/api/v1/projects/${project.id}/permissions`, () =>
        HttpResponse.json({ effective_role: 'viewer', capabilities: ['read'] }),
      ),
      http.get(`/api/v1/projects/${project.id}/environment-instances`, ({ request }) => {
        const page = Number(new URL(request.url).searchParams.get('page'))
        pages.push(page)
        return HttpResponse.json({
          items: [{ ...instance, id: `instance-${page}` }],
          total: 126,
          page,
          page_size: 20,
        })
      }),
    )
    renderPage()
    expect(await screen.findByText('instance')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Provision' })).toBeDisabled()
    expect(screen.getByRole('button', { name: /清理/ })).toBeDisabled()
    await userEvent
      .setup()
      .click(
        within(screen.getByText('环境实例与清理').closest('.ant-card') as HTMLElement).getByTitle(
          'Next Page',
        ),
      )
    await waitFor(() => expect(pages).toEqual([1, 2]))
  })
  it('reads the original disabled binding independently, keeps failures and retries the same version without writes', async () => {
    let reads = 0
    let writes = 0
    installHandlers({
      templates: [
        {
          ...template,
          id: 'new-v2',
          version: 2,
          manifest: { ...template.manifest, default_ttl_seconds: 900 },
        },
      ],
      instances: [],
    })
    server.use(
      http.get(`/api/v1/projects/${project.id}/environment-instances/${instance.id}`, () =>
        HttpResponse.json(instance),
      ),
      http.get(
        `/api/v1/projects/${project.id}/environment-instances/${instance.id}/template-version`,
        () => {
          reads += 1
          return reads === 1
            ? HttpResponse.json(
                {
                  error: {
                    code: 'READ_FAILED',
                    message: '原版本暂不可读取',
                    trace_id: 'bound-template-trace',
                  },
                },
                { status: 503 },
              )
            : HttpResponse.json({ ...template, status: 'disabled' })
        },
      ),
      http.post('/api/v1/environment-templates', () => {
        writes += 1
        return new HttpResponse(null, { status: 500 })
      }),
      http.post(`/api/v1/projects/${project.id}/environment-instances`, () => {
        writes += 1
        return new HttpResponse(null, { status: 500 })
      }),
    )
    renderPage(`/projects/${project.id}/environments?instance=${instance.id}`)
    const browser = userEvent.setup()
    await browser.click(await screen.findByRole('tab', { name: '签名配置与资源' }))
    expect(await screen.findByText(/bound-template-trace/)).toBeVisible()
    expect(screen.queryByText('此实例绑定的签名模板配置')).not.toBeInTheDocument()
    await browser.click(screen.getByRole('button', { name: '重试绑定版本' }))
    expect(await screen.findByText(/模板已停用；此处保留实例绑定/)).toBeVisible()
    expect(screen.getByText('此实例绑定的签名模板配置')).toBeVisible()
    expect(screen.getByText(/固定模板版本ID/)).toHaveTextContent(template.id)
    expect(reads).toBe(2)
    expect(writes).toBe(0)
  })

  it('finds an off-page provision version through its own search, pagination and exact UUID without writing until submitted', async () => {
    const queries: Array<{ page: string | null; search: string | null; active: string | null }> = []
    let writes = 0
    installHandlers()
    server.use(
      http.get('/api/v1/environment-templates', ({ request }) => {
        const params = new URL(request.url).searchParams
        if (params.get('active_only') === 'true') {
          queries.push({
            page: params.get('page'),
            search: params.get('search'),
            active: params.get('active_only'),
          })
          return HttpResponse.json({
            items:
              params.get('page') === '2' || params.get('search') === '完整环境' ? [template] : [],
            total: 21,
            page: Number(params.get('page')),
            page_size: 20,
          })
        }
        return HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 })
      }),
      http.post(`/api/v1/projects/${project.id}/environment-instances`, () => {
        writes += 1
        return HttpResponse.json(instance, { status: 202 })
      }),
    )
    renderPage()
    const browser = userEvent.setup()
    const picker = within(
      screen.getByText('Provision 受控环境').closest('.ant-card') as HTMLElement,
    )
    await waitFor(() => expect(queries).toHaveLength(1))
    await browser.click(picker.getByTitle('Next Page'))
    await waitFor(() => expect(queries.at(-1)?.page).toBe('2'))
    await browser.type(picker.getByLabelText('查找可用模板'), '完整环境{Enter}')
    await waitFor(() =>
      expect(queries.at(-1)).toEqual({ page: '1', search: '完整环境', active: 'true' }),
    )
    await browser.type(picker.getByLabelText('模板版本ID'), template.id)
    await browser.click(picker.getByRole('button', { name: '读取指定版本' }))
    await waitFor(() => expect(picker.getByRole('button', { name: 'Provision' })).toBeEnabled())
    expect(picker.getByText(/固定版本/)).toHaveTextContent(template.id)
    expect(writes).toBe(0)
    await browser.click(picker.getByRole('button', { name: 'Provision' }))
    await waitFor(() => expect(writes).toBe(1))
  })

  it('explains disabled capability and avoids unavailable catalog requests', async () => {
    let reads = 0
    installHandlers()
    server.use(
      http.get('/api/v1/v3/features', () => HttpResponse.json({ environment_lab: false })),
      http.get('/api/v1/projects/:id/environment-instances', () => {
        reads += 1
        return HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 })
      }),
    )
    renderPage()
    expect(await screen.findByText('环境实验室当前关闭')).toBeVisible()
    expect(reads).toBe(0)
    expect(screen.queryByRole('button', { name: '注册环境模板' })).not.toBeInTheDocument()
  })
})

function installHandlers({
  templates = [template],
  instances = [instance],
}: {
  templates?: EnvironmentTemplateVersion[]
  instances?: EnvironmentInstance[]
} = {}) {
  server.use(
    http.get('/api/v1/projects', () =>
      HttpResponse.json({ items: [project], total: 1, page: 1, page_size: 100 }),
    ),
    http.get('/api/v1/environment-templates/versions/:versionId', () =>
      HttpResponse.json(template),
    ),
    http.get(
      `/api/v1/projects/${project.id}/environment-instances/${instance.id}/template-version`,
      () => HttpResponse.json(template),
    ),
    http.get('/api/v1/environment-templates', () =>
      HttpResponse.json({ items: templates, total: templates.length, page: 1, page_size: 100 }),
    ),
    http.get(`/api/v1/projects/${project.id}/environment-instances`, () =>
      HttpResponse.json({ items: instances, total: instances.length, page: 1, page_size: 100 }),
    ),
  )
}

function renderPage(initialEntry?: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <AntdApp>
        <QueryClientProvider client={queryClient}>
          <ProjectTestProvider section="environments" initialEntry={initialEntry}>
            <EnvironmentLabPage />
          </ProjectTestProvider>
        </QueryClientProvider>
      </AntdApp>
    </ConfigProvider>,
  )
}
