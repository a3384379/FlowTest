import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App as AntdApp } from 'antd'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'

import { authenticateTestUser } from '../test/auth'
import { user } from '../test/fixtures'
import { server } from '../test/server'
import OrganizationGovernancePage from './OrganizationGovernancePage'

const organizationId = '00000000-0000-4000-8000-000000000701'

describe('OrganizationGovernancePage', () => {
  beforeEach(() => {
    authenticateTestUser(user)
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
    expect(await screen.findByText('Organization Data Encryption Key Rotation')).toBeVisible()
    expect(screen.getByText('密钥轮换能力已确认')).toBeVisible()
    expect(screen.getByText(/Apply 在同一事务内/)).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Apply' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Rollback' })).not.toBeInTheDocument()
    expect(screen.getByText(/Support Bundle 只生成经过字段级脱敏的诊断清单/)).toBeVisible()
    expect(screen.getByText('data_encryption_key')).toBeVisible()
  })

  it('issues a least-privilege service account and displays its token once', async () => {
    let submitted: Record<string, unknown> | undefined
    let securityFailed = true
    server.use(
      http.get(`/api/v1/organizations/${organizationId}/security`, () =>
        securityFailed
          ? HttpResponse.json({ error: { message: '密钥读取暂不可用' } }, { status: 500 })
          : HttpResponse.json(readResponse('security')),
      ),
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
    await browser.type(scope, 'mcp:evidence:write')
    fireEvent.click(
      await screen.findByText('mcp:evidence:write', {
        selector: '.ant-select-item-option-content',
      }),
    )
    fireEvent.mouseDown(scope)
    await browser.type(scope, 'mcp:flow:propose')
    fireEvent.click(
      await screen.findByText('mcp:flow:propose', {
        selector: '.ant-select-item-option-content',
      }),
    )
    await browser.click(within(panel).getByRole('button', { name: '签发令牌' }))

    expect(await screen.findByText('令牌只显示一次')).toBeVisible()
    expect(screen.getByText('ftsa_one-time-governance-token')).toBeVisible()
    expect(submitted).toMatchObject({
      name: 'Governance bot',
      account_key: 'governance-bot',
      scopes: ['mcp:evidence:write', 'mcp:flow:propose'],
    })
    await browser.click(screen.getByRole('button', { name: '我已安全保存' }))
    await browser.click(screen.getByRole('tab', { name: /审计与安全/ }))
    await screen.findByText('密钥安全加载失败')
    securityFailed = false
    await browser.click(screen.getByRole('button', { name: '重试密钥安全' }))
    await screen.findByText('密钥轮换能力已确认')
    await browser.click(screen.getByRole('tab', { name: 'Service Account' }))
    expect(screen.queryByText('令牌只显示一次')).not.toBeInTheDocument()
    expect(screen.queryByText('ftsa_one-time-governance-token')).not.toBeInTheDocument()
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
            migration_status: 'planned',
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
    await browser.click(within(panel).getByRole('button', { name: '创建轮换版本' }))

    await waitFor(() =>
      expect(submitted).toEqual({
        key_reference: 'external:data-encryption-key',
        key_fingerprint: 'b'.repeat(64),
      }),
    )
  })

  it.each([
    ['runner-governance', 'Runner 治理', '配额与 Runner'],
    ['security', '密钥安全', '审计与安全'],
    ['audit-logs', '组织审计', '审计与安全'],
    ['support-bundle/redaction', '支持包', '审计与安全'],
  ])('reports %s failure and recovers only that read', async (path, label, tab) => {
    let failed = true
    server.use(
      http.get(`/api/v1/organizations/${organizationId}/${path}`, () =>
        failed
          ? HttpResponse.json(
              { error: { message: '读取不可用', trace_id: 'org-read-trace' } },
              { status: 500 },
            )
          : HttpResponse.json(readResponse(path)),
      ),
    )
    renderPage()
    await screen.findByText('组织与角色')
    await userEvent.click(screen.getByRole('tab', { name: new RegExp(tab) }))
    expect(await screen.findByText(`${label}加载失败`)).toBeVisible()
    expect(screen.getByText(/org-read-trace/)).toBeVisible()
    if (path === 'security') {
      expect(screen.queryByText('密钥轮换能力已确认')).not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: '创建轮换版本' })).not.toBeInTheDocument()
    }
    failed = false
    await userEvent.click(screen.getByRole('button', { name: `重试${label}` }))
    await waitFor(() => expect(screen.queryByText(`${label}加载失败`)).not.toBeInTheDocument())
  })

  it.each([
    ['runner-governance', 'Runner 治理', '配额与 Runner'],
    ['security', '密钥安全', '审计与安全'],
    ['audit-logs', '组织审计', '审计与安全'],
    ['support-bundle/redaction', '支持包', '审计与安全'],
  ])('shows %s permission denial without success defaults', async (path, label, tab) => {
    server.use(
      http.get(`/api/v1/organizations/${organizationId}/${path}`, () =>
        HttpResponse.json(
          { error: { message: '无权读取', trace_id: 'org-forbidden' } },
          { status: 403 },
        ),
      ),
    )
    renderPage()
    await screen.findByText('组织与角色')
    await userEvent.click(screen.getByRole('tab', { name: new RegExp(tab) }))
    expect(await screen.findByText(`无权读取${label}`)).toBeVisible()
    if (path === 'security')
      expect(screen.queryByText('密钥轮换能力已确认')).not.toBeInTheDocument()
  })

  it.each([
    ['runner-governance', 'Runner 治理', '配额与 Runner'],
    ['security', '密钥安全', '审计与安全'],
    ['audit-logs', '组织审计', '审计与安全'],
    ['support-bundle/redaction', '支持包', '审计与安全'],
  ])('keeps %s pending distinct from successful empty data', async (path, label, tab) => {
    let release: (() => void) | undefined
    server.use(
      http.get(`/api/v1/organizations/${organizationId}/${path}`, async () => {
        await new Promise<void>((resolve) => {
          release = resolve
        })
        return HttpResponse.json(readResponse(path))
      }),
    )
    renderPage()
    await screen.findByText('组织与角色')
    await userEvent.click(screen.getByRole('tab', { name: new RegExp(tab) }))
    expect(await screen.findByLabelText(`正在加载${label}`)).toBeInTheDocument()
    if (path === 'security')
      expect(screen.queryByText('密钥轮换能力已确认')).not.toBeInTheDocument()
    await act(async () => release?.())
    await waitFor(() => expect(screen.queryByLabelText(`正在加载${label}`)).not.toBeInTheDocument())
  })

  it('rejects a successful security read whose capability fields do not confirm availability', async () => {
    server.use(
      http.get(`/api/v1/organizations/${organizationId}/security`, () =>
        HttpResponse.json({
          ...readResponse('security'),
          ciphertext_reencryption_available: false,
        }),
      ),
    )
    renderPage()
    await screen.findByText('组织与角色')
    await userEvent.click(screen.getByRole('tab', { name: /审计与安全/ }))
    expect(await screen.findByText('密钥轮换能力不可用')).toBeVisible()
    expect(screen.queryByRole('button', { name: '创建轮换版本' })).not.toBeInTheDocument()
  })

  it.each(['admin', 'member', 'viewer'])(
    'preserves the %s role boundary even when key data is available',
    async (role) => {
      authenticateTestUser({ ...user, is_system_admin: false })
      server.use(
        http.get('/api/v1/organizations', () => HttpResponse.json([{ ...organization, role }])),
      )
      renderPage()
      await screen.findByText('组织与角色')
      await userEvent.click(screen.getByRole('tab', { name: /审计与安全/ }))
      expect(await screen.findByText('密钥轮换能力已确认')).toBeVisible()
      expect(screen.queryByRole('button', { name: '创建轮换版本' })).not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: 'Apply' })).not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: 'Rollback' })).not.toBeInTheDocument()
    },
  )

  it.each([404, 500])(
    'keeps exact account ID, selected role and old row role after %s',
    async (status) => {
      authenticateTestUser({ ...user, is_system_admin: false })
      let directoryReads = 0
      server.use(
        http.post('/api/v1/users/search', () => {
          directoryReads += 1
          return HttpResponse.json({})
        }),
        http.put(`/api/v1/organizations/${organizationId}/members/${user.id}`, () =>
          HttpResponse.json(
            { error: { message: '用户更新失败', trace_id: 'exact-member-trace' } },
            { status },
          ),
        ),
      )
      renderPage()
      await userEvent.click(await screen.findByRole('button', { name: '按 ID 输入' }))
      await userEvent.type(screen.getByRole('textbox', { name: '用户 ID' }), user.id)
      await userEvent.click(screen.getByRole('combobox', { name: '成员角色' }))
      await userEvent.click(
        screen.getByText('管理员 Admin', { selector: '.ant-select-item-option-content' }),
      )
      await userEvent.click(screen.getByRole('button', { name: '添加 / 更新' }))
      expect(await screen.findByText(/用户更新失败.*exact-member-trace/)).toBeVisible()
      expect(screen.getByRole('textbox', { name: '用户 ID' })).toHaveValue(user.id)
      expect(screen.getAllByText('管理员 Admin').length).toBeGreaterThan(0)
      expect(
        screen.getByRole('combobox', { name: `更新 ${user.id} 角色` }).closest('.ant-select'),
      ).toHaveTextContent('所有者 Owner')
      expect(directoryReads).toBe(0)
      expect(screen.getByText(/仅搜索已有组织成员/)).toBeVisible()
    },
  )

  it('loads audit page 6 from server and applies identity, resource and time filters', async () => {
    const requests: URL[] = []
    server.use(
      http.get(`/api/v1/organizations/${organizationId}/audit-logs`, ({ request }) => {
        const url = new URL(request.url)
        requests.push(url)
        const page = Number(url.searchParams.get('page'))
        return HttpResponse.json({ items: [auditEntry(page)], page, page_size: 10, total: 61 })
      }),
    )
    renderPage()
    await screen.findByText('组织与角色')
    await userEvent.click(screen.getByRole('tab', { name: /审计与安全/ }))
    expect(await screen.findByText('共 61 条')).toBeVisible()
    await userEvent.click(screen.getByTitle('6'))
    expect(await screen.findByText('audit-resource-6')).toBeVisible()
    expect(requests.at(-1)?.searchParams.get('page')).toBe('6')
    await userEvent.click(screen.getByRole('button', { name: '查看审计详情' }))
    const details = await screen.findByRole('dialog')
    expect(details).toHaveTextContent('audit-trace-6')
    expect(details).toHaveTextContent('仅服务端已授权详情')
    await userEvent.click(screen.getByRole('button', { name: '关闭详情' }))
    await userEvent.type(screen.getByLabelText('审计动作'), 'organization.updated')
    await userEvent.type(screen.getByLabelText('操作者 ID'), user.id)
    await userEvent.type(screen.getByLabelText('资源类型'), 'organization')
    await userEvent.type(screen.getByLabelText('资源 ID'), organizationId)
    fireEvent.change(screen.getByLabelText('开始时间'), { target: { value: '2026-10-01T12:00' } })
    fireEvent.change(screen.getByLabelText('结束时间'), { target: { value: '2026-10-21T12:00' } })
    await userEvent.click(screen.getByRole('button', { name: '查询审计' }))
    await waitFor(() => expect(requests.at(-1)?.searchParams.get('actor_user_id')).toBe(user.id))
    expect(Object.fromEntries(requests.at(-1)!.searchParams)).toMatchObject({
      page: '1',
      page_size: '10',
      action: 'organization.updated',
      resource_type: 'organization',
      resource_id: organizationId,
    })
    expect(requests.at(-1)?.searchParams.get('created_from')).toContain('2026-10-01')
    expect(requests.at(-1)?.searchParams.get('created_to')).toContain('2026-10-21')
  })

  it('shows an out of range audit page after retention removes its entries', async () => {
    server.use(
      http.get(`/api/v1/organizations/${organizationId}/audit-logs`, ({ request }) => {
        const page = Number(new URL(request.url).searchParams.get('page'))
        return HttpResponse.json({
          items: page === 1 ? [auditEntry(1)] : [],
          total: page === 1 ? 61 : 3,
          page,
          page_size: 10,
        })
      }),
    )
    renderPage()
    await screen.findByText('组织与角色')
    await userEvent.click(screen.getByRole('tab', { name: /审计与安全/ }))
    await screen.findByText('共 61 条')
    await userEvent.click(screen.getByTitle('6'))
    expect(await screen.findByText('当前页已超出审计目录范围')).toBeVisible()
    await userEvent.click(screen.getByRole('button', { name: '返回审计首页' }))
    expect(await screen.findByText('audit-resource-1')).toBeVisible()
  })

  it('resets audit scope and hides old details when switching to an organization denied by server', async () => {
    const otherId = '00000000-0000-4000-8000-000000000799'
    const reads: URL[] = []
    server.use(
      http.get('/api/v1/organizations', () =>
        HttpResponse.json([
          organization,
          { ...organization, id: otherId, name: '其他组织', slug: 'other-org' },
        ]),
      ),
      http.get(`/api/v1/organizations/${organizationId}/audit-logs`, ({ request }) => {
        const url = new URL(request.url)
        return HttpResponse.json({
          items: [auditEntry(Number(url.searchParams.get('page')))],
          total: 61,
          page: Number(url.searchParams.get('page')),
          page_size: 10,
        })
      }),
      http.get(`/api/v1/organizations/${otherId}/:path*`, ({ request }) => {
        reads.push(new URL(request.url))
        return HttpResponse.json(
          { error: { message: '其他组织读取被拒绝', trace_id: 'other-org-trace' } },
          { status: 403 },
        )
      }),
    )
    renderPage()
    await screen.findByText('组织与角色')
    await userEvent.click(screen.getByRole('tab', { name: /审计与安全/ }))
    await screen.findByText('共 61 条')
    await userEvent.click(screen.getByTitle('6'))
    await userEvent.click(await screen.findByRole('button', { name: '查看审计详情' }))
    expect(await screen.findByRole('dialog')).toHaveTextContent('audit-resource-6')
    await userEvent.click(screen.getByRole('button', { name: '关闭详情' }))
    await userEvent.click(screen.getByRole('combobox', { name: '治理组织' }))
    await userEvent.click(
      await screen.findByText('其他组织 · other-org', {
        selector: '.ant-select-item-option-content',
      }),
    )
    await screen.findByText('无权读取组织成员')
    await userEvent.click(screen.getByRole('tab', { name: /审计与安全/ }))
    expect(await screen.findByText('无权读取组织审计')).toBeVisible()
    expect(screen.queryByText('audit-resource-6')).not.toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    const auditRead = reads.find((url) => url.pathname.endsWith('/audit-logs'))
    expect(auditRead?.searchParams.get('page')).toBe('1')
    expect(auditRead?.searchParams.has('action')).toBe(false)
  })

  it('keeps failed member selection and role, disables repeated writes and resets after success', async () => {
    let failed = true
    let writes = 0
    let release: (() => void) | undefined
    server.use(
      http.post('/api/v1/users/search', () =>
        HttpResponse.json({
          items: [
            { ...user, display_name: '同名用户' },
            { ...user, id: organizationId, email: 'other@example.com', display_name: '同名用户' },
          ],
          total: 2,
          page: 1,
          page_size: 20,
        }),
      ),
      http.put(`/api/v1/organizations/${organizationId}/members/${user.id}`, async () => {
        writes += 1
        await new Promise<void>((resolve) => {
          release = resolve
        })
        return failed
          ? HttpResponse.json(
              { error: { message: '成员更新不可用', trace_id: 'member-trace' } },
              { status: 500 },
            )
          : HttpResponse.json(member)
      }),
    )
    renderPage()
    await screen.findByText('组织与角色')
    await userEvent.click(await screen.findByRole('combobox', { name: '组织用户' }))
    expect(await screen.findByText('同名用户 (other@example.com)')).toBeInTheDocument()
    await userEvent.click(screen.getByText(`同名用户 (${user.email})`))
    await userEvent.click(screen.getByRole('button', { name: '添加 / 更新' }))
    await waitFor(() => expect(writes).toBe(1))
    expect(screen.getByRole('button', { name: '添加 / 更新' })).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: '添加 / 更新' }))
    expect(writes).toBe(1)
    release?.()
    expect(await screen.findByText(/成员更新不可用.*member-trace/)).toBeVisible()
    expect(
      screen.getByRole('combobox', { name: '组织用户' }).closest('.ant-select'),
    ).toHaveTextContent(`同名用户 (${user.email})`)
    failed = false
    await userEvent.click(screen.getByRole('button', { name: '添加 / 更新' }))
    await waitFor(() => expect(writes).toBe(2))
    release?.()
    await waitFor(() =>
      expect(screen.queryByText(`同名用户 (${user.email})`)).not.toBeInTheDocument(),
    )
  })
})

function auditEntry(page: number) {
  return {
    id: `audit-${page}`,
    actor_user_id: user.id,
    organization_id: organizationId,
    project_id: null,
    action: 'organization.updated',
    resource_type: 'organization',
    resource_id: `audit-resource-${page}`,
    details: { trace_id: `audit-trace-${page}`, reason: '仅服务端已授权详情' },
    created_at: '2026-10-21T12:00:00Z',
  }
}

function readResponse(path: string) {
  if (path === 'audit-logs') return { items: [], total: 0, page: 1, page_size: 10 }
  if (path === 'runner-governance')
    return { pool_count: 0, runner_count: 0, current_load: 0, capacity: 0, pools: [] }
  if (path === 'security')
    return {
      active_key_version: 1,
      capability_name: 'Organization Data Encryption Key Rotation',
      capability_mode: 'reencrypt_verify_activate_rollback',
      ciphertext_reencryption_available: true,
      ga_blocker: null,
      key_versions: [],
    }
  return {
    schema_version: 'support-v1',
    data_classification: 'internal-redacted',
    included_sections: [],
    redacted_fields: [],
    excluded_fields: [],
  }
}

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
        capability_name: 'Organization Data Encryption Key Rotation',
        capability_mode: 'reencrypt_verify_activate_rollback',
        ciphertext_reencryption_available: true,
        ga_blocker: null,
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
