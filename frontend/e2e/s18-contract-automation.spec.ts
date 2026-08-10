import { expect, test } from '@playwright/test'

import { authenticate } from './support/auth'

test('S18 契约 Diff、Schema 覆盖率与生成草稿审核主路径', async ({ page }) => {
  test.setTimeout(90_000)
  const suffix = Date.now().toString()

  await page.goto('/')
  await authenticate(page)
  await page.getByRole('link', { name: '测试资产' }).click()
  await page.getByRole('tab', { name: '契约自动化' }).click()

  const schema = openApiSchema(`S18 Contract ${suffix}`)
  await page.locator('input[type="file"]').setInputFiles({
    name: `s18-${suffix}.json`,
    mimeType: 'application/json',
    buffer: Buffer.from(JSON.stringify(schema)),
  })
  const created = page.waitForResponse(
    (response) =>
      response.url().includes('/contract-runs') && response.request().method() === 'POST',
  )
  await page.getByRole('button', { name: /生成契约用例/ }).click()
  expect((await created).status()).toBe(201)

  const runRow = page.getByRole('row').filter({ hasText: `s18-${suffix}.json` })
  await expect(runRow).toContainText('100%')
  await runRow.getByRole('button', { name: /审核用例/ }).click()
  await expect(page.getByText('生成草稿审核')).toBeVisible()
  const caseTable = page.locator('.ant-card').filter({ hasText: '生成草稿审核' })
  await expect(caseTable.getByRole('row').filter({ hasText: '/users' })).toHaveCount(3)

  const boundary = caseTable.getByRole('row').filter({ hasText: '边界' }).last()
  await boundary.getByRole('button', { name: /编辑并接受/ }).click()
  const dialog = page.getByRole('dialog', { name: '编辑并接受契约用例' })
  await dialog.getByLabel('审核说明').fill('Playwright 确认 Schema 边界')
  const accepted = page.waitForResponse(
    (response) => response.url().endsWith('/accept') && response.request().method() === 'POST',
  )
  await dialog.getByRole('button', { name: '接受草稿' }).click()
  expect((await accepted).ok()).toBeTruthy()
  await expect(boundary).toContainText('已接受')

  const negative = caseTable.getByRole('row').filter({ hasText: '异常' }).last()
  const rejected = page.waitForResponse(
    (response) => response.url().endsWith('/reject') && response.request().method() === 'POST',
  )
  await negative.getByRole('button', { name: /拒绝/ }).click()
  expect((await rejected).ok()).toBeTruthy()
  await expect(negative).toContainText('已拒绝')
})

function openApiSchema(title: string) {
  return {
    openapi: '3.0.3',
    info: { title, version: '1.0.0' },
    paths: {
      '/users': {
        get: {
          operationId: 'listUsers',
          parameters: [
            {
              name: 'limit',
              in: 'query',
              required: false,
              schema: { type: 'integer', minimum: 1, maximum: 100 },
            },
          ],
          responses: {
            '200': {
              description: 'OK',
              content: {
                'application/json': {
                  schema: {
                    type: 'object',
                    properties: { count: { type: 'integer' } },
                  },
                },
              },
            },
          },
        },
      },
    },
  }
}
