import { expect, test, type APIRequestContext } from '@playwright/test'

type Identified = { id: string }

test('S30 发布风险证据经 AI 变更集逐项审核后只生成草稿', async ({ page }) => {
  test.setTimeout(90_000)
  const draftName = `S30 浏览器草稿工作流 ${Date.now()}`

  const token = await accessTokenFromSession(page.request)
  const project = await createProject(page.request, token)
  await createImpact(page.request, token, project.id)

  await page.goto(`/projects/${project.id}/quality`)
  await expect(page.getByRole('heading', { name: '质量中心' })).toBeVisible({ timeout: 15_000 })
  await page.getByRole('button', { name: '分析发布风险' }).click()
  const riskDialog = page.getByRole('dialog', { name: '分析发布风险' })
  await riskDialog.getByLabel('候选版本').fill('S30 浏览器 RC')
  await riskDialog.getByLabel('影响分析').click()
  await page
    .getByText(/S30 浏览器影响分析/)
    .last()
    .click()
  const riskCreated = page.waitForResponse(
    (response) =>
      response.url().endsWith('/release-risks') && response.request().method() === 'POST',
  )
  await riskDialog.locator('.ant-modal-footer .ant-btn-primary').click()
  expect((await riskCreated).status()).toBe(201)
  await expect(page.getByText('发布风险分析已完成')).toBeVisible()
  await expect(page.getByText('证据指纹')).toBeVisible()

  await page.getByRole('link', { name: 'AI 变更集' }).click()
  await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/ai-changes$`))
  await expect(page.getByRole('heading', { name: 'AI 测试资产变更审核' })).toBeVisible()
  await expect(page.getByText(/AI 只生成草稿/)).toBeVisible()
  await page.getByRole('button', { name: '生成 Draft Change Set' }).click()
  const changeSetDialog = page.getByRole('dialog', { name: '生成 Draft Change Set' })
  await changeSetDialog.getByLabel('变更集名称').fill('S30 浏览器 Draft Change Set')
  await changeSetDialog.getByLabel('发布风险证据').click()
  await page
    .getByText(/S30 浏览器 RC/)
    .last()
    .click()
  const changeSetCreated = page.waitForResponse(
    (response) =>
      response.url().endsWith('/api/v1/ai/change-sets') && response.request().method() === 'POST',
  )
  await changeSetDialog.locator('.ant-modal-footer .ant-btn-primary').click()
  const createdResponse = await changeSetCreated
  expect(createdResponse.status()).toBe(202)
  const created = (await createdResponse.json()) as { ai_job_id: string }

  const suggestion = await firstSuggestion(page.request, token, created.ai_job_id)
  const bypassed = await page.request.post(`/api/v1/ai/suggestions/${suggestion.id}/accept`, {
    headers: { Authorization: `Bearer ${token}` },
    data: { note: 'must use item review' },
  })
  expect(bypassed.status()).toBe(409)
  expect(((await bypassed.json()) as { error: { code: string } }).error.code).toBe(
    'AI_CHANGE_SET_REVIEW_REQUIRED',
  )

  await expect(page.getByText('S30 AI 变更集草稿工作流', { exact: true })).toBeVisible({
    timeout: 30_000,
  })
  const beforeAccept = await listWorkflows(page.request, token, project.id)
  expect(beforeAccept.total).toBe(0)
  await page.getByRole('button', { name: '审核并接受' }).click()
  const reviewDialog = page.getByRole('dialog', { name: '编辑并接受变更项' })
  const editor = reviewDialog.getByLabel('变更内容 JSON')
  const content = JSON.parse(await editor.inputValue()) as Record<string, unknown>
  content.name = draftName
  await editor.fill(JSON.stringify(content, null, 2))
  await reviewDialog.getByLabel('审核备注').fill('Playwright 逐项人工确认')
  const accepted = page.waitForResponse(
    (response) => response.url().endsWith('/accept') && response.request().method() === 'POST',
  )
  await reviewDialog.locator('.ant-modal-footer .ant-btn-primary').click()
  expect((await accepted).ok()).toBeTruthy()
  await expect(page.getByText('已接受', { exact: true }).last()).toBeVisible()

  const afterAccept = await listWorkflows(page.request, token, project.id)
  expect(afterAccept.total).toBe(1)
  expect(afterAccept.items[0]?.name).toBe(draftName)
  expect(afterAccept.items[0]?.current_version).toBeNull()
})

async function accessTokenFromSession(request: APIRequestContext): Promise<string> {
  const response = await request.post('/api/v1/auth/login', {
    data: {
      email: process.env.FLOWTEST_E2E_ADMIN_EMAIL ?? 'admin@flowtest.dev',
      password: process.env.FLOWTEST_E2E_ACTIVE_PASSWORD ?? 'FlowTest-E2E-Admin-123!',
    },
  })
  expect(response.ok(), await response.text()).toBeTruthy()
  return ((await response.json()) as { access_token: string }).access_token
}

async function createProject(request: APIRequestContext, token: string): Promise<Identified> {
  const response = await request.post('/api/v1/projects', {
    headers: { Authorization: `Bearer ${token}` },
    data: { name: `S30 浏览器 ${Date.now()}`, description: 'S30 Playwright' },
  })
  expect(response.ok(), await response.text()).toBeTruthy()
  return (await response.json()) as Identified
}

async function createImpact(
  request: APIRequestContext,
  token: string,
  projectId: string,
): Promise<Identified> {
  const response = await request.post(`/api/v1/projects/${projectId}/impact/runs`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      title: 'S30 浏览器影响分析',
      source_ref: 'playwright/s30',
      git_diff:
        'diff --git a/backend/orders.py b/backend/orders.py\n' +
        '--- a/backend/orders.py\n' +
        '+++ b/backend/orders.py\n' +
        '@@ -1 +1 @@\n' +
        '-old\n' +
        '+new\n',
    },
  })
  expect(response.status(), await response.text()).toBe(201)
  return (await response.json()) as Identified
}

async function firstSuggestion(
  request: APIRequestContext,
  token: string,
  jobId: string,
): Promise<Identified> {
  const deadline = Date.now() + 30_000
  while (Date.now() < deadline) {
    const response = await request.get(`/api/v1/ai/jobs/${jobId}/suggestions`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    expect(response.ok(), await response.text()).toBeTruthy()
    const suggestions = (await response.json()) as Identified[]
    if (suggestions[0]) return suggestions[0]
    await new Promise((resolve) => setTimeout(resolve, 250))
  }
  throw new Error(`AI job ${jobId} did not produce a suggestion`)
}

async function listWorkflows(
  request: APIRequestContext,
  token: string,
  projectId: string,
): Promise<{ total: number; items: Array<{ name: string; current_version: number | null }> }> {
  const response = await request.get(`/api/v1/projects/${projectId}/workflows`, {
    headers: { Authorization: `Bearer ${token}` },
    params: { page: 1, page_size: 100 },
  })
  expect(response.ok(), await response.text()).toBeTruthy()
  return (await response.json()) as {
    total: number
    items: Array<{ name: string; current_version: number | null }>
  }
}
