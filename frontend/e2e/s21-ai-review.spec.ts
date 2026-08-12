import { expect, test } from '@playwright/test'

import { authenticate } from './support/auth'

test('S21 AI 脱敏任务与人工接受主路径', async ({ page }) => {
  test.setTimeout(60_000)
  const acceptedWorkflowName = `S21 AI 人工审核工作流 ${Date.now()}`

  await page.goto('/')
  await authenticate(page)
  await page.getByRole('link', { name: 'AI 助手' }).click()
  await expect(page).toHaveURL(/\/ai$/)
  await expect(page.getByRole('heading', { name: 'AI 助手' })).toBeVisible()
  await expect(page.getByText(/AI 不会读取 Secret、自动发布或自动执行/)).toBeVisible()
  await expect(page.getByText('模型：flowtest-compose-model')).toBeVisible()

  await page.getByRole('button', { name: /新建 AI 任务/ }).click()
  const createDialog = page.getByRole('dialog', { name: '新建 AI 建议任务' })
  await createDialog.getByLabel('任务类型').click()
  await page.getByText('Workflow 草稿', { exact: true }).click()
  const created = page.waitForResponse(
    (response) =>
      response.url().endsWith('/api/v1/ai/jobs') && response.request().method() === 'POST',
  )
  await createDialog.getByRole('button', { name: '确 定' }).click()
  expect((await created).status()).toBe(202)

  const suggestionRow = page.getByRole('row').filter({ hasText: 'S21 AI 人工审核工作流' })
  await expect(suggestionRow).toContainText('pending', { timeout: 30_000 })
  await suggestionRow.getByRole('button', { name: /接受/ }).click()
  const reviewDialog = page.getByRole('dialog', { name: '接受并生成草稿' })
  const contentEditor = reviewDialog.getByLabel('建议内容')
  const content = JSON.parse(await contentEditor.inputValue()) as Record<string, unknown>
  content.name = acceptedWorkflowName
  await contentEditor.fill(JSON.stringify(content, null, 2))
  await reviewDialog.getByLabel('审核备注').fill('Playwright 人工确认')
  const accepted = page.waitForResponse(
    (response) => response.url().endsWith('/accept') && response.request().method() === 'POST',
  )
  await reviewDialog.getByRole('button', { name: '确 定' }).click()
  expect((await accepted).ok()).toBeTruthy()
  await expect(suggestionRow).toContainText('accepted')
  await expect(suggestionRow.getByRole('button', { name: /接受/ })).toBeDisabled()
})
