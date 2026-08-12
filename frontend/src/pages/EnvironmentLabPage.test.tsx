import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App as AntdApp } from 'antd'
import { http, HttpResponse } from 'msw'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { useAuthStore } from '../features/auth/auth-store'
import type {
  EnvironmentInstance,
  EnvironmentTemplateVersion,
} from '../features/environments/environment-service'
import ProjectTestProvider from '../test/ProjectTestProvider'
import { project, user } from '../test/fixtures'
import { server } from '../test/server'
import EnvironmentLabPage from './EnvironmentLabPage'

const fixtureImage =
  'nginxinc/nginx-unprivileged:1.31.3-alpine3.24@sha256:334d92979f15aaecd5dd50af5105e1230e2bb70765d45b1e2f964e7c5eda81c3'

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
        user_id: 101,
        group_id: 101,
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
    useAuthStore.setState({ user: { ...user, is_system_admin: true } })
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
    http.get('/api/v1/environment-templates', () =>
      HttpResponse.json({ items: templates, total: templates.length, page: 1, page_size: 100 }),
    ),
    http.get(`/api/v1/projects/${project.id}/environment-instances`, () =>
      HttpResponse.json({ items: instances, total: instances.length, page: 1, page_size: 100 }),
    ),
  )
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <AntdApp>
      <QueryClientProvider client={queryClient}>
        <ProjectTestProvider section="environments">
          <EnvironmentLabPage />
        </ProjectTestProvider>
      </QueryClientProvider>
    </AntdApp>,
  )
}
