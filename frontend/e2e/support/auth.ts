import { expect, type Page, type Response } from '@playwright/test'

export const administratorEmail = process.env.FLOWTEST_E2E_ADMIN_EMAIL ?? 'admin@flowtest.dev'
export const activePassword = process.env.FLOWTEST_E2E_ACTIVE_PASSWORD ?? 'FlowTest-E2E-Admin-123!'
export const bootstrapPassword = process.env.FLOWTEST_E2E_BOOTSTRAP_PASSWORD ?? 'admin123456'
export const authenticationStatePath = '.playwright/.auth/administrator.json'

export async function authenticate(page: Page): Promise<void> {
  const authenticatedShell = page.getByRole('button', { name: '退出' })
  const login = page.getByRole('heading', { name: '登录账号' })
  const reconnect = page.getByRole('button', { name: '重试连接' })
  await expect(authenticatedShell.or(login).or(reconnect)).toBeVisible()
  if (await reconnect.isVisible()) {
    // Saved setup cookies can already have rotated in a previous test context.
    // Start a new session through the normal login UI instead of reusing them.
    await page.context().clearCookies()
    await page.reload()
    await expect(login).toBeVisible()
  }
  if (await authenticatedShell.isVisible()) return

  await page.getByLabel('账号').fill(administratorEmail)
  let response = await submitLogin(page, activePassword)
  if (!response.ok() && activePassword !== bootstrapPassword) {
    response = await submitLogin(page, bootstrapPassword)
  }
  expect(response.ok()).toBeTruthy()
  await expect(authenticatedShell).toBeVisible()
}

export async function submitLogin(page: Page, password: string): Promise<Response> {
  await page.getByLabel('密码').fill(password)
  const response = page.waitForResponse(
    (candidate) =>
      candidate.url().endsWith('/api/v1/auth/login') && candidate.request().method() === 'POST',
  )
  await page.getByRole('button', { name: /登\s*录/ }).click()
  return response
}
