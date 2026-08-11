import { expect, test } from '@playwright/test'

import { administratorEmail, authenticate } from './support/auth'

test('S14 团队、测试资产与 API 工作台主路径', async ({ page }) => {
  test.setTimeout(90_000)
  const suffix = Date.now().toString()
  const environmentName = `S14 环境 ${suffix}`
  const apiName = `S14 接口 ${suffix}`
  const folderName = `S14 目录 ${suffix}`
  const renamedFolder = `${folderName} 已编辑`
  const secretName = `S14_SECRET_${suffix}`
  const secretValue = `never-return-${suffix}`
  const teamName = `S14 团队 ${suffix}`

  await page.goto('/')
  await authenticate(page)

  await page.getByRole('link', { name: '接口管理' }).click()
  await expect(page.getByRole('heading', { name: '接口管理' })).toBeVisible()
  await createEnvironment(page, environmentName)
  await createApi(page, apiName)
  await editApiVersion(page, apiName)

  await page.getByRole('link', { name: '项目管理' }).click()
  await expect(page.getByRole('heading', { name: '项目治理' })).toBeVisible()
  await manageFolder(page, folderName, renamedFolder)
  await updateProjectConfiguration(page, suffix)
  await writeSecret(page, secretName, secretValue)
  await manageTeam(page, teamName)
  await expect(page.locator('body')).not.toContainText(secretValue)
})

async function createEnvironment(page: import('@playwright/test').Page, name: string) {
  await page.getByRole('button', { name: '新建环境' }).click()
  const dialog = page.getByRole('dialog', { name: '新建环境' })
  await dialog.getByLabel('环境名称').fill(name)
  await dialog.getByLabel('基础 URL').fill('http://mock-target.test:8080')
  await dialog.getByRole('button', { name: /确\s*定/ }).click()
  await expect(page.getByText(name, { exact: true })).toBeVisible()
}

async function createApi(page: import('@playwright/test').Page, name: string) {
  await page.getByRole('button', { name: '新建接口' }).click()
  const dialog = page.getByRole('dialog', { name: '新建接口' })
  await dialog.getByLabel('接口名称').fill(name)
  await dialog.getByPlaceholder('/users/me').fill('/echo')
  await dialog.getByRole('button', { name: /确\s*定/ }).click()
  await expect(workbench(page, name)).toBeVisible()
  await expect(workbench(page, name).getByText('v1', { exact: true })).toBeVisible()
}

async function editApiVersion(page: import('@playwright/test').Page, apiName: string) {
  const panel = workbench(page, apiName)
  await panel.getByRole('tab', { name: 'Params' }).click()
  await panel.getByRole('button', { name: '添加一行' }).click()
  await panel.getByPlaceholder('参数名').fill('source')
  await panel.getByPlaceholder('值或 {{变量}}').fill('s14')

  await panel.getByRole('tab', { name: '提取' }).click()
  await panel.getByRole('button', { name: '添加一行' }).click()
  await panel.getByPlaceholder('变量名').fill('echo_body')
  await panel.getByPlaceholder('$.data.token').fill('$.body')

  await panel.getByRole('tab', { name: '断言' }).click()
  await panel.getByRole('button', { name: '添加一行' }).click()
  await panel.getByRole('button', { name: '保存新版本' }).click()
  await expect(page.getByText('接口新版本已保存').last()).toBeVisible()
  await expect(workbench(page, apiName).getByText('v2', { exact: true })).toBeVisible()

  await panel.getByRole('button', { name: '预览最终请求' }).click()
  const preview = page.getByRole('dialog', { name: '最终请求预览（Secret 已脱敏）' })
  await expect(preview).toContainText('http://mock-target.test:8080/echo')
  await expect(preview).toContainText('source')
  await page.keyboard.press('Escape')
}

function workbench(page: import('@playwright/test').Page, apiName: string) {
  return page
    .locator('.ant-card')
    .filter({ has: page.getByRole('button', { name: '保存新版本' }) })
    .filter({ hasText: apiName })
}

async function manageFolder(page: import('@playwright/test').Page, name: string, renamed: string) {
  const panel = page.locator('.ant-card').filter({ hasText: '测试资产配置' })
  await panel.getByPlaceholder('目录名称').fill(name)
  await panel.getByRole('button', { name: '新建目录' }).click()
  const row = panel.getByRole('row').filter({ hasText: name })
  await expect(row).toBeVisible()
  await row.getByRole('button', { name: '编辑目录' }).click()
  await expect(panel.getByPlaceholder('目录名称')).toHaveValue(name)
  await panel.getByPlaceholder('目录名称').fill(renamed)
  await panel.getByRole('button', { name: '保存目录' }).click()
  await expect(panel.getByRole('row').filter({ hasText: renamed })).toBeVisible()
}

async function updateProjectConfiguration(page: import('@playwright/test').Page, suffix: string) {
  await page.getByRole('tab', { name: '项目变量与 Header' }).click()
  await page.getByLabel('项目变量（JSON）').fill(`{"s14":"${suffix}"}`)
  await page.getByLabel('项目 Header（JSON）').fill('{"X-FlowTest":"s14"}')
  await page.getByRole('button', { name: '保存项目配置' }).click()
  await expect(page.getByText('测试资产配置已保存').last()).toBeVisible()
}

async function writeSecret(page: import('@playwright/test').Page, name: string, value: string) {
  await page.getByRole('tab', { name: 'Secret' }).click()
  const panel = page.getByRole('tabpanel', { name: 'Secret' })
  await panel.getByPlaceholder('Secret 名称').fill(name)
  await panel.getByPlaceholder('仅写入，不可读回').fill(value)
  const saved = page.waitForResponse(
    (response) =>
      response.request().method() === 'PUT' && response.url().endsWith('/secrets') && response.ok(),
  )
  await panel.getByRole('button', { name: '写入 Secret' }).click()
  await saved
  await expect(panel.getByRole('row').filter({ hasText: name })).toContainText('已加密 · 不可读回')
}

async function manageTeam(page: import('@playwright/test').Page, name: string) {
  await page.getByRole('tab', { name: '用户与团队' }).click()
  const organization = page.getByRole('tabpanel', { name: '用户与团队' })
  await page.getByPlaceholder('团队名称').fill(name)
  await page.getByPlaceholder('团队说明').fill('S14 浏览器验收团队')
  await page.getByRole('button', { name: '创建团队' }).click()
  await expect(page.getByText('成员与团队配置已更新').last()).toBeVisible()

  await expect(page.getByText(name, { exact: true }).last()).toBeVisible()
  await organization.getByRole('combobox').nth(1).click()
  await page.getByText(administratorEmail, { exact: true }).last().click()
  await page.getByRole('button', { name: '添加到团队' }).click()
  await expect(page.getByRole('row').filter({ hasText: administratorEmail })).toBeVisible()

  await page.getByRole('tab', { name: '团队授权' }).click()
  const grants = page.getByRole('tabpanel', { name: '团队授权' })
  await grants.getByRole('combobox').first().click()
  await page.keyboard.press('End')
  await page.keyboard.press('Enter')
  await page.getByRole('button', { name: '授权团队' }).click()
  await expect(grants.getByRole('row').filter({ hasText: 'viewer' }).last()).toBeVisible()
}
