import { expect, test, type Page } from '@playwright/test'

import { authenticate } from './support/auth'

test('S15 用例、套件、版本 Diff 与固定计划目标主路径', async ({ page }) => {
  test.setTimeout(90_000)
  const suffix = Date.now().toString()
  const caseName = `S15 登录用例 ${suffix}`
  const suiteName = `S15 冒烟套件 ${suffix}`
  const planName = `S15 固定套件计划 ${suffix}`

  await page.goto('/')
  await authenticate(page)
  await page.getByRole('link', { name: '测试资产' }).click()
  await expect(page.getByRole('heading', { name: '测试资产' })).toBeVisible()

  await createCase(page, caseName)
  await publishCaseTwiceAndReviewDiff(page, caseName)
  await createAndPublishSuite(page, caseName, suiteName)
  await createSuitePlan(page, suiteName, planName)
})

async function createCase(page: Page, caseName: string) {
  await page.getByRole('button', { name: '新建测试用例' }).click()
  const dialog = page.getByRole('dialog', { name: '新建测试用例' })
  await dialog.getByLabel('用例名称').fill(caseName)
  await chooseLastOption(page, dialog.getByLabel('已发布工作流'))
  await chooseNamedOption(page, dialog.getByLabel('运行环境'), 'V1 Mock Business')
  await dialog.getByLabel('标签').fill('s15')
  await page.keyboard.press('Enter')
  await dialog.getByRole('button', { name: /确\s*定/ }).click()
  await expect(assetRow(page, caseName)).toBeVisible()
}

async function publishCaseTwiceAndReviewDiff(page: Page, caseName: string) {
  await assetRow(page, caseName).getByRole('button', { name: '发布' }).click()
  await expect(assetRow(page, caseName).getByText('v1', { exact: true })).toBeVisible()

  await assetRow(page, caseName).getByRole('button', { name: '编辑' }).click()
  const editor = page.getByRole('dialog', { name: '编辑测试用例草稿' })
  await editor.getByLabel('说明').fill('S15 第二版固定用例')
  await chooseFirstOption(page, editor.getByLabel('已发布工作流'))
  await editor.getByRole('button', { name: /确\s*定/ }).click()
  await assetRow(page, caseName).getByRole('button', { name: '发布' }).click()
  await expect(assetRow(page, caseName).getByText('v2', { exact: true })).toBeVisible()

  await assetRow(page, caseName).getByRole('button', { name: 'Diff' }).click()
  const diff = page.getByRole('dialog', { name: /版本 Diff：v1 → v2/ })
  await expect(diff).toContainText('workflow_id')
  await page.keyboard.press('Escape')

  await assetRow(page, caseName).getByRole('button', { name: '克隆' }).click()
  await expect(assetRow(page, `${caseName} 副本`)).toBeVisible()
}

async function createAndPublishSuite(page: Page, caseName: string, suiteName: string) {
  await page.getByRole('tab', { name: /测试套件/ }).click()
  await page.getByRole('button', { name: '新建测试套件' }).click()
  const dialog = page.getByRole('dialog', { name: '新建测试套件' })
  await dialog.getByLabel('套件名称').fill(suiteName)
  await dialog.getByLabel('已发布测试用例').click()
  await page.getByText(caseName, { exact: true }).last().click()
  await page.keyboard.press('Escape')
  await dialog.getByRole('button', { name: /确\s*定/ }).click()
  await expect(assetRow(page, suiteName)).toBeVisible()
  await assetRow(page, suiteName).getByRole('button', { name: '发布' }).click()
  await expect(assetRow(page, suiteName).getByText('v1', { exact: true })).toBeVisible()
}

async function createSuitePlan(page: Page, suiteName: string, planName: string) {
  await page.getByRole('link', { name: '任务执行' }).click()
  await expect(page.getByRole('heading', { name: '任务执行' })).toBeVisible()
  await page.getByRole('button', { name: '新建计划' }).click()
  const dialog = page.getByRole('dialog', { name: '新建测试计划' })
  await dialog.getByLabel('计划名称').fill(planName)
  await dialog.getByLabel('资产类型').click()
  await page.getByText('测试套件', { exact: true }).last().click()
  await dialog.getByLabel('测试套件').click()
  await page.getByText(suiteName, { exact: true }).last().click()
  await dialog.getByRole('button', { name: /确\s*定/ }).click()

  await expect(page.getByText('Webhook Secret（仅显示一次）')).toBeVisible()
  await page.keyboard.press('Escape')
  const planRow = page.getByRole('row').filter({ hasText: planName })
  await expect(planRow).toBeVisible()
  const queued = page.waitForResponse(
    (response) =>
      response.url().includes('/test-plans/') &&
      response.url().endsWith('/runs') &&
      response.request().method() === 'POST',
  )
  await planRow.getByRole('button', { name: '运行' }).click()
  expect((await queued).status()).toBe(202)
  await expect(page.getByText('测试计划已进入队列').last()).toBeVisible()
  const runQueue = page.locator('.ant-card').filter({ hasText: '运行队列' })
  await expect(runQueue.getByRole('row').nth(1)).toContainText('passed', { timeout: 30_000 })
}

async function chooseLastOption(page: Page, select: ReturnType<Page['getByLabel']>) {
  await select.click()
  const options = page.locator(
    '.ant-select-dropdown:visible .ant-select-item-option:not(.ant-select-item-option-disabled)',
  )
  await expect(options.first()).toBeVisible()
  await options.last().click()
}

async function chooseFirstOption(page: Page, select: ReturnType<Page['getByLabel']>) {
  await select.click()
  const options = page.locator(
    '.ant-select-dropdown:visible .ant-select-item-option:not(.ant-select-item-option-disabled)',
  )
  await expect(options.first()).toBeVisible()
  await options.first().click()
}

async function chooseNamedOption(page: Page, select: ReturnType<Page['getByLabel']>, name: string) {
  await select.click()
  await page.getByText(name, { exact: true }).last().click()
}

function assetRow(page: Page, name: string) {
  return page.getByRole('row').filter({ hasText: name }).first()
}
