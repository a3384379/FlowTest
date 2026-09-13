import { authenticate } from './auth'
import { expect, type Locator, type Page } from '@playwright/test'
import type { ApiDetail, Workflow, WorkflowDefinition } from '../../src/lib/api'

export type EditorFixture = {
  projectId: string
  workflow: Workflow
  headers: Record<string, string>
  root: string
}

export async function seedEditor(
  page: Page,
  prepare?: (definition: WorkflowDefinition) => WorkflowDefinition,
): Promise<EditorFixture> {
  await page.goto('/')
  await authenticate(page)
  const refreshed = await page.request.post('/api/v1/auth/refresh')
  expect(refreshed.ok()).toBeTruthy()
  const authentication: { access_token: string } = await refreshed.json()
  const headers = { Authorization: `Bearer ${authentication.access_token}` }
  async function create<T = { id: string }>(
    path: string,
    data: unknown,
    method: 'post' | 'put' = 'post',
  ): Promise<T> {
    const response = await page.request[method](`/api/v1${path}`, { headers, data })
    expect(response.ok(), await response.text()).toBeTruthy()
    return response.json()
  }
  const project = await create('/projects', { name: `流程编辑验收 ${Date.now()}` })
  const root = `/projects/${project.id}`
  await create(
    `${root}/security-policy`,
    { allowed_hosts: ['mock-target'], allowed_private_cidrs: ['172.16.0.0/12'] },
    'put',
  )
  const environment = await create(`${root}/environments`, {
    name: '验收环境',
    base_url: 'http://mock-target:8080',
    classification: 'test',
  })
  const service = await create(`${root}/services`, {
    name: '验收服务',
    service_key: 'editor-acceptance',
  })
  await create(`${root}/environments/${environment.id}/service-endpoints`, {
    service_id: service.id,
    base_url: 'http://mock-target:8080',
  })
  const api = await create<ApiDetail>(`${root}/apis`, {
    name: '验收健康接口',
    service_id: service.id,
    request: { method: 'GET', path: '/health' },
  })
  const definition: WorkflowDefinition = {
    schema_version: '1.0',
    variables: {},
    nodes: [
      { id: 'start', type: 'start', name: '开始', position: { x: 0, y: 80 }, config: {} },
      {
        id: 'api',
        type: 'api',
        name: '健康检查',
        position: { x: 260, y: 80 },
        config: { api_definition_id: api.definition.id, api_version: api.version.version },
      },
      { id: 'end', type: 'end', name: '结束', position: { x: 520, y: 80 }, config: {} },
    ],
    edges: [
      { id: 'start-api', source: 'start', target: 'api', condition: null, mappings: [] },
      { id: 'api-end', source: 'api', target: 'end', condition: null, mappings: [] },
    ],
    settings: { fail_fast: true, concurrency: 20, default_timeout_seconds: 30 },
  }
  const prepared = prepare ? prepare(definition) : definition
  const workflow = await create<Workflow>(`${root}/workflows`, {
    name: '流程编辑器验收',
    definition: prepared,
  })
  await page.goto(`${root}/workflows`)
  await expect(page.locator('.react-flow__node')).toHaveCount(prepared.nodes.length)
  await expect(page.locator('.react-flow__edge')).toHaveCount(prepared.edges.length)
  return { projectId: project.id, workflow, headers, root }
}
export async function clickEdge(page: Page, id = 'start-api') {
  const path = page.locator(`.react-flow__edge[data-id="${id}"] .react-flow__edge-interaction`)
  await path.waitFor({ state: 'attached' })
  const hit = await path.evaluate((element) => {
    const svgPath = element as SVGPathElement
    const transform = svgPath.getScreenCTM()
    if (!transform) return null
    for (const fraction of [0.5, 0.2, 0.8, 0.1, 0.9]) {
      const point = svgPath
        .getPointAtLength(svgPath.getTotalLength() * fraction)
        .matrixTransform(transform)
      if (
        document.elementFromPoint(point.x, point.y)?.closest('.react-flow__edge') ===
        element.closest('.react-flow__edge')
      )
        return { x: point.x, y: point.y }
    }
    return null
  })
  expect(hit, '连线存在可点击且未被节点遮挡的命中区').not.toBeNull()
  await page.mouse.click(hit!.x, hit!.y)
  await expect(page.getByRole('heading', { name: '连线配置', exact: true })).toBeVisible()
}
export async function dragBetween(page: Page, source: Locator, target: Locator) {
  await source.click({ trial: true })
  await target.click({ trial: true })
  const from = await source.boundingBox()
  const to = await target.boundingBox()
  expect(from).not.toBeNull()
  expect(to).not.toBeNull()
  await page.mouse.move(from!.x + from!.width / 2, from!.y + from!.height / 2)
  await page.mouse.down()
  await page.mouse.move(to!.x + to!.width / 2, to!.y + to!.height / 2, { steps: 30 })
  await page.mouse.up()
}
export async function canvasKey(page: Page, key: string) {
  await page.getByLabel('工作流画布', { exact: true }).focus()
  await page.keyboard.press(key)
}
export async function closeInspector(page: Page) {
  const button = page.getByRole('button', { name: '关闭配置', exact: true })
  if (await button.isVisible()) await button.click()
  await page.getByRole('button', { name: 'Fit View', exact: true }).click()
}
export async function publishAndRun(page: Page) {
  await page.getByRole('button', { name: 'cloud-upload 发布服务器草稿', exact: true }).click()
  await page
    .getByRole('dialog', { name: '发布服务器草稿？', exact: true })
    .getByRole('button', { name: '发布服务器草稿', exact: true })
    .click()
  await page.getByRole('button', { name: 'play-circle 运行已发布版本', exact: true }).click()
  await expect(page.getByText('工作流执行通过').last()).toBeVisible({ timeout: 30000 })
}
