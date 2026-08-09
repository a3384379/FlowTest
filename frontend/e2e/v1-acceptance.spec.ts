import { expect, test, type Page, type Response } from '@playwright/test'

const administratorEmail = process.env.FLOWTEST_E2E_ADMIN_EMAIL ?? 'admin@flowtest.dev'
const activePassword = process.env.FLOWTEST_E2E_ACTIVE_PASSWORD ?? 'FlowTest-E2E-Admin-123!'
const bootstrapPassword = process.env.FLOWTEST_E2E_BOOTSTRAP_PASSWORD ?? 'FlowTest-Change-Me-123!'

test('V1.0 项目治理与脱敏报告主路径', async ({ page }) => {
  await page.goto('/')
  await authenticate(page)

  await page.getByText('项目管理', { exact: true }).click()
  await expect(page.getByRole('heading', { name: '项目治理' })).toBeVisible()
  await expect(page).toHaveURL(/\/projects\/[^/]+\/settings$/)
  const governanceUrl = page.url()
  await page.reload()
  await expect(page).toHaveURL(governanceUrl)
  await expect(page.getByRole('heading', { name: '项目治理' })).toBeVisible()
  await expect(
    page
      .getByRole('main')
      .getByText(/^S11 V1 Pilot /)
      .first(),
  ).toBeVisible()
  await expect(page.getByText('当前身份：系统管理员')).toBeVisible()
  await expect(page.getByLabel('保留天数')).toHaveValue('90')
  await expect(page.getByLabel('允许域名（每行一个）')).toHaveValue('mock-target')
  await expect(page.getByLabel('允许私网 CIDR（每行一个）')).toHaveValue('172.16.0.0/12')
  await expect(page.getByText('project.retention_policy_updated')).toBeVisible()

  await page.getByText('首页', { exact: true }).click()
  await expect(page).toHaveURL(/\/projects\/[^/]+\/dashboard$/)
  await expect(page.getByRole('heading', { name: '工作台' })).toBeVisible()
  await expect(page.getByText(/^当前查看：S11 V1 Pilot /)).toBeVisible()

  await page.getByText('测试报告', { exact: true }).click()
  await expect(page.getByRole('heading', { name: '测试报告' })).toBeVisible()
  const businessExecution = page.getByRole('row', { name: /V1 登录下单流程/ })
  await expect(businessExecution).toContainText('8/8 通过')
  await businessExecution.getByRole('button', { name: '详情' }).click()
  const report = page.getByRole('dialog', { name: '执行报告详情' })
  await expect(report).toContainText('V1 登录下单流程')
  await expect(report).toContainText('登录')
  await expect(report).toContainText('查询用户')
  await expect(report).toContainText('创建订单')
  await expect(page.locator('body')).not.toContainText('mock-token')
  await page.keyboard.press('Escape')
  await expect(report).toBeHidden()

  for (const [menu, heading] of [
    ['接口管理', '接口管理'],
    ['流程编排', '流程编排'],
    ['任务执行', '任务执行'],
  ] as const) {
    await page.getByText(menu, { exact: true }).click()
    await expect(page.getByRole('heading', { name: heading })).toBeVisible()
  }
})

async function authenticate(page: Page): Promise<void> {
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

async function submitLogin(page: Page, password: string): Promise<Response> {
  await page.getByLabel('密码').fill(password)
  const response = page.waitForResponse(
    (candidate) =>
      candidate.url().endsWith('/api/v1/auth/login') && candidate.request().method() === 'POST',
  )
  await page.getByRole('button', { name: /登\s*录/ }).click()
  return response
}
