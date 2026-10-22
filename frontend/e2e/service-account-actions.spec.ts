import { randomUUID } from 'node:crypto'
import {
  expect,
  test,
  type APIRequestContext,
  type Locator,
  type Page,
  type Response,
} from '@playwright/test'

import { authenticate } from './support/auth'

type AccountMetadata = { id: string; token_prefix: string; enabled: boolean }
type AccountFixture = {
  organizationId: string
  organizationName: string
  slug: string
  accountName: string
  account: AccountMetadata
  headers: { Authorization: string }
}

// This flow issues a one-time credential. Keep it out of browser artifacts.
test.use({
  storageState: { cookies: [], origins: [] },
  trace: 'off',
  screenshot: 'off',
  video: 'off',
})

test.afterEach(async ({ page }) => {
  // Playwright also takes a fallback ARIA snapshot when a failed context closes.
  if (!page.isClosed()) await page.close()
})

test('组织 Service Account 操作在完整页面可见并支持键盘轮换与撤销', async ({ page }) => {
  await page.goto('/')
  await authenticate(page)
  const fixture = await createAccountFixture(page.request)
  await page.goto('/organization')
  await expect(page.getByRole('heading', { name: '组织治理' })).toBeVisible()
  await page.getByRole('combobox', { name: '治理组织' }).click()
  await page
    .locator('.ant-select-dropdown:visible')
    .getByText(`${fixture.organizationName} · ${fixture.slug}`, { exact: true })
    .click()
  await page.getByRole('tab', { name: 'Service Account', exact: true }).click()

  const panel = page.getByRole('tabpanel', { name: 'Service Account', exact: true })
  const row = panel.getByRole('row').filter({ hasText: fixture.accountName })
  await expect(panel).toBeVisible()
  await expect(row).toBeVisible()
  await expect(row).toContainText(fixture.account.token_prefix)
  await expect(row.getByText('启用', { exact: true })).toBeVisible()

  const base = `/api/v1/organizations/${fixture.organizationId}/service-accounts`
  const rotatePath = `${base}/${fixture.account.id}/rotate`
  const revokePath = `${base}/${fixture.account.id}/revoke`
  const actionPosts: string[] = []
  page.on('request', (request) => {
    const path = new URL(request.url()).pathname
    if (request.method() === 'POST' && [rotatePath, revokePath].includes(path))
      actionPosts.push(path)
  })

  const rotate = row.getByRole('button', { name: /^轮\s*换$/ })
  await expectReadyAction(rotate)
  const [rotated, rotationRefresh] = await Promise.all([
    responseFor(page, rotatePath, 'POST'),
    responseFor(page, base, 'GET'),
    rotate.press('Enter'),
  ])
  expect(rotated.status()).toBe(200)
  expect(rotated.request().headers()['x-organization-id']).toBe(fixture.organizationId)
  const rotatedAccount = (await rotated.json()) as AccountMetadata
  expect(rotatedAccount.id).toBe(fixture.account.id)
  expect(rotatedAccount.enabled).toBe(true)
  expect(rotatedAccount.token_prefix).not.toBe(fixture.account.token_prefix)
  expect(rotationRefresh.status()).toBe(200)
  await expect(row).toContainText(rotatedAccount.token_prefix)
  await page.getByRole('button', { name: '我已安全保存', exact: true }).click()
  await expect(page.getByText('令牌只显示一次', { exact: true })).toHaveCount(0)

  const revoke = row.getByRole('button', { name: /^撤\s*销$/ })
  await expectReadyAction(revoke)
  const [revoked, revocationRefresh] = await Promise.all([
    responseFor(page, revokePath, 'POST'),
    responseFor(page, base, 'GET'),
    revoke.press('Enter'),
  ])
  expect(revoked.status()).toBe(200)
  expect(revoked.request().headers()['x-organization-id']).toBe(fixture.organizationId)
  const revokedAccount = (await revoked.json()) as AccountMetadata
  expect(revokedAccount.id).toBe(fixture.account.id)
  expect(revokedAccount.enabled).toBe(false)
  expect(revocationRefresh.status()).toBe(200)
  await expect(row.getByText('已撤销', { exact: true })).toBeVisible()
  await expect(revoke).toBeVisible()
  await expect(revoke).toBeDisabled()
  expect(actionPosts).toEqual([rotatePath, revokePath])

  const persisted = await page.request.get(base, { headers: fixture.headers })
  expect(persisted.status()).toBe(200)
  const accounts = (await persisted.json()) as AccountMetadata[]
  expect(accounts.find((account) => account.id === fixture.account.id)?.enabled).toBe(false)
})

async function expectReadyAction(action: Locator): Promise<void> {
  await expect(action).toBeVisible()
  await expect(action).toBeEnabled()
  const ancestorsVisible = await action.evaluate((element) => {
    for (let current: Element | null = element; current; current = current.parentElement) {
      const style = getComputedStyle(current)
      if (
        current.hasAttribute('hidden') ||
        style.display === 'none' ||
        ['hidden', 'collapse'].includes(style.visibility) ||
        style.contentVisibility === 'hidden' ||
        Number(style.opacity) === 0
      )
        return false
    }
    return true
  })
  expect(ancestorsVisible).toBe(true)
  await action.focus()
  await expect(action).toBeFocused()
}

function responseFor(page: Page, path: string, method: 'GET' | 'POST'): Promise<Response> {
  return page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === path && response.request().method() === method,
  )
}

async function createAccountFixture(request: APIRequestContext): Promise<AccountFixture> {
  const refreshed = await request.post('/api/v1/auth/refresh', {
    headers: { 'X-Requested-With': 'FlowTest' },
  })
  expect(refreshed.status()).toBe(200)
  const { access_token: token } = (await refreshed.json()) as { access_token: string }
  const headers = { Authorization: `Bearer ${token}` }
  const suffix = randomUUID()
  const organizationName = `000 Service Account 浏览器验收 ${suffix}`
  const slug = `e2e-service-actions-${suffix}`
  const createdOrganization = await request.post('/api/v1/organizations', {
    headers,
    data: { name: organizationName, slug },
  })
  expect(createdOrganization.status()).toBe(201)
  const { id: organizationId } = (await createdOrganization.json()) as { id: string }
  const accountName = `Service Account 操作 ${suffix}`
  const createdAccount = await request.post(
    `/api/v1/organizations/${organizationId}/service-accounts`,
    {
      headers,
      data: {
        name: accountName,
        account_key: `e2e-actions-${suffix}`,
        scopes: ['project:read'],
        metadata: {},
      },
    },
  )
  expect(createdAccount.status()).toBe(201)
  const { id, token_prefix, enabled } = (await createdAccount.json()) as AccountMetadata
  return {
    organizationId,
    organizationName,
    slug,
    accountName,
    account: { id, token_prefix, enabled },
    headers,
  }
}
