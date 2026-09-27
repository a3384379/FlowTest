import { expect, test } from '@playwright/test'

import { publishAndRun, seedEditor } from './support/workflow-editor'

test('异步轮询模板只提交一次，再按固定版本 GET 查询到成功', async ({ page }) => {
  const fixture = await seedEditor(page)
  async function createApi(name: string, method: 'GET' | 'POST', path: string) {
    const response = await page.request.post(`/api/v1${fixture.root}/apis`, {
      headers: fixture.headers,
      data: { name, service_id: fixture.serviceId, request: { method, path } },
    })
    expect(response.ok(), await response.text()).toBeTruthy()
    return (await response.json()) as { definition: { id: string } }
  }
  const submit = await createApi('提交受控任务', 'POST', '/control/tasks')
  const poll = await createApi('查询受控任务', 'GET', '/control/tasks/status')
  await page.reload()
  await page.getByRole('button', { name: '工作流更多操作', exact: true }).click()
  await page
    .getByRole('tooltip')
    .getByRole('button', { name: /新建工作流/ })
    .click()
  const dialog = page.getByRole('dialog', { name: '新建工作流草稿' })
  await dialog.getByRole('textbox', { name: '名称' }).fill('异步轮询验收')
  await dialog.getByRole('combobox', { name: '起始模板' }).click()
  await page
    .locator('.ant-select-dropdown:visible')
    .getByText(/异步状态轮询 · 提交一次任务/)
    .click()
  const statusApi = dialog.getByRole('combobox', { name: '状态查询 API（GET）' })
  await statusApi.click()
  await statusApi.fill('查询受控任务')
  await page
    .locator('.ant-select-dropdown:visible')
    .last()
    .getByText('查询受控任务', { exact: true })
    .click()
  const submitApi = dialog.getByRole('combobox', { name: '任务提交 API（POST）' })
  await submitApi.click()
  await submitApi.fill('提交受控任务')
  await page
    .locator('.ant-select-dropdown:visible')
    .last()
    .getByText('提交受控任务', { exact: true })
    .click()
  await dialog.getByRole('button', { name: '创建草稿' }).click()
  await expect(page.getByText('工作流草稿已创建').last()).toBeVisible()
  await expect(page.locator('.react-flow__node')).toHaveCount(4)

  const workflows = await page.request.get(`/api/v1${fixture.root}/workflows`, {
    headers: fixture.headers,
  })
  expect(workflows.ok()).toBeTruthy()
  const created = (
    (await workflows.json()) as { items: Array<{ id: string; name: string }> }
  ).items.find((item) => item.name === '异步轮询验收')
  expect(created).toBeDefined()
  await publishAndRun(page)
  const executions = await page.request.get(
    `/api/v1${fixture.root}/workflow-executions?workflow_id=${created!.id}`,
    { headers: fixture.headers },
  )
  expect(executions.ok()).toBeTruthy()
  const run = ((await executions.json()) as { items: Array<{ id: string }> }).items[0]
  const detailResponse = await page.request.get(
    `/api/v1${fixture.root}/workflow-executions/${run.id}`,
    { headers: fixture.headers },
  )
  expect(detailResponse.ok()).toBeTruthy()
  const detail = (await detailResponse.json()) as {
    nodes: Array<{
      node_id: string
      output: { body?: Record<string, unknown>; polling_attempts?: number }
    }>
  }
  expect(detail.nodes.find((node) => node.node_id === 'submit')?.output.body?.submitCount).toBe(1)
  expect(detail.nodes.find((node) => node.node_id === 'api')?.output).toMatchObject({
    polling_attempts: 2,
    body: { taskId: 'mock-task', status: 'SUCCESS', submitCount: 1, pollCount: 2 },
  })
  expect(submit.definition.id).not.toBe(poll.definition.id)
})
