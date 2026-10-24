import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App as AntdApp } from 'antd'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'

import { useAuthStore } from '../features/auth/auth-store'
import { setOrganizationId } from '../lib/api'
import { authenticateTestUser } from '../test/auth'
import { user } from '../test/fixtures'
import { server } from '../test/server'
import OrganizationGovernancePage from './OrganizationGovernancePage'

const organizationId = '00000000-0000-4000-8000-000000000701'

describe('OrganizationGovernancePage', () => {
  beforeEach(() => {
    authenticateTestUser(user)
    setOrganizationId(null)
    installHandlers()
  })

  it('retains the explicitly selected organization after leaving governance', async () => {
    const view = renderPage()
    await screen.findByRole('combobox', { name: '治理组织' })
    await waitFor(() => expect(useAuthStore.getState().organizationId).toBe(organizationId))
    view.unmount()
    expect(useAuthStore.getState().organizationId).toBe(organizationId)
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

  it('offers supported MCP scopes and submits only explicitly selected compilation scopes', async () => {
    let submitted: Record<string, unknown> | undefined
    server.use(
      http.post(`/api/v1/organizations/${organizationId}/service-accounts`, async ({ request }) => {
        submitted = (await request.json()) as Record<string, unknown>
        return HttpResponse.json(
          { ...account, token: 'ftsa_scoped-compilation-fixture' },
          { status: 201 },
        )
      }),
    )
    renderPage()
    const browser = userEvent.setup()
    await screen.findByText('组织与角色')
    await browser.click(screen.getByRole('tab', { name: 'Service Account' }))
    const panel = screen.getByRole('tabpanel')
    await browser.type(within(panel).getByPlaceholderText('回归机器人'), '固定设计编译')
    await browser.type(within(panel).getByPlaceholderText('regression-bot'), 'design-compiler')
    await browser.click(within(panel).getByRole('button', { name: '签发令牌' }))
    expect(submitted).toBeUndefined()
    const scopeInput = within(panel).getByRole('combobox', { name: '权限范围' })
    for (const scope of [
      'org:key_rotate',
      'mcp:preview:execute',
      'mcp:project:bootstrap',
      'mcp:contract:import',
      'mcp:regression:prepare',
      'mcp:test-plan:propose',
    ]) {
      await browser.clear(scopeInput)
      fireEvent.mouseDown(scopeInput)
      await browser.type(scopeInput, scope, { skipClick: true })
      expect(
        await screen.findByText(scope, { selector: '.ant-select-item-option-content' }),
      ).toBeInTheDocument()
    }
    for (const scope of ['mcp:read', 'mcp:flow:propose']) {
      await browser.clear(scopeInput)
      await browser.type(scopeInput, scope)
      await browser.click(
        await screen.findByText(scope, { selector: '.ant-select-item-option-content' }),
      )
    }
    await browser.keyboard('{Escape}')
    expect(submitted).toBeUndefined()
    await browser.click(within(panel).getByRole('button', { name: '签发令牌' }))
    await screen.findByText('令牌只显示一次')
    expect(submitted).toMatchObject({
      name: '固定设计编译',
      account_key: 'design-compiler',
      scopes: ['mcp:read', 'mcp:flow:propose'],
    })
  })

  it.each(['member', 'viewer'] as const)(
    'does not expose service-account scope grants to organization %s',
    async (role) => {
      authenticateTestUser({ ...user, is_system_admin: false })
      let writes = 0
      server.use(
        http.get('/api/v1/organizations', () => HttpResponse.json([{ ...organization, role }])),
        http.post(`/api/v1/organizations/${organizationId}/service-accounts`, () => {
          writes += 1
          return HttpResponse.json({ ...account, token: 'ftsa_unreachable' }, { status: 201 })
        }),
      )
      renderPage()
      await screen.findByText('组织与角色')
      await userEvent.click(screen.getByRole('tab', { name: 'Service Account' }))
      expect(await screen.findByText(account.name)).toBeVisible()
      expect(screen.queryByRole('combobox', { name: '权限范围' })).not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: '签发令牌' })).not.toBeInTheDocument()
      expect(writes).toBe(0)
    },
  )

  it.each([403, 409, 503])(
    'retains account inputs after %s and clears them only after an explicit successful retry',
    async (status) => {
      let release!: () => void
      const response = new Promise<void>((resolve) => {
        release = resolve
      })
      let releaseSuccess!: () => void
      const successResponse = new Promise<void>((resolve) => {
        releaseSuccess = resolve
      })
      const submitted: unknown[] = []
      server.use(
        http.post(
          `/api/v1/organizations/${organizationId}/service-accounts`,
          async ({ request }) => {
            submitted.push(await request.json())
            if (submitted.length === 1) {
              await response
              return HttpResponse.json(
                {
                  error: {
                    code: 'ACCOUNT_UNAVAILABLE',
                    message: '账号签发暂不可用',
                    trace_id: 'account-failure',
                  },
                },
                { status },
              )
            }
            await successResponse
            return HttpResponse.json(
              { ...account, token: 'ftsa_synthetic-retry-token' },
              { status: 201 },
            )
          },
        ),
      )
      const rendered = renderPage()
      async function reloadAccounts(): Promise<void> {
        let releaseRead!: () => void
        const read = new Promise<void>((resolve) => {
          releaseRead = resolve
        })
        server.use(
          http.get(`/api/v1/organizations/${organizationId}/service-accounts`, async () => {
            await read
            return HttpResponse.json([account])
          }),
        )
        let completed!: Promise<void>
        act(() => {
          completed = rendered.queryClient.refetchQueries({
            queryKey: ['organization-service-accounts', organizationId],
          })
        })
        try {
          await screen.findByLabelText('正在加载服务账号')
          expect(screen.queryByPlaceholderText('回归机器人')).not.toBeInTheDocument()
        } finally {
          await act(async () => {
            releaseRead()
            await completed
          })
        }
        await screen.findByPlaceholderText('回归机器人')
      }
      const browser = userEvent.setup()
      await screen.findByText('组织与角色')
      await browser.click(screen.getByRole('tab', { name: 'Service Account' }))
      const panel = screen.getByRole('tabpanel')
      await fillAccountForm(browser, panel, 'Synthetic bot', 'synthetic-bot')
      const submit = () => within(panel).getByRole('button', { name: /签发令牌$/ })
      await browser.click(submit())
      await waitFor(() => expect(submitted).toHaveLength(1))
      try {
        if (status === 503) await reloadAccounts()
        expect(within(panel).getByPlaceholderText('回归机器人')).toHaveValue('Synthetic bot')
        expect(within(panel).getByPlaceholderText('regression-bot')).toHaveValue('synthetic-bot')
        expect(within(panel).getByPlaceholderText('回归机器人')).toBeDisabled()
        expect(within(panel).getByPlaceholderText('regression-bot')).toBeDisabled()
        expect(within(panel).getByRole('combobox')).toBeDisabled()
        await browser.click(within(panel).getByPlaceholderText('回归机器人'))
        await browser.keyboard('{End}x')
        await browser.click(submit())
        expect(submitted).toHaveLength(1)
      } finally {
        release()
      }
      expect(
        await within(panel).findByText('账号签发暂不可用（Trace ID: account-failure）'),
      ).toBeVisible()
      expect(within(panel).getByPlaceholderText('回归机器人')).toHaveValue('Synthetic bot')
      expect(within(panel).getByPlaceholderText('regression-bot')).toHaveValue('synthetic-bot')
      expect(
        within(panel).getByText('mcp:evidence:write', {
          selector: '.ant-select-selection-item-content',
        }),
      ).toBeVisible()
      expect(within(panel).getByPlaceholderText('回归机器人')).toBeEnabled()
      expect(screen.queryByText('令牌只显示一次')).not.toBeInTheDocument()
      expect(submitted).toEqual([
        {
          name: 'Synthetic bot',
          account_key: 'synthetic-bot',
          scopes: ['mcp:evidence:write'],
          metadata: {},
        },
      ])
      await browser.click(submit())
      await waitFor(() => expect(submitted).toHaveLength(2))
      try {
        if (status === 503) await reloadAccounts()
        expect(within(panel).getByPlaceholderText('回归机器人')).toHaveValue('Synthetic bot')
        expect(within(panel).getByPlaceholderText('regression-bot')).toHaveValue('synthetic-bot')
        expect(within(panel).getByPlaceholderText('回归机器人')).toBeDisabled()
        expect(screen.queryByText('令牌只显示一次')).not.toBeInTheDocument()
      } finally {
        releaseSuccess()
      }
      expect(await screen.findByText('ftsa_synthetic-retry-token')).toBeVisible()
      const refreshed = screen.getByRole('tabpanel')
      expect(within(refreshed).getByPlaceholderText('回归机器人')).toHaveValue('')
      expect(within(refreshed).getByPlaceholderText('regression-bot')).toHaveValue('')
      expect(
        within(refreshed).queryByText('mcp:evidence:write', {
          selector: '.ant-select-selection-item-content',
        }),
      ).not.toBeInTheDocument()
      expect(submitted).toHaveLength(2)
      expect(submitted[1]).toEqual(submitted[0])
      await browser.click(screen.getByRole('button', { name: '我已安全保存' }))
      expect(screen.queryByText('ftsa_synthetic-retry-token')).not.toBeInTheDocument()
    },
  )

  it.each(
    (['create', 'rotate', 'revoke'] as const).flatMap((command) =>
      (['organization', 'unmount'] as const).map((change) => ({ command, change })),
    ),
  )(
    'invalidates the original account catalog without revealing a late $command receipt after $change changes',
    async ({ command, change }) => {
      const otherId = '00000000-0000-4000-8000-000000000799'
      let release!: () => void
      const response = new Promise<void>((resolve) => {
        release = resolve
      })
      let writes = 0
      let applied = false
      let originalReads = 0
      const updated = changedServiceAccount(command)
      const endpoint = `/api/v1/organizations/${organizationId}/service-accounts`
      server.use(
        http.get('/api/v1/organizations', () =>
          HttpResponse.json([
            organization,
            { ...organization, id: otherId, name: '另一个组织', slug: 'other' },
          ]),
        ),
        http.get(endpoint, () => {
          originalReads += 1
          return HttpResponse.json(applied ? [updated] : [account])
        }),
        http.get(`/api/v1/organizations/${otherId}/members`, () => HttpResponse.json([])),
        http.get(`/api/v1/organizations/${otherId}/service-accounts`, () => HttpResponse.json([])),
        http.get(`/api/v1/organizations/${otherId}/governance`, () =>
          HttpResponse.json({ ...governance, organization_id: otherId }),
        ),
        ...['runner-governance', 'security', 'support-bundle/redaction'].map((path) =>
          http.get(`/api/v1/organizations/${otherId}/${path}`, () =>
            HttpResponse.json(readResponse(path)),
          ),
        ),
        http.post(
          command === 'create' ? endpoint : `${endpoint}/${account.id}/${command}`,
          async () => {
            writes += 1
            await response
            applied = true
            return accountCommandReceipt(command, updated)
          },
        ),
      )
      const rendered = renderPage(15_000)
      const browser = userEvent.setup()
      await screen.findByText('组织与角色')
      await browser.click(screen.getByRole('tab', { name: 'Service Account' }))
      const originalPanel = screen.getByRole('tabpanel')
      await within(originalPanel).findByText(account.name)
      const originalKey = ['organization-service-accounts', organizationId]
      expect(rendered.queryClient.getQueryState(originalKey)?.isInvalidated).toBe(false)
      expect(originalReads).toBe(1)
      await submitAccountCommand(browser, originalPanel, command)
      await waitFor(() => expect(writes).toBe(1))
      if (change === 'unmount') rendered.unmount()
      else {
        await browser.click(screen.getByRole('combobox', { name: '治理组织' }))
        await browser.click(
          await screen.findByText('另一个组织 · other', {
            selector: '.ant-select-item-option-content',
          }),
        )
        await browser.click(screen.getByRole('tab', { name: 'Service Account' }))
        await fillAccountForm(browser, screen.getByRole('tabpanel'), 'Current bot', 'current-bot')
      }
      await act(async () => {
        release()
        await response
      })
      await waitFor(() =>
        expect(
          rendered.queryClient
            .getMutationCache()
            .getAll()
            .every((mutation) => mutation.state.status !== 'pending'),
        ).toBe(true),
      )
      expect.soft(rendered.queryClient.getQueryState(originalKey)?.isInvalidated).toBe(true)
      expect(screen.queryByText('ftsa_synthetic-old-receipt')).not.toBeInTheDocument()
      for (const text of [
        'Service Account 已创建，令牌只显示一次',
        'Service Account 令牌已轮换',
        'Service Account 已撤销',
        'Service Account 创建失败',
        'Service Account 轮换失败',
        'Service Account 撤销失败',
      ])
        expect(screen.queryByText(text)).not.toBeInTheDocument()
      if (change === 'organization') {
        expect(
          rendered.queryClient.getQueryState(['organization-service-accounts', otherId])
            ?.isInvalidated,
        ).toBe(false)
        const panel = screen.getByRole('tabpanel')
        expect(within(panel).getByPlaceholderText('回归机器人')).toHaveValue('Current bot')
        expect(within(panel).getByPlaceholderText('regression-bot')).toHaveValue('current-bot')
        await browser.click(screen.getByRole('combobox', { name: '治理组织' }))
        await browser.click(
          await screen.findByText('Governed Organization · governed-org', {
            selector: '.ant-select-item-option-content',
          }),
        )
        await browser.click(screen.getByRole('tab', { name: 'Service Account' }))
        await waitFor(() => expect(originalReads).toBe(2))
        const refreshed = await screen.findByRole('tabpanel')
        if (command === 'create')
          expect(await within(refreshed).findByText(updated.name)).toBeVisible()
        else if (command === 'rotate')
          expect(await within(refreshed).findByText(updated.token_prefix)).toBeVisible()
        else expect(await within(refreshed).findByText('已撤销')).toBeVisible()
      }
      expect(writes).toBe(1)
    },
  )

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

  it.each(['admin', 'owner'] as const)(
    'refreshes the current %s role and permission controls after self-demotion',
    async (initialRole) => {
      authenticateTestUser({ ...user, is_system_admin: false })
      let currentRole: 'admin' | 'owner' | 'viewer' = initialRole
      let directoryReads = 0
      const submissions: unknown[] = []
      server.use(
        http.get('/api/v1/organizations', () => {
          directoryReads += 1
          return HttpResponse.json([{ ...organization, role: currentRole, member_count: 2 }])
        }),
        http.get(`/api/v1/organizations/${organizationId}/members`, () =>
          HttpResponse.json([
            { ...member, role: currentRole },
            { ...member, id: 'other-owner', user_id: organizationId, role: 'owner' },
          ]),
        ),
        http.put(
          `/api/v1/organizations/${organizationId}/members/${user.id}`,
          async ({ request }) => {
            submissions.push(await request.json())
            currentRole = 'viewer'
            return HttpResponse.json({ ...member, role: currentRole })
          },
        ),
      )
      renderPage()
      const browser = userEvent.setup()
      await screen.findByText('当前角色')
      const organizationInfo = within(screen.getByText('当前角色').closest('table') as HTMLElement)
      expect(organizationInfo.getByText(initialRole)).toBeVisible()
      await browser.click(screen.getByRole('tab', { name: /审计与安全/ }))
      await screen.findByText('密钥轮换能力已确认')
      if (initialRole === 'owner')
        expect(screen.getByRole('button', { name: '创建轮换版本' })).toBeVisible()
      await browser.click(screen.getByRole('tab', { name: /组织与角色/ }))
      await browser.click(screen.getByRole('combobox', { name: `更新 ${user.id} 角色` }))
      await browser.click(
        screen.getByText('只读成员 Viewer', { selector: '.ant-select-item-option-content' }),
      )

      await waitFor(() =>
        expect(
          within(screen.getByText('当前角色').closest('table') as HTMLElement).getByText('viewer'),
        ).toBeVisible(),
      )
      expect(directoryReads).toBe(2)
      expect(submissions).toEqual([{ user_id: user.id, role: 'viewer' }])
      expect(screen.getByRole('combobox', { name: `更新 ${user.id} 角色` })).toBeDisabled()
      expect(screen.queryByRole('button', { name: '添加 / 更新' })).not.toBeInTheDocument()
      await browser.click(screen.getByRole('tab', { name: 'Service Account' }))
      const accounts = within(screen.getByRole('tabpanel'))
      expect(accounts.queryByRole('button', { name: '签发令牌' })).not.toBeInTheDocument()
      expect(accounts.queryByRole('button', { name: '轮换' })).not.toBeInTheDocument()
      expect(accounts.queryByRole('button', { name: '撤销' })).not.toBeInTheDocument()
      await browser.click(screen.getByRole('tab', { name: '配额与 Runner' }))
      expect(screen.queryByRole('button', { name: '保存治理策略' })).not.toBeInTheDocument()
      await browser.click(screen.getByRole('tab', { name: /审计与安全/ }))
      expect(screen.queryByRole('button', { name: '创建轮换版本' })).not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: 'Apply' })).not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: 'Rollback' })).not.toBeInTheDocument()
      expect(submissions).toHaveLength(1)
    },
  )

  it('keeps a self-demotion pending until the organization directory finishes refreshing', async () => {
    authenticateTestUser({ ...user, is_system_admin: false })
    let writes = 0
    let releaseDirectory: (() => void) | undefined
    server.use(
      http.get('/api/v1/organizations', async () => {
        if (writes) {
          await new Promise<void>((resolve) => {
            releaseDirectory = resolve
          })
        }
        return HttpResponse.json([{ ...organization, role: writes ? 'viewer' : 'admin' }])
      }),
      http.get(`/api/v1/organizations/${organizationId}/members`, () =>
        HttpResponse.json([{ ...member, role: writes ? 'viewer' : 'admin' }]),
      ),
      http.put(`/api/v1/organizations/${organizationId}/members/${user.id}`, () => {
        writes += 1
        return HttpResponse.json({ ...member, role: 'viewer' })
      }),
    )
    renderPage()
    const browser = userEvent.setup()
    await browser.click(await screen.findByRole('combobox', { name: `更新 ${user.id} 角色` }))
    await browser.click(
      screen.getByText('只读成员 Viewer', { selector: '.ant-select-item-option-content' }),
    )
    try {
      await waitFor(() => expect(releaseDirectory).toBeTypeOf('function'))
      const selfRole = await screen.findByRole('combobox', { name: `更新 ${user.id} 角色` })
      expect(selfRole).toBeDisabled()
      const submit = screen.getByRole('button', { name: '添加 / 更新' })
      expect(submit).toBeDisabled()
      await browser.click(submit)
      expect(writes).toBe(1)
      expect(screen.queryByText('组织角色已更新')).not.toBeInTheDocument()
    } finally {
      await act(async () => releaseDirectory?.())
    }
    await waitFor(() =>
      expect(
        within(screen.getByText('当前角色').closest('table') as HTMLElement).getByText('viewer'),
      ).toBeVisible(),
    )
    expect(screen.queryByRole('button', { name: '添加 / 更新' })).not.toBeInTheDocument()
    expect(writes).toBe(1)
  })

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
    const browser = userEvent.setup()
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
    const auditTab = screen.getByText('审计与安全').closest('[role="tab"]')!
    expect(auditTab).toHaveRole('tab')
    expect(auditTab).toHaveAccessibleName(/审计与安全/)
    expect(auditTab).toBeVisible()
    expect(auditTab.closest('[aria-hidden="true"]')).toBeNull()
    await browser.click(auditTab)
    expect(await screen.findByText('共 61 条')).toBeVisible()
    const audit = within(screen.getByText('组织审计查询').closest('.ant-card')!)
    await browser.click(audit.getByTitle('6'))
    const resource = await audit.findByText('audit-resource-6')
    expect(resource).toBeVisible()
    expect(requests.at(-1)?.searchParams.get('page')).toBe('6')
    const view = within(resource.closest('tr')!).getByLabelText('查看审计详情', {
      selector: 'button',
    })
    expect(view).toHaveRole('button')
    expect(view).toHaveAccessibleName('查看审计详情')
    expect(view).toBeVisible()
    expect(view.closest('[aria-hidden="true"]')).toBeNull()
    await browser.click(view)
    const details = await screen.findByRole('dialog')
    expect(details).toHaveTextContent('audit-trace-6')
    expect(details).toHaveTextContent('仅服务端已授权详情')
    await browser.click(within(details).getByRole('button', { name: '关闭详情' }))
    for (const [label, value] of [
      ['审计动作', 'organization.updated'],
      ['操作者 ID', user.id],
      ['资源类型', 'organization'],
      ['资源 ID', organizationId],
    ] as const) {
      await browser.click(audit.getByLabelText(label))
      await browser.paste(value)
    }
    fireEvent.change(audit.getByLabelText('开始时间'), { target: { value: '2026-10-01T12:00' } })
    fireEvent.change(audit.getByLabelText('结束时间'), { target: { value: '2026-10-21T12:00' } })
    await browser.click(audit.getByRole('button', { name: '查询审计' }))
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
    const browser = userEvent.setup()
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
    const auditTab = screen.getByText('审计与安全').closest('[role="tab"]')!
    expect(auditTab).toHaveRole('tab')
    expect(auditTab).toHaveAccessibleName(/审计与安全/)
    expect(auditTab).toBeVisible()
    expect(auditTab.closest('[aria-hidden="true"]')).toBeNull()
    await browser.click(auditTab)
    await screen.findByText('共 61 条')
    const audit = within(screen.getByText('组织审计查询').closest('.ant-card')!)
    await browser.click(audit.getByTitle('6'))
    const resource = await audit.findByText('audit-resource-6')
    expect(resource).toBeVisible()
    const view = within(resource.closest('tr')!).getByLabelText('查看审计详情', {
      selector: 'button',
    })
    expect(view).toHaveRole('button')
    expect(view).toHaveAccessibleName('查看审计详情')
    expect(view).toBeVisible()
    expect(view.closest('[aria-hidden="true"]')).toBeNull()
    await browser.click(view)
    const details = await screen.findByRole('dialog')
    expect(details).toHaveTextContent('audit-resource-6')
    await browser.click(within(details).getByRole('button', { name: '关闭详情' }))
    await browser.click(screen.getByRole('combobox', { name: '治理组织' }))
    await browser.click(
      await screen.findByText('其他组织 · other-org', {
        selector: '.ant-select-item-option-content',
      }),
    )
    await screen.findByText('无权读取组织成员')
    const otherAuditTab = screen.getByText('审计与安全').closest('[role="tab"]')!
    expect(otherAuditTab).toHaveRole('tab')
    expect(otherAuditTab).toHaveAccessibleName(/审计与安全/)
    expect(otherAuditTab).toBeVisible()
    expect(otherAuditTab.closest('[aria-hidden="true"]')).toBeNull()
    await browser.click(otherAuditTab)
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

  it.each(['directory', 'advanced'] as const)(
    'locks the system administrator %s picker until the member update finishes',
    async (mode) => {
      let writes = 0
      let submitted: unknown
      let release: (() => void) | undefined
      server.use(
        http.post('/api/v1/users/search', () =>
          HttpResponse.json({ items: [user], total: 1, page: 1, page_size: 20 }),
        ),
        http.put(
          `/api/v1/organizations/${organizationId}/members/${user.id}`,
          async ({ request }) => {
            writes += 1
            submitted = await request.json()
            await new Promise<void>((resolve) => {
              release = resolve
            })
            return HttpResponse.json(member)
          },
        ),
      )
      renderPage()
      const browser = userEvent.setup()
      await screen.findByRole('combobox', { name: '组织用户' })
      if (mode === 'advanced') {
        await browser.click(screen.getByRole('button', { name: '按 ID 输入' }))
        await browser.type(screen.getByRole('textbox', { name: '组织用户 ID' }), user.id)
      } else {
        await browser.click(screen.getByRole('combobox', { name: '组织用户' }))
        await browser.click(await screen.findByText(`${user.display_name} (${user.email})`))
      }
      await browser.click(screen.getByRole('button', { name: '添加 / 更新' }))
      await waitFor(() => expect(writes).toBe(1))
      const input =
        mode === 'advanced'
          ? screen.getByRole('textbox', { name: '组织用户 ID' })
          : screen.getByRole('combobox', { name: '组织用户' })
      expect(input).toBeDisabled()
      expect(screen.getByRole('button', { name: /按 ID 输入|返回名称搜索/ })).toBeDisabled()
      expect(screen.getByRole('combobox', { name: '成员角色' })).toBeDisabled()
      await browser.type(input, 'unsubmitted-user', { skipClick: true })
      expect(input).toHaveValue(mode === 'advanced' ? user.id : '')
      await browser.click(screen.getByRole('button', { name: '添加 / 更新' }))
      expect(writes).toBe(1)
      expect(submitted).toEqual({ user_id: user.id, role: 'member' })
      await act(async () => release?.())
      await waitFor(() => expect(screen.getByRole('button', { name: '添加 / 更新' })).toBeEnabled())
      const cleared = screen.getByRole('combobox', { name: '组织用户' })
      expect(cleared).toHaveValue('')
      expect(cleared.closest('.ant-select')).not.toHaveTextContent(user.email)
      expect(writes).toBe(1)
    },
  )
})

async function fillAccountForm(
  browser: ReturnType<typeof userEvent.setup>,
  panel: HTMLElement,
  name: string,
  key: string,
) {
  await browser.click(within(panel).getByPlaceholderText('回归机器人'))
  await browser.paste(name)
  await browser.click(within(panel).getByPlaceholderText('regression-bot'))
  await browser.paste(key)
  const scope = within(panel).getByRole('combobox')
  await browser.click(scope)
  await browser.type(scope, 'mcp:evidence:write')
  await browser.click(
    await screen.findByText('mcp:evidence:write', { selector: '.ant-select-item-option-content' }),
  )
}

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

function renderPage(staleTime = 0) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime }, mutations: { retry: false } },
  })
  return {
    queryClient,
    ...render(
      <AntdApp>
        <QueryClientProvider client={queryClient}>
          <OrganizationGovernancePage />
        </QueryClientProvider>
      </AntdApp>,
    ),
  }
}

function changedServiceAccount(command: 'create' | 'rotate' | 'revoke'): typeof account {
  return {
    ...account,
    id: command === 'create' ? 'new-account' : account.id,
    name: command === 'create' ? 'Late created bot' : account.name,
    token_prefix: command === 'rotate' ? 'ftsa_synthetic_rotated' : account.token_prefix,
    enabled: command !== 'revoke',
  }
}

function accountCommandReceipt(
  command: 'create' | 'rotate' | 'revoke',
  updated: typeof account,
): Response {
  return HttpResponse.json(
    command === 'revoke' ? updated : { ...updated, token: 'ftsa_synthetic-old-receipt' },
    { status: command === 'create' ? 201 : 200 },
  )
}

async function submitAccountCommand(
  browser: ReturnType<typeof userEvent.setup>,
  panel: HTMLElement,
  command: 'create' | 'rotate' | 'revoke',
): Promise<void> {
  if (command === 'create') {
    await fillAccountForm(browser, panel, 'Original bot', 'original-bot')
    await browser.click(within(panel).getByRole('button', { name: '签发令牌' }))
  } else {
    const row = within(panel).getByText(account.name).closest('tr') as HTMLElement
    const label = command === 'rotate' ? /轮\s*换/ : /撤\s*销/
    const text = within(row).getByText(label, { selector: 'button span' })
    const action = text.closest('button') as HTMLButtonElement
    expect(action).toHaveRole('button')
    expect(action).toHaveAccessibleName(label)
    expect(panel).toBeVisible()
    expect(action).not.toHaveAttribute('hidden')
    expect(action).not.toHaveAttribute('aria-hidden')
    expect(action.closest('[aria-hidden="true"]')).toBeNull()
    expect(action).toBeEnabled()
    action.focus()
    expect(action).toHaveFocus()
    await browser.keyboard('{Enter}')
  }
}
