import { expect, test, type APIRequestContext, type Page, type Response } from '@playwright/test'

import { authenticate } from './support/auth'

test('S15 用例、套件、版本 Diff 与固定计划目标主路径', async ({ page }, testInfo) => {
  test.setTimeout(180_000)
  const suffix = `${Date.now()}-${testInfo.retry}`
  const caseName = `S15 登录用例 ${suffix}`
  const suiteName = `S15 冒烟套件 ${suffix}`
  const planName = `S15 固定套件计划 ${suffix}`
  const firstEnvironmentName = `S15 环境 v1 ${suffix}`
  const secondEnvironmentName = `S15 环境 v2 ${suffix}`
  const workflowName = `S15 固定工作流 ${suffix}`

  await page.goto('/')
  await authenticate(page)
  await createSecondaryEnvironment(page, firstEnvironmentName)
  await createSecondaryEnvironment(page, secondEnvironmentName)
  await createPublishedWorkflow(page, workflowName)
  await page.getByRole('link', { name: '测试资产' }).click()
  await expect(page.getByRole('heading', { name: '测试资产' })).toBeVisible()

  await createCase(page, caseName, workflowName, firstEnvironmentName)
  await publishCaseTwiceAndReviewDiff(page, caseName, secondEnvironmentName)
  await createAndPublishSuite(page, caseName, suiteName)
  await createSuitePlan(page, suiteName, planName)
})

async function createCase(
  page: Page,
  caseName: string,
  workflowName: string,
  environmentName: string,
) {
  await page.getByRole('button', { name: '新建测试用例' }).click()
  const dialog = page.getByRole('dialog', { name: '新建测试用例' })
  await dialog.getByLabel('用例名称').fill(caseName)
  await chooseOption(page, dialog.getByLabel('已发布工作流'), workflowName)
  await chooseOption(page, dialog.getByLabel('运行环境'), environmentName)
  await dialog.getByLabel('标签').fill('s15')
  await page.keyboard.press('Enter')
  await page.keyboard.press('Escape')
  const created = waitForProjectPost(page, '/test-cases')
  await dialog.getByRole('button', { name: /确\s*定/ }).click()
  await expectSuccessful(created)
  await expect(dialog).toBeHidden()
  await expect(assetRow(page, caseName)).toBeVisible({ timeout: 15_000 })
}

async function createPublishedWorkflow(page: Page, name: string) {
  const projectId = await selectedProjectId(page)
  const token = await accessTokenFromSession(page.request)
  const created = await page.request.post(`/api/v1/projects/${projectId}/workflows`, {
    headers: authorization(token),
    data: {
      name,
      description: 'S15 端到端验收工作流',
      definition: {
        schema_version: '1.0',
        variables: {},
        nodes: [
          { id: 'start', type: 'start', name: '开始', position: { x: 0, y: 80 }, config: {} },
          { id: 'end', type: 'end', name: '结束', position: { x: 440, y: 80 }, config: {} },
        ],
        edges: [{ id: 'start-end', source: 'start', target: 'end' }],
        settings: { fail_fast: true, concurrency: 20, default_timeout_seconds: 30 },
      },
    },
  })
  expect(created.ok(), await created.text()).toBeTruthy()
  const workflow = (await created.json()) as { id: string }
  const published = await page.request.post(
    `/api/v1/projects/${projectId}/workflows/${workflow.id}/versions`,
    { headers: authorization(token) },
  )
  expect(published.ok(), await published.text()).toBeTruthy()
}

async function selectedProjectId(page: Page): Promise<string> {
  const dashboardLink = page.getByRole('link', { name: '质量总览' })
  await expect(dashboardLink).toHaveAttribute('href', /^\/projects\/[^/]+\/dashboard$/)
  const dashboardHref = await dashboardLink.getAttribute('href')
  const match = dashboardHref?.match(/^\/projects\/([^/]+)\/dashboard$/) ?? null
  expect(match, `全局导航缺少项目上下文: ${dashboardHref}`).not.toBeNull()
  return match![1]
}

async function accessTokenFromSession(request: APIRequestContext): Promise<string> {
  const response = await request.post('/api/v1/auth/refresh')
  expect(response.ok(), await response.text()).toBeTruthy()
  return ((await response.json()) as { access_token: string }).access_token
}

function authorization(token: string) {
  return { Authorization: `Bearer ${token}` }
}

async function publishCaseTwiceAndReviewDiff(
  page: Page,
  caseName: string,
  secondEnvironmentName: string,
) {
  await assetRow(page, caseName).getByRole('button', { name: '发布' }).click()
  await expect(assetRow(page, caseName).getByText('v1', { exact: true })).toBeVisible()

  await assetRow(page, caseName).getByRole('button', { name: '编辑' }).click()
  const editor = page.getByRole('dialog', { name: '编辑测试用例草稿' })
  await editor.getByLabel('说明').fill('S15 第二版固定用例')
  await chooseOption(page, editor.getByLabel('运行环境'), secondEnvironmentName)
  await editor.getByRole('button', { name: /确\s*定/ }).click()
  await assetRow(page, caseName).getByRole('button', { name: '发布' }).click()
  await expect(assetRow(page, caseName).getByText('v2', { exact: true })).toBeVisible()

  await assetRow(page, caseName).getByRole('button', { name: 'Diff' }).click()
  const diff = page.getByRole('dialog', { name: /版本 Diff：v1 → v2/ })
  await expect(diff).toContainText('environment_id')
  await page.keyboard.press('Escape')

  await assetRow(page, caseName).getByRole('button', { name: '克隆' }).click()
  await expect(assetRow(page, `${caseName} 副本`)).toBeVisible()
}

async function createSecondaryEnvironment(page: Page, name: string) {
  await page.getByRole('link', { name: '接口管理' }).click()
  await expect(page.getByRole('heading', { name: '接口管理' })).toBeVisible()
  await page.getByRole('button', { name: '新建环境' }).click()
  const dialog = page.getByRole('dialog', { name: '新建环境' })
  await dialog.getByLabel('环境名称').fill(name)
  await dialog.getByLabel('基础 URL').fill('http://mock-target.test:8080')
  const created = waitForProjectPost(page, '/environments')
  await dialog.getByRole('button', { name: /确\s*定/ }).click()
  await expectSuccessful(created)
  await expect(dialog).toBeHidden()
  await expect(page.getByText(name, { exact: true })).toBeVisible({ timeout: 15_000 })
}

async function createAndPublishSuite(page: Page, caseName: string, suiteName: string) {
  await page.getByRole('tab', { name: /测试套件/ }).click()
  await page.getByRole('button', { name: '新建测试套件' }).click()
  const dialog = page.getByRole('dialog', { name: '新建测试套件' })
  await dialog.getByLabel('套件名称').fill(suiteName)
  await dialog.getByLabel('已发布测试用例').click()
  await page.getByText(caseName, { exact: true }).last().click()
  await page.keyboard.press('Escape')
  const created = waitForProjectPost(page, '/test-suites')
  await dialog.getByRole('button', { name: /确\s*定/ }).click()
  await expectSuccessful(created)
  await expect(dialog).toBeHidden()
  await expect(assetRow(page, suiteName)).toBeVisible({ timeout: 15_000 })
  await assetRow(page, suiteName).getByRole('button', { name: '发布' }).click()
  await expect(assetRow(page, suiteName).getByText('v1', { exact: true })).toBeVisible()
}

async function createSuitePlan(page: Page, suiteName: string, planName: string) {
  await page.getByRole('link', { name: '任务执行' }).click()
  await expect(page.getByRole('heading', { name: '任务执行' })).toBeVisible()
  await page.getByRole('button', { name: '新建计划' }).click()
  const dialog = page.getByRole('dialog', { name: '新建测试计划' })
  await dialog.getByLabel('计划名称').fill(planName)
  await chooseOption(page, dialog.getByLabel('资产类型'), '测试套件')
  const suiteSelect = dialog.getByLabel('测试套件')
  await expect(suiteSelect).toBeVisible()
  await chooseOption(page, suiteSelect, suiteName)
  const created = waitForProjectPost(page, '/test-plans')
  await dialog.getByRole('button', { name: /确\s*定/ }).click()
  await expectSuccessful(created)

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

async function chooseOption(
  page: Page,
  select: ReturnType<Page['getByLabel']>,
  optionName: string,
) {
  await select.click()
  const dropdown = page.locator('.ant-select-dropdown:visible').last()
  const option = dropdown.getByText(optionName, { exact: true })
  await expect(option).toBeVisible()
  await option.click()
}

function assetRow(page: Page, name: string) {
  return page.getByRole('row').filter({ hasText: name }).first()
}

function waitForProjectPost(page: Page, pathSuffix: string): Promise<Response> {
  return page.waitForResponse(
    (response) =>
      response.url().includes('/api/v1/projects/') &&
      response.url().endsWith(pathSuffix) &&
      response.request().method() === 'POST',
  )
}

async function expectSuccessful(responsePromise: Promise<Response>): Promise<void> {
  const response = await responsePromise
  expect(response.ok(), await response.text()).toBeTruthy()
}
