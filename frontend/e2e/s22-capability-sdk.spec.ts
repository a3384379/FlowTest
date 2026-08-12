import { expect, test } from '@playwright/test'

import { authenticate } from './support/auth'

test('S22 能力版本、安全边界与平台深链接主路径', async ({ page }) => {
  await page.goto('/')
  await authenticate(page)

  await page.getByRole('link', { name: '平台管理' }).click()
  await expect(page).toHaveURL(/\/platform$/)
  await expect(page.getByRole('heading', { name: '能力与插件中心' })).toBeVisible()
  const httpCapability = page.getByRole('row').filter({ hasText: 'http.request' })
  if (!(await httpCapability.isVisible())) {
    await page.getByTitle('2').click()
  }
  await expect(httpCapability).toContainText('HTTP 请求')
  await expect(page.getByText('固定 Schema 哈希')).toBeVisible()
  await expect(page.getByText(/插件不会获得 Secret 明文/)).toBeVisible()
  await expect(page.getByRole('button', { name: '安装签名插件' })).toBeDisabled()

  await page.reload()
  await expect(page).toHaveURL(/\/platform$/)
  await expect(page.getByRole('heading', { name: '能力与插件中心' })).toBeVisible()

  await page.getByTitle('插件').click()
  await expect(page.getByText('尚未安装管理员签名插件')).toBeVisible()
  await page.getByTitle('Runner').click()
  await expect(page.getByText('Runner Fabric 尚未启用')).toBeVisible()
})
