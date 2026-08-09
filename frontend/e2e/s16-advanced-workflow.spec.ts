import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

import { authenticate } from './support/auth'

type Identified = { id: string }
type Workflow = Identified & { draft_revision: number }

test('S16 子流程、ForEach、调试重放与画布编辑主路径', async ({ page }) => {
  test.setTimeout(90_000)
  const suffix = Date.now().toString()

  await page.goto('/')
  await authenticate(page)

  const accessToken = await accessTokenFromSession(page.request)
  const project = await firstProject(page.request, accessToken)
  const child = await createPublishedChild(page.request, accessToken, project.id, suffix)
  const parentName = `S16 ForEach 编排 ${suffix}`
  await createVersionedParent(page.request, accessToken, project.id, child.id, parentName)

  await page.getByRole('link', { name: '流程编排' }).click()
  await expect(page.getByRole('heading', { name: '流程编排' })).toBeVisible()
  await page.getByRole('row').filter({ hasText: parentName }).first().click()
  await expect(page.getByText('已发布 v2')).toBeVisible()

  await verifyCanvasEditing(page)
  await verifyVersionDiff(page)
  await verifyExecutionDebugAndReplay(page)
})

async function verifyCanvasEditing(page: Page) {
  const forEachNode = page.locator('.react-flow__node[data-id="foreach"]')
  await expect(forEachNode).toContainText('批量调用 v2')
  await forEachNode.click()
  await expect(page.getByText('已发布子流程')).toBeVisible()
  await expect(page.getByText('循环并发')).toBeVisible()

  await page.getByRole('button', { name: /复s*制/ }).click()
  await page.getByRole('button', { name: /粘s*贴/ }).click()
  await expect(page.locator('.react-flow__node')).toHaveCount(4)
  await page.getByRole('button', { name: /撤s*销/ }).click()
  await expect(page.locator('.react-flow__node')).toHaveCount(3)
  await page.getByRole('button', { name: /重s*做/ }).click()
  await expect(page.locator('.react-flow__node')).toHaveCount(4)
  await page.getByRole('button', { name: /撤s*销/ }).click()
  await page.getByRole('button', { name: /自动布局/ }).click()
}

async function verifyVersionDiff(page: Page) {
  await page.getByRole('button', { name: /版本 Diff/ }).click()
  const dialog = page.getByRole('dialog', { name: '工作流版本 Diff' })
  await expect(dialog).toContainText('批量调用 v1')
  await expect(dialog).toContainText('批量调用 v2')
  await dialog.locator('.ant-modal-close').click()
  await expect(dialog).toBeHidden()
}

async function verifyExecutionDebugAndReplay(page: Page) {
  await page.getByRole('button', { name: /运\s*行/ }).click()
  await expect(page.getByText('工作流执行通过').last()).toBeVisible({ timeout: 30_000 })

  const latestRun = page.locator('.ant-card').filter({ hasText: '最近一次运行' })
  const forEachRow = latestRun.getByRole('row').filter({ hasText: '批量调用 v2' })
  await expect(forEachRow).toContainText('passed')
  await forEachRow.getByRole('button', { name: /重s*放/ }).click()
  await expect(page.getByText('节点重放结果')).toBeVisible()
  await expect(page.locator('.ant-card').filter({ hasText: '节点重放结果' })).toContainText(
    'passed',
  )

  await page.getByLabel('调试断点').click()
  await page.getByText('批量调用 v2', { exact: true }).last().click()
  await page.getByRole('button', { name: /调试至断点/ }).click()
  await expect(page.getByText('断点调试结果')).toBeVisible()
  await expect(page.locator('.ant-card').filter({ hasText: '断点调试结果' })).toContainText(
    'passed',
  )
}

async function accessTokenFromSession(request: APIRequestContext): Promise<string> {
  const response = await request.post('/api/v1/auth/refresh')
  expect(response.ok(), await response.text()).toBeTruthy()
  return ((await response.json()) as { access_token: string }).access_token
}

async function firstProject(request: APIRequestContext, token: string): Promise<Identified> {
  const response = await request.get('/api/v1/projects?page=1&page_size=1', {
    headers: authorization(token),
  })
  expect(response.ok(), await response.text()).toBeTruthy()
  const body = (await response.json()) as { items: Identified[] }
  expect(body.items.length).toBeGreaterThan(0)
  return body.items[0]
}

async function createPublishedChild(
  request: APIRequestContext,
  token: string,
  projectId: string,
  suffix: string,
): Promise<Workflow> {
  const child = await createWorkflow(request, token, projectId, {
    name: `S16 子流程 ${suffix}`,
    description: 'S16 固定版本子流程',
    definition: linearDefinition('子流程结束'),
  })
  await publishWorkflow(request, token, projectId, child.id)
  return child
}

async function createVersionedParent(
  request: APIRequestContext,
  token: string,
  projectId: string,
  childId: string,
  name: string,
) {
  const firstDefinition = forEachDefinition(childId, '批量调用 v1')
  const parent = await createWorkflow(request, token, projectId, {
    name,
    description: 'S16 ForEach 固定子流程快照',
    definition: firstDefinition,
  })
  await publishWorkflow(request, token, projectId, parent.id)

  const response = await request.patch(`/api/v1/projects/${projectId}/workflows/${parent.id}`, {
    headers: authorization(token),
    data: {
      expected_revision: parent.draft_revision,
      definition: forEachDefinition(childId, '批量调用 v2'),
    },
  })
  expect(response.ok(), await response.text()).toBeTruthy()
  await publishWorkflow(request, token, projectId, parent.id)
}

async function createWorkflow(
  request: APIRequestContext,
  token: string,
  projectId: string,
  payload: Record<string, unknown>,
): Promise<Workflow> {
  const response = await request.post(`/api/v1/projects/${projectId}/workflows`, {
    headers: authorization(token),
    data: payload,
  })
  expect(response.ok(), await response.text()).toBeTruthy()
  return (await response.json()) as Workflow
}

async function publishWorkflow(
  request: APIRequestContext,
  token: string,
  projectId: string,
  workflowId: string,
) {
  const response = await request.post(
    `/api/v1/projects/${projectId}/workflows/${workflowId}/versions`,
    { headers: authorization(token) },
  )
  expect(response.ok(), await response.text()).toBeTruthy()
}

function linearDefinition(endName: string) {
  return {
    schema_version: '1.0',
    variables: {},
    nodes: [node('start', 'start', '开始', 0), node('end', 'end', endName, 440)],
    edges: [edge('start-end', 'start', 'end')],
    settings: settings(),
  }
}

function forEachDefinition(childId: string, forEachName: string) {
  return {
    schema_version: '1.0',
    variables: { scenario: 's16-e2e' },
    nodes: [
      node('start', 'start', '开始', 0),
      {
        ...node('foreach', 'for_each', forEachName, 220),
        config: {
          workflow_id: childId,
          workflow_version: 1,
          source_node_id: 'start',
          expression: '[variables]',
          item_variable: 'item',
          index_variable: 'index',
          concurrency: 5,
          fail_fast: true,
        },
      },
      node('end', 'end', '结束', 440),
    ],
    edges: [edge('start-foreach', 'start', 'foreach'), edge('foreach-end', 'foreach', 'end')],
    settings: settings(),
  }
}

function node(id: string, type: string, name: string, x: number) {
  return { id, type, name, position: { x, y: 80 }, config: {} }
}

function edge(id: string, source: string, target: string) {
  return { id, source, target, condition: null, mappings: [] }
}

function settings() {
  return { fail_fast: true, concurrency: 20, default_timeout_seconds: 30 }
}

function authorization(token: string) {
  return { Authorization: `Bearer ${token}` }
}
