import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App as AntdApp } from 'antd'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useAuthStore } from '../features/auth/auth-store'
import { user } from '../test/fixtures'
import { server } from '../test/server'
import OrganizationGovernancePage from './OrganizationGovernancePage'
import { rotationAction } from './organization-governance-rotation'

const organizationId = '00000000-0000-4000-8000-000000000701'

describe('OrganizationGovernancePage', () => {
  beforeEach(() => {
    useAuthStore.setState({ user, initialized: true, token: 'test-token' })
    installHandlers()
  })

  it('renders organization roles, quota governance, security and redacted support bundle', async () => {
    renderPage()
    expect(await screen.findByText('组织治理')).toBeVisible()
    expect(await screen.findByText('组织与角色')).toBeVisible()
    expect(screen.getByText('当前角色')).toBeVisible()

    const browser = userEvent.setup()
    await browser.click(screen.getByRole('tab', { name: '配额与 Runner' }))
    expect(await screen.findByText('配额与 Runner Pool 治理')).toBeVisible()
    expect(screen.getByText('Runner 容量')).toBeVisible()

    await browser.click(screen.getByRole('tab', { name: /审计与安全/ }))
    expect(await screen.findByText('密钥版本与迁移')).toBeVisible()
    expect(screen.getByText(/Support Bundle 只生成经过字段级脱敏的诊断清单/)).toBeVisible()
    expect(screen.getByText('data_encryption_key')).toBeVisible()
  })

  it('issues a least-privilege service account and displays its token once', async () => {
    let submitted: Record<string, unknown> | undefined
    server.use(
      http.post(`/api/v1/organizations/${organizationId}/service-accounts`, async ({ request }) => {
        submitted = (await request.json()) as Record<string, unknown>
        return HttpResponse.json(
          {
            ...account,
            token: 'ftsa_one-time-governance-token',
          },
          { status: 201 },
        )
      }),
    )
    renderPage()
    const browser = userEvent.setup()
    await screen.findByText('组织与角色')
    await browser.click(screen.getByText('Service Account'))
    const panel = screen.getByRole('tabpanel')
    await browser.type(within(panel).getByPlaceholderText('回归机器人'), 'Governance bot')
    await browser.type(within(panel).getByPlaceholderText('regression-bot'), 'governance-bot')
    const scope = within(panel).getByRole('combobox')
    fireEvent.mouseDown(scope)
    fireEvent.click(
      await screen.findByText('org:read', { selector: '.ant-select-item-option-content' }),
    )
    await browser.click(within(panel).getByRole('button', { name: '签发令牌' }))

    expect(await screen.findByText('令牌只显示一次')).toBeVisible()
    expect(screen.getByText('ftsa_one-time-governance-token')).toBeVisible()
    expect(submitted).toMatchObject({
      name: 'Governance bot',
      account_key: 'governance-bot',
      scopes: ['org:read'],
    })
  })

  it('prepares a key rotation plan from the security tab', async () => {
    let submitted: Record<string, unknown> | undefined
    server.use(
      http.post(
        `/api/v1/organizations/${organizationId}/security/key-rotation/prepare`,
        async ({ request }) => {
          submitted = (await request.json()) as Record<string, unknown>
          return HttpResponse.json({
            id: 'key-702',
            organization_id: organizationId,
            version: 2,
            key_reference: 'external:data-encryption-key',
            key_fingerprint: 'b'.repeat(64),
            status: 'pending',
            migration_status: 'prepared',
            previous_version: 1,
            created_by_id: user.id,
            activated_at: null,
            migrated_at: null,
            rolled_back_at: null,
            created_at: '2026-08-22T00:00:00Z',
            updated_at: '2026-08-22T00:00:00Z',
          })
        },
      ),
    )
    renderPage()
    const browser = userEvent.setup()
    await screen.findByText('组织与角色')
    await browser.click(screen.getByText('审计与安全'))
    const panel = screen.getByRole('tabpanel')
    await browser.type(within(panel).getByPlaceholderText('64 位十六进制指纹'), 'b'.repeat(64))
    await browser.click(within(panel).getByRole('button', { name: '创建迁移计划' }))

    await waitFor(() =>
      expect(submitted).toEqual({
        key_reference: 'external:data-encryption-key',
        key_fingerprint: 'b'.repeat(64),
      }),
    )
  })

  it('covers key rotation action guards', () => {
    const onApply = vi.fn()
    const onRollback = vi.fn()
    const baseItem = {
      id: 'key-guard-701',
      version: 1,
      key_reference: 'external:key',
      key_fingerprint: 'a'.repeat(64),
      migration_status: 'migrated',
      previous_version: null,
      created_at: '2026-08-22T00:00:00Z',
    }
    const view = render(
      <>{rotationAction({ ...baseItem, status: 'active' }, false, onApply, onRollback, false)}</>,
    )
    expect(view.container).toBeEmptyDOMElement()

    view.rerender(
      <>
        {rotationAction(
          { ...baseItem, id: 'key-pending-guard', status: 'pending' },
          true,
          onApply,
          onRollback,
          false,
        )}
      </>,
    )
    expect(screen.getByRole('button', { name: 'Apply' })).toBeVisible()

    view.rerender(
      <>
        {rotationAction(
          { ...baseItem, id: 'key-active-guard', version: 2, status: 'active' },
          true,
          onApply,
          onRollback,
          false,
        )}
      </>,
    )
    expect(screen.getByRole('button', { name: 'Rollback' })).toBeVisible()

    view.rerender(
      <>
        {rotationAction(
          { ...baseItem, id: 'key-active-v1-guard', status: 'active' },
          true,
          onApply,
          onRollback,
          false,
        )}
      </>,
    )
    expect(view.container).toBeEmptyDOMElement()
  })
})

function installHandlers() {
  server.use(
    http.get('/api/v1/organizations', () => HttpResponse.json([organization])),
    http.get(`/api/v1/organizations/${organizationId}/governance`, () =>
      HttpResponse.json(governance),
    ),
    http.get(`/api/v1/organizations/${organizationId}/members`, () => HttpResponse.json([member])),
    http.get(`/api/v1/organizations/${organizationId}/service-accounts`, () =>
      HttpResponse.json([account]),
    ),
    http.get(`/api/v1/organizations/${organizationId}/audit-logs`, () =>
      HttpResponse.json({ items: [], total: 0, page: 1, page_size: 50 }),
    ),
    http.get(`/api/v1/organizations/${organizationId}/runner-governance`, () =>
      HttpResponse.json({
        organization_id: organizationId,
        pool_count: 1,
        runner_count: 2,
        current_load: 3,
        capacity: 20,
        pools: [
          {
            id: 'pool-701',
            name: 'Default Pool',
            runner_type: 'general',
            runtime: 'docker',
            enabled: true,
            max_concurrency: 20,
            current_load: 3,
            runner_count: 2,
          },
        ],
      }),
    ),
    http.get(`/api/v1/organizations/${organizationId}/security`, () =>
      HttpResponse.json({
        organization_id: organizationId,
        active_key_version: 1,
        key_versions: [
          {
            id: 'key-701',
            organization_id: organizationId,
            version: 1,
            key_reference: 'settings:data_encryption_key',
            key_fingerprint: 'a'.repeat(64),
            status: 'active',
            migration_status: 'migrated',
            previous_version: null,
            created_by_id: user.id,
            activated_at: '2026-08-22T00:00:00Z',
            migrated_at: '2026-08-22T00:00:00Z',
            rolled_back_at: null,
            created_at: '2026-08-22T00:00:00Z',
            updated_at: '2026-08-22T00:00:00Z',
          },
        ],
      }),
    ),
    http.get(`/api/v1/organizations/${organizationId}/support-bundle/redaction`, () =>
      HttpResponse.json({
        organization_id: organizationId,
        schema_version: 's44-redacted-support-bundle-v1',
        data_classification: 'internal-redacted',
        included_sections: ['runtime_profile'],
        redacted_fields: ['service_account_token'],
        excluded_fields: ['data_encryption_key'],
      }),
    ),
  )
}

const organization = {
  id: organizationId,
  name: 'Governed Organization',
  slug: 'governed-org',
  description: 'S44 governance',
  enabled: true,
  created_by_id: user.id,
  role: 'owner' as const,
  member_count: 1,
  created_at: '2026-08-22T00:00:00Z',
  updated_at: '2026-08-22T00:00:00Z',
}

const member = {
  id: 'member-701',
  organization_id: organizationId,
  user_id: user.id,
  role: 'owner' as const,
  created_at: '2026-08-22T00:00:00Z',
  updated_at: '2026-08-22T00:00:00Z',
}

const account = {
  id: 'account-701',
  organization_id: organizationId,
  name: 'Read only bot',
  account_key: 'read-only-bot',
  token_prefix: 'ftsa_readonly',
  scopes: ['org:read'],
  enabled: true,
  created_by_id: user.id,
  expires_at: null,
  last_used_at: null,
  revoked_at: null,
  metadata_json: {},
  created_at: '2026-08-22T00:00:00Z',
  updated_at: '2026-08-22T00:00:00Z',
}

const governance = {
  organization_id: organizationId,
  audit_retention_days: 365,
  quota_policies: {
    project_count: { mode: 'observe', limit: null, warn_at: null },
    user_count: { mode: 'observe', limit: null, warn_at: null },
    runner_concurrency: { mode: 'observe', limit: null, warn_at: null },
    execution_concurrency: { mode: 'observe', limit: null, warn_at: null },
    ai_request_count: { mode: 'observe', limit: null, warn_at: null },
    artifact_storage: { mode: 'observe', limit: null, warn_at: null },
  },
  runner_policy: {
    allowed_runner_types: ['general'],
    allowed_runtimes: ['docker'],
    max_pools: 20,
    registration_requires_approval: false,
  },
  active_key_version: 1,
  updated_at: '2026-08-22T00:00:00Z',
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <AntdApp>
      <QueryClientProvider client={queryClient}>
        <OrganizationGovernancePage />
      </QueryClientProvider>
    </AntdApp>,
  )
}
