import { navigateMenu } from './support/navigation'
import { expect, test } from '@playwright/test'

import type { Capability } from '../src/features/capabilities/capability-service'
import { authenticate } from './support/auth'

test('S22 能力版本、安全边界与平台深链接主路径', async ({ page }) => {
  await page.goto('/')
  await authenticate(page)

  await navigateMenu(page, '平台管理')
  await expect(page).toHaveURL(/\/platform$/)
  await expect(page.getByRole('heading', { name: '能力与插件中心' })).toBeVisible()
  await expect(page.locator('.v3-platform-table .ant-table-row').first()).toBeVisible()
  const httpCapability = page.getByRole('row').filter({ hasText: 'http.request' })
  for (let pageNumber = 1; pageNumber < 10 && !(await httpCapability.isVisible()); pageNumber++) {
    const next = page.locator(
      '.v3-platform-table .ant-pagination-next:not(.ant-pagination-disabled)',
    )
    if (!(await next.count())) break
    await next.click()
    await expect(page.locator('.v3-platform-table .ant-pagination-item-active')).toHaveText(
      String(pageNumber + 1),
    )
  }
  await expect(httpCapability).toContainText('HTTP 请求')
  const inspector = page.getByRole('complementary', { name: '平台对象检查器' })
  await expect(inspector.getByText('选择当前库存对象查看详情')).toBeVisible()
  const detailResponse = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname.startsWith('/api/v1/capabilities/http.request/versions/') &&
      response.request().method() === 'GET',
  )
  await httpCapability.getByRole('button', { name: 'HTTP 请求', exact: true }).click()
  const response = await detailResponse
  expect(response.ok()).toBeTruthy()
  const capability: Capability = await response.json()
  expect(capability.id).toBe('http.request')
  expect(capability.schema_hash).toMatch(/^[a-f0-9]{64}$/)
  await expect(
    inspector.getByText(`${capability.id}@${capability.version}`, { exact: true }),
  ).toBeVisible()
  await expect(inspector.getByText(capability.schema_hash, { exact: true })).toBeVisible()
  await inspector.getByRole('tab', { name: '策略与来源' }).click()
  expect(capability.manifest.snapshot_policy.include_schema_hash).toBe(true)
  await expect(
    inspector.locator('.ant-descriptions-row').filter({ hasText: 'Snapshot 固定 Schema 哈希' }),
  ).toContainText('是')
  expect(capability.manifest.snapshot_policy.credential_material).toBe('encrypted')
  await expect(
    inspector.locator('.ant-descriptions-row').filter({ hasText: 'Snapshot 凭据材料策略' }),
  ).toContainText(capability.manifest.snapshot_policy.credential_material)
  await expect(
    inspector.getByText('以下为能力声明的策略；实际诊断采集按安装与请求级项目策略执行'),
  ).toBeVisible()
  await expect(page.getByRole('button', { name: '安装签名插件' })).toBeDisabled()

  const selectedUrl = page.url()
  expect(new URL(selectedUrl).searchParams.get('id')).toBe(capability.id)
  expect(new URL(selectedUrl).searchParams.get('version')).toBe(capability.version)
  await page.reload()
  await expect(page).toHaveURL(selectedUrl)
  await expect(page.getByRole('heading', { name: '能力与插件中心' })).toBeVisible()
  await expect(
    inspector.getByText(`${capability.id}@${capability.version}`, { exact: true }),
  ).toBeVisible()
  await expect(inspector.getByText(capability.schema_hash, { exact: true })).toBeVisible()

  await page.getByTitle('插件').click()
  await expect(
    page.getByText('尚未安装管理员签名插件或没有匹配结果', { exact: true }),
  ).toBeVisible()
  await expect(inspector.getByText('选择当前库存对象查看详情')).toBeVisible()
  await expect(
    inspector.getByText(`${capability.id}@${capability.version}`, { exact: true }),
  ).toHaveCount(0)
  await page.getByTitle('Runner').click()
  await expect(page.getByRole('columnheader', { name: '池名称' })).toBeVisible()
  await expect(page.getByRole('columnheader', { name: '网络区' })).toBeVisible()
  await expect(inspector.getByText('选择当前库存对象查看详情')).toBeVisible()
})
