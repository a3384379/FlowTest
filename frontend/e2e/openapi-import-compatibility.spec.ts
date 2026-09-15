import { expect, test } from '@playwright/test'
import { resolve } from 'node:path'

import { activePassword, administratorEmail } from './support/auth'

test('Swagger 兼容导入生成八个 Diff 并显示 definition 诊断', async ({ page }) => {
  const login = await page.request.post('/api/v1/auth/login', {
    data: { email: administratorEmail, password: activePassword },
  })
  expect(login.ok()).toBeTruthy()
  const { access_token: token } = await login.json()
  const created = await page.request.post('/api/v1/projects', {
    headers: { Authorization: `Bearer ${token}` },
    data: { name: `OpenAPI compatibility ${Date.now()}`, description: '匿名回归验收' },
  })
  expect(created.status()).toBe(201)
  const project = await created.json()
  await page.goto(`/projects/${project.id}/apis`)
  await page.getByRole('button', { name: '导入接口' }).click()
  await page
    .getByRole('dialog', { name: '导入接口文档' })
    .locator('input[type="file"]')
    .setInputFiles(resolve('../backend/tests/fixtures/importers/swagger2-compatibility.yaml'))
  const response = page.waitForResponse(
    (item) => item.url().includes('/imports/preview') && item.request().method() === 'POST',
  )
  await page.getByRole('button', { name: '生成 Diff' }).click()
  const preview = await response
  expect(preview.status()).toBe(201)
  const result = await preview.json()
  expect(result.results).toHaveLength(8)
  await page.getByText(/已兼容导入，发现/).click()
  await expect(
    page.getByText(/JscpcoChargeRentBillItemDataFeeStandardDto\/properties/),
  ).toBeVisible()
  await expect(page.getByRole('button', { name: '合并所选' })).toBeEnabled()
})
