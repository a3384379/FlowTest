import { expect, test, type APIRequestContext } from '@playwright/test'

type Identified = { id: string }

test('S31 全局搜索进入发布门禁并生成不可变 PASS 判断', async ({ page }) => {
  const token = await accessTokenFromSession(page.request)
  const project = await createProject(page.request, token)
  const policyName = `S31 浏览器策略 ${Date.now()}`
  await createPolicy(page.request, token, project.id, policyName)

  await page.goto(`/projects/${project.id}/dashboard`)
  const search = page.getByLabel('全局搜索')
  await search.fill(policyName)
  await expect(page.getByText(policyName).last()).toBeVisible()
  await page.getByText(policyName).last().click()

  await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/release`))
  await expect(page.getByRole('heading', { name: '发布门禁' })).toBeVisible()
  await page.getByRole('button', { name: '生成发布判断' }).click()
  const dialog = page.getByRole('dialog', { name: '生成发布判断' })
  await dialog.getByLabel('发布策略').click()
  await page.getByText(policyName).last().click()
  await dialog.getByLabel('候选版本').fill('v3.0.0-rc.browser')
  const created = page.waitForResponse(
    (response) =>
      response.url().endsWith('/release-decisions') && response.request().method() === 'POST',
  )
  await dialog.locator('.ant-modal-footer .ant-btn-primary').click()
  expect((await created).status()).toBe(201)

  await expect(page.getByText('v3.0.0-rc.browser')).toBeVisible()
  await expect(page.getByText('PASS').last()).toBeVisible()
  await page.getByRole('button', { name: '查看证据' }).click()
  const detail = page.getByRole('dialog', { name: '发布判断证据' })
  await expect(detail.getByText(/历史判断只读/)).toBeVisible()
  await expect(detail.getByText('QUALITY_GATE_EVIDENCE_MISSING_OPTIONAL')).toBeVisible()
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
    data: { name: `S31 浏览器 ${Date.now()}`, description: 'S31 Playwright' },
  })
  expect(response.status(), await response.text()).toBe(201)
  return (await response.json()) as Identified
}

async function createPolicy(
  request: APIRequestContext,
  token: string,
  projectId: string,
  name: string,
): Promise<void> {
  const response = await request.post(`/api/v1/projects/${projectId}/release-policies`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      name,
      enabled: true,
      quality_gate_id: null,
      require_quality_gate: false,
      require_contract_compatibility: false,
      require_impact_evidence: false,
      min_impact_coverage_percent: 80,
      require_release_risk: false,
      max_release_risk_score: 50,
      require_performance_evidence: false,
      require_runner_evidence: false,
    },
  })
  expect(response.status(), await response.text()).toBe(201)
}
