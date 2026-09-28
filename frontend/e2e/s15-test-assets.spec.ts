import { navigateMenu } from './support/navigation'
import {
  expect,
  test,
  type APIRequestContext,
  type Locator,
  type Page,
  type Response,
} from '@playwright/test'

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
  const projectId = await createIsolatedProject(page, suffix)
  await page.goto(`/projects/${projectId}/apis`)
  await expect(page.getByRole('link', { name: '质量总览' })).toHaveAttribute(
    'href',
    `/projects/${projectId}/dashboard`,
  )
  await createSecondaryEnvironment(page, projectId, firstEnvironmentName)
  await createSecondaryEnvironment(page, projectId, secondEnvironmentName)
  await createPublishedWorkflow(page, projectId, workflowName)
  await navigateMenu(page, '测试用例')
  await expect(page.getByRole('heading', { name: '测试用例' })).toBeVisible()

  await createCase(page, caseName, workflowName, firstEnvironmentName)
  await publishCaseTwiceAndReviewDiff(page, caseName, secondEnvironmentName)
  await runPublishedCase(page, caseName)
  await createAndPublishSuite(page, caseName, suiteName)
  await createSuitePlan(page, suiteName, planName)
  await addCaseToExistingPlan(page, caseName, planName)
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
  await dialog.getByRole('button', { name: '添加请求头' }).click()
  await dialog.getByLabel('请求头覆盖名称1').fill('X-Tenant-ID')
  await dialog.getByLabel('请求头覆盖值1').fill('synthetic-tenant')
  const tagsSelect = dialog.getByLabel('标签')
  await tagsSelect.fill('s15')
  await tagsSelect.press('Enter')
  await expect(selectControl(tagsSelect)).toContainText('s15')
  await tagsSelect.press('Escape')
  const created = waitForProjectPost(page, '/test-cases')
  await dialog.getByRole('button', { name: /确\s*定/ }).click()
  await expectSuccessful(created)
  await expect(dialog).toBeHidden()
  await expect(assetRow(page, caseName)).toBeVisible({ timeout: 15_000 })
}

async function createPublishedWorkflow(page: Page, projectId: string, name: string) {
  const token = await accessTokenFromSession(page.request)
  const apiCreated = await page.request.post(`/api/v1/projects/${projectId}/apis`, {
    headers: authorization(token),
    data: {
      name: `S15 检查租户请求 ${name}`,
      request: { method: 'GET', path: '/s47-2/inspect', body_kind: 'none' },
    },
  })
  expect(apiCreated.ok(), await apiCreated.text()).toBeTruthy()
  const api = (await apiCreated.json()) as { definition: { id: string } }
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
          {
            id: 'api',
            type: 'api',
            name: '检查租户请求',
            position: { x: 220, y: 80 },
            config: { api_definition_id: api.definition.id },
          },
          { id: 'end', type: 'end', name: '结束', position: { x: 440, y: 80 }, config: {} },
        ],
        edges: [
          { id: 'start-api', source: 'start', target: 'api' },
          { id: 'api-end', source: 'api', target: 'end' },
        ],
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

async function createIsolatedProject(page: Page, suffix: string): Promise<string> {
  const token = await accessTokenFromSession(page.request)
  const created = await page.request.post('/api/v1/projects', {
    headers: authorization(token),
    data: { name: `S15 隔离用例项目 ${suffix}` },
  })
  expect(created.ok(), await created.text()).toBeTruthy()
  const project = (await created.json()) as { id: string }
  const policy = await page.request.put(`/api/v1/projects/${project.id}/security-policy`, {
    headers: authorization(token),
    data: { allowed_hosts: ['mock-target'], allowed_private_cidrs: ['172.16.0.0/12'] },
  })
  expect(policy.ok(), await policy.text()).toBeTruthy()
  return project.id
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
  await caseAction(page, caseName, '发布新版本')
  await expect(assetRow(page, caseName).getByText('v1', { exact: true })).toBeVisible()

  await assetRow(page, caseName).getByRole('button', { name: '编辑' }).click()
  const editor = page.getByRole('dialog', { name: '编辑测试用例草稿' })
  await editor.getByLabel('说明').fill('S15 第二版固定用例')
  await chooseOption(page, editor.getByLabel('运行环境'), secondEnvironmentName)
  await editor.getByRole('button', { name: /确\s*定/ }).click()
  await caseAction(page, caseName, '发布新版本')
  await expect(assetRow(page, caseName).getByText('v2', { exact: true })).toBeVisible()

  await caseAction(page, caseName, '版本对比')
  const diff = page.getByRole('dialog', { name: /版本 Diff：v1 → v2/ })
  await expect(diff).toContainText('environment_id')
  await page.keyboard.press('Escape')

  await caseAction(page, caseName, '克隆')
  await expect(assetRow(page, `${caseName} 副本`)).toBeVisible()
}

async function runPublishedCase(page: Page, caseName: string) {
  const projectId = await selectedProjectId(page)
  await assetRow(page, caseName).getByRole('button', { name: '运行' }).click()
  const dialog = page.getByRole('dialog', { name: `运行测试用例：${caseName}` })
  await dialog.getByLabel('运行已发布用例版本').check()
  await expect(selectControl(dialog.getByLabel('运行用例版本'))).toContainText('用例 v2')
  const submitted = page.waitForResponse(
    (response) =>
      response.url().includes('/test-cases/') &&
      response.url().endsWith('/runs') &&
      response.request().method() === 'POST',
  )
  await dialog.getByRole('button', { name: '运行已发布版本' }).click()
  const response = await submitted
  expect(response.status()).toBe(202)
  const run = (await response.json()) as { execution_id: string }
  const token = await accessTokenFromSession(page.request)
  await expect
    .poll(
      async () => {
        const detail = await page.request.get(
          `/api/v1/projects/${projectId}/workflow-executions/${run.execution_id}`,
          { headers: authorization(token) },
        )
        if (!detail.ok()) return null
        const payload = (await detail.json()) as {
          nodes: Array<{ node_id: string; output: { body?: { tenant_header_present?: boolean } } }>
        }
        return payload.nodes.find((node) => node.node_id === 'api')?.output.body
          ?.tenant_header_present
      },
      { timeout: 30_000 },
    )
    .toBe(true)
  const receipt = page.getByRole('dialog', { name: '运行已提交' })
  await expect(receipt).toContainText('用例 v2')
  await receipt.getByRole('button', { name: '查看执行详情' }).click()
  await expect(page.getByText('正在查看历史执行快照')).toBeVisible({ timeout: 30_000 })
  await navigateMenu(page, '测试用例')
  await expect(assetRow(page, caseName)).toContainText('用例 v2', { timeout: 30_000 })
}

async function addCaseToExistingPlan(page: Page, caseName: string, planName: string) {
  await navigateMenu(page, '测试用例')
  await caseAction(page, caseName, '加入测试计划')
  const dialog = page.getByRole('dialog', { name: '加入测试计划' })
  await chooseOption(page, dialog.getByLabel('选择测试计划'), planName)
  const added = page.waitForResponse(
    (response) =>
      response.url().includes('/test-plans/') &&
      response.url().endsWith('/items') &&
      response.request().method() === 'POST',
  )
  await dialog.getByRole('button', { name: /确\s*定|OK/ }).click()
  const response = await added
  expect(response.status()).toBe(201)
  const plan = (await response.json()) as {
    items: Array<{ target_type: string; target_version: number }>
  }
  expect(plan.items.some((item) => item.target_type === 'case' && item.target_version === 2)).toBe(
    true,
  )
}

async function createSecondaryEnvironment(page: Page, projectId: string, name: string) {
  const token = await accessTokenFromSession(page.request)
  const created = await page.request.post(`/api/v1/projects/${projectId}/environments`, {
    headers: authorization(token),
    data: { name, base_url: 'http://mock-target:8080', variables: {}, headers: {} },
  })
  expect(created.ok(), await created.text()).toBeTruthy()
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
  await navigateMenu(page, '任务执行')
  await expect(page.getByRole('heading', { name: '任务执行' })).toBeVisible()
  await page.getByRole('button', { name: '新建计划' }).click()
  const dialog = page.getByRole('dialog', { name: '新建测试计划' })
  await dialog.getByLabel('计划名称').fill(planName)
  await chooseOption(page, dialog.getByLabel('执行目标'), '测试套件')
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

async function chooseOption(page: Page, select: Locator, optionName: string) {
  await expect(select).toBeEnabled()
  await select.click()
  if (await select.isEditable()) await select.fill(optionName)
  const dropdown = page.locator('.ant-select-dropdown:visible').last()
  const option = dropdown.getByText(optionName, { exact: true })
  await expect(option).toBeVisible()
  await option.click()
  await expect(selectControl(select)).toContainText(optionName)
}

function selectControl(select: Locator): Locator {
  return select.locator(
    'xpath=ancestor::*[contains(concat(" ", normalize-space(@class), " "), " ant-select ")][1]',
  )
}

function assetRow(page: Page, name: string) {
  return page.getByRole('row').filter({ has: page.getByRole('cell', { name, exact: true }) })
}

async function caseAction(page: Page, name: string, action: string) {
  await assetRow(page, name).getByRole('button', { name: '更多' }).click()
  await page.getByRole('menuitem', { name: action }).click()
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
