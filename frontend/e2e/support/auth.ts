import { expect, type Page, type Response } from '@playwright/test'

export const administratorEmail = process.env.FLOWTEST_E2E_ADMIN_EMAIL ?? 'admin@flowtest.dev'
export const activePassword = process.env.FLOWTEST_E2E_ACTIVE_PASSWORD ?? 'FlowTest-E2E-Admin-123!'
export const bootstrapPassword =
  process.env.FLOWTEST_E2E_BOOTSTRAP_PASSWORD ?? 'FlowTest-Change-Me-123!'
export const authenticationStatePath = '.playwright/.auth/administrator.json'

export async function authenticate(page: Page): Promise<void> {
  const dashboard = page.getByRole('heading', { name: '工作台' })
  const login = page.getByRole('heading', { name: '登录账号' })
  await expect(dashboard.or(login)).toBeVisible()
  if (await dashboard.isVisible()) return

  await page.getByLabel('邮箱').fill(administratorEmail)
  let response = await submitLogin(page, activePassword)
  if (!response.ok() && activePassword !== bootstrapPassword) {
    response = await submitLogin(page, bootstrapPassword)
  }
  expect(response.ok()).toBeTruthy()
  await expect(dashboard).toBeVisible()
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
