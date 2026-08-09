import { expect, test } from '@playwright/test'
import { mkdir } from 'node:fs/promises'

import {
  activePassword,
  administratorEmail,
  authenticationStatePath,
  bootstrapPassword,
  submitLogin,
} from './support/auth'

test('管理员登录并完成首次密码初始化', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('邮箱').fill(administratorEmail)
  let loginResponse = await submitLogin(page, bootstrapPassword)
  if (!loginResponse.ok() && activePassword !== bootstrapPassword) {
    loginResponse = await submitLogin(page, activePassword)
  }
  expect(loginResponse.ok()).toBeTruthy()
  const login = (await loginResponse.json()) as { user: { requires_password_change: boolean } }

  if (login.user.requires_password_change) {
    await expect(page.getByRole('heading', { name: '首次登录，请修改密码' })).toBeVisible()
    await page.getByLabel('当前密码').fill(bootstrapPassword)
    await page.getByLabel('新密码', { exact: true }).fill(activePassword)
    await page.getByLabel('确认新密码').fill(activePassword)
    const changeResponsePromise = page.waitForResponse(
      (response) =>
        response.url().endsWith('/api/v1/auth/change-password') &&
        response.request().method() === 'POST',
    )
    await page.getByRole('button', { name: '保存并进入平台' }).click()
    expect((await changeResponsePromise).ok()).toBeTruthy()

    // Password changes revoke every refresh session. Log in again to verify the
    // new credential and finish setup with a valid browser session.
    await page.context().clearCookies()
    await page.reload()
    await page.getByLabel('邮箱').fill(administratorEmail)
    expect((await submitLogin(page, activePassword)).ok()).toBeTruthy()
  }

  await expect(page.getByRole('heading', { name: '工作台' })).toBeVisible()
  await mkdir('.playwright/.auth', { recursive: true })
  await page.context().storageState({ path: authenticationStatePath })
})
