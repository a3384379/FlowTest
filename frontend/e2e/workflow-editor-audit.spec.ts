import { expect, test, type Page } from '@playwright/test'
import type { WorkflowDefinition } from '../src/lib/api'
import { canvasKey, clickEdge, seedEditor } from './support/workflow-editor'

test.use({ viewport: { width: 1920, height: 1080 } })
for (const type of ['api', 'capability'] as const) {
  for (const unmount of [false, true]) {
    test(`F01：${type} 请求配置 mounted=${!unmount} 通过服务端持久化校验`, async ({ page }) => {
      const fixture = await seedEditor(page, (definition) => ({
        ...definition,
        nodes: definition.nodes.map((node) => {
          if (node.id !== 'api') return node
          const config = {
            ...node.config,
            request_overrides: {
              auth_disabled: true,
              suppressed_headers: ['X-Fixture'],
              suppressed_cookies: ['fixture'],
            },
          }
          return type === 'api'
            ? { ...node, config }
            : {
                ...node,
                type,
                config: {},
                capability_id: 'http.request',
                capability_version: '2.0.0',
                configuration: config,
                bindings: [],
              }
        }),
      }))
      await page.locator('.react-flow__node[data-id=api]').click()
      await page.getByRole('button', { name: '最大化配置', exact: true }).click()
      for (const section of ['Params', 'Headers', 'Body']) {
        await page.getByRole('tab', { name: section, exact: true }).click()
        await page
          .getByRole('tabpanel', { name: new RegExp(`^${section}`) })
          .getByText('节点自定义', { exact: true })
          .click()
      }
      const body = page.getByRole('tabpanel', { name: /^Body/ })
      await body.getByText('raw', { exact: true }).click()
      await page.getByRole('textbox', { name: 'JSON Body', exact: true }).fill('{"fixture":true}')
      if (unmount) await page.getByRole('button', { name: '还原配置', exact: true }).click()
      await page.getByRole('button', { name: '应用节点配置', exact: true }).click()
      if (!unmount) await page.getByRole('button', { name: '还原配置', exact: true }).click()
      const response = page.waitForResponse(
        (response) =>
          response.url().endsWith(`/workflows/${fixture.workflow.id}`) &&
          response.request().method() === 'PATCH',
      )
      await page.getByRole('button', { name: '保存草稿', exact: true }).click()
      expect((await response).ok()).toBeTruthy()
      const persisted = await savedDefinition(page, fixture)
      const node = persisted.nodes.find((item) => item.id === 'api')!
      expect(node.type).toBe(type)
      if (type === 'capability') {
        expect(node.config).toEqual({})
        expect(node).toMatchObject({
          capability_id: 'http.request',
          capability_version: '2.0.0',
          bindings: [],
        })
      }
      const config = type === 'capability' ? node.configuration : node.config
      expect(config).toMatchObject({
        api_version: 1,
        request_overrides: {
          auth_disabled: true,
          suppressed_headers: ['X-Fixture'],
          suppressed_cookies: ['fixture'],
          body: { kind: 'json', value: { fixture: true } },
          headers: {},
          query_parameters: [],
        },
      })
    })
  }
}
test('F02：A v12 未应用请求的取消、恢复与确认切换到 B v2', async ({ page }) => {
  const fixture = await seedEditor(page)
  const definition = fixture.workflow.draft_definition
  const apiId = definition.nodes[1].config.api_definition_id as string
  const apiA = await page.request.get(`/api/v1${fixture.root}/apis/${apiId}`, {
    headers: fixture.headers,
  })
  expect(apiA.ok()).toBeTruthy()
  const serviceId = (await apiA.json()).definition.service_id
  async function version(id: string, owner: string) {
    const response = await page.request.post(`/api/v1${fixture.root}/apis/${id}/versions`, {
      headers: fixture.headers,
      data: {
        method: 'GET',
        path: '/health',
        query_parameters: [],
        headers: {},
        body_kind: 'json',
        body: { owner },
      },
    })
    expect(response.ok(), await response.text()).toBeTruthy()
  }
  for (let revision = 2; revision <= 12; revision++) await version(apiId, 'A')
  const createdB = await page.request.post(`/api/v1${fixture.root}/apis`, {
    headers: fixture.headers,
    data: {
      name: '候选接口 B',
      service_id: serviceId,
      request: { method: 'GET', path: '/health' },
    },
  })
  expect(createdB.ok()).toBeTruthy()
  const apiB = (await createdB.json()).definition.id as string
  await version(apiB, 'B')
  const changed = await page.request.patch(
    `/api/v1${fixture.root}/workflows/${fixture.workflow.id}`,
    {
      headers: fixture.headers,
      data: {
        expected_revision: fixture.workflow.draft_revision,
        definition: {
          ...definition,
          nodes: definition.nodes.map((node) =>
            node.id === 'api' ? { ...node, config: { ...node.config, api_version: 12 } } : node,
          ),
        },
      },
    },
  )
  expect(changed.ok()).toBeTruthy()
  await page.reload()
  await page.locator('.react-flow__node[data-id=api]').click()
  await page.getByRole('button', { name: '最大化配置', exact: true }).click()
  await expect(page.getByText('继承接口模板 v12')).toBeVisible()
  await page.getByRole('tab', { name: 'Body', exact: true }).click()
  await page
    .getByRole('tabpanel', { name: /^Body/ })
    .getByText('节点自定义', { exact: true })
    .click()
  await page.getByRole('textbox', { name: 'JSON Body', exact: true }).fill('{"pending":"A"}')
  await page.getByRole('button', { name: '还原配置', exact: true }).click()
  await chooseApiB(page)
  const modal = page.getByRole('dialog', { name: '切换请求目标？', exact: true })
  await modal.getByRole('button', { name: '取消切换', exact: true }).click()
  await expect(modal).toBeHidden()
  await expect(page.getByText('固定 v12')).toBeVisible()
  await page.getByRole('button', { name: '最大化配置', exact: true }).click()
  await expect(page.getByRole('textbox', { name: 'JSON Body', exact: true })).toHaveValue(
    '{"pending":"A"}',
  )
  await expect(page.getByRole('tab', { name: /^Body/ })).toHaveAttribute('aria-selected', 'true')
  await page.getByRole('button', { name: '还原配置', exact: true }).click()
  await chooseApiB(page)
  await modal.getByRole('button', { name: '丢弃请求草稿并切换', exact: true }).click()
  await expect(page.getByText('固定 v2')).toBeVisible()
  await page.getByRole('button', { name: '应用节点配置', exact: true }).click()
  await page.getByRole('button', { name: '保存草稿', exact: true }).click()
  await expect(page.getByText('草稿已保存').last()).toBeVisible()
  expect((await savedDefinition(page, fixture)).nodes[1].config).toMatchObject({
    api_definition_id: apiB,
    api_version: 2,
    request_overrides: {},
  })
})
async function chooseApiB(page: Page) {
  await page.locator('.workflow-inspector .config-target .ant-select').first().click()
  await page.getByTitle('候选接口 B', { exact: true }).click()
}
test('F03：80 字符映射编辑、第二行编辑、删除各自完整撤销', async ({ page }) => {
  await seedEditor(page)
  await clickEdge(page)
  await page.getByRole('button', { name: '添加映射', exact: true }).click()
  const source = page.getByRole('textbox', { name: '映射源表达式' })
  await source.fill('')
  await source.pressSequentially('x'.repeat(80))
  await source.press('Enter')
  await canvasKey(page, 'ControlOrMeta+z')
  await expect(source).toHaveValue('body')
  await canvasKey(page, 'ControlOrMeta+Shift+z')
  await expect(source).toHaveValue('x'.repeat(80))
  await page.getByRole('button', { name: '添加映射', exact: true }).click()
  const sources = page.getByRole('textbox', { name: '映射源表达式' })
  await sources.nth(1).fill('body.second')
  await sources.nth(1).press('Tab')
  await page.getByRole('button', { name: '删除映射', exact: true }).first().click()
  await canvasKey(page, 'ControlOrMeta+z')
  await expect(sources).toHaveCount(2)
  await expect(sources.nth(0)).toHaveValue('x'.repeat(80))
  await expect(sources.nth(1)).toHaveValue('body.second')
  await canvasKey(page, 'ControlOrMeta+z')
  await expect(sources.nth(1)).toHaveValue('body')
})
for (const zoom of [0.5, 1.5]) {
  test(`F04：${zoom * 100}% 缩放和平移不会被选中、名称、映射编辑覆盖`, async ({ page }) => {
    await seedEditor(page)
    await page.locator('.react-flow__node[data-id=api]').click()
    await page.getByRole('button', { name: 'aim 适应画布', exact: true }).click()
    await settleFitAnimation(page)
    await setZoomAndPan(page, zoom)
    const before = await viewport(page)
    await page.getByRole('textbox', { name: '名称', exact: true }).fill('视口保留')
    await page.getByRole('button', { name: '应用节点配置', exact: true }).click()
    await expect.poll(() => viewport(page)).toEqual(before)
    const divider = (await page
      .locator('.workflow-split-body .ant-splitter-bar')
      .last()
      .boundingBox())!
    await page.mouse.move(divider.x + divider.width / 2, divider.y + divider.height / 2)
    await page.mouse.down()
    await page.mouse.move(divider.x - 60, divider.y + divider.height / 2, { steps: 20 })
    await page.mouse.up()
    await expect.poll(async () => (await viewport(page)).zoom).toBeCloseTo(before.zoom, 4)
    await clickEdge(page)
    const edgeViewport = await viewport(page)
    await page.getByRole('button', { name: '添加映射', exact: true }).click()
    await page.getByRole('textbox', { name: '映射源表达式' }).fill('body.id')
    await page.getByRole('textbox', { name: '映射源表达式' }).press('Enter')
    await expect.poll(() => viewport(page)).toEqual(edgeViewport)
    await canvasKey(page, 'Escape')
    await expect(
      page.locator('.react-flow__node.selected, .react-flow__edge.selected'),
    ).toHaveCount(0)
    await expect.poll(() => viewport(page)).toEqual(edgeViewport)
    await page.getByRole('button', { name: 'aim 适应画布', exact: true }).click()
    await expect.poll(async () => (await viewport(page)).zoom).not.toBeCloseTo(zoom, 3)
  })
}
async function viewport(page: Page) {
  return page.locator('.react-flow__viewport').evaluate((element) => {
    const matrix = new DOMMatrix(getComputedStyle(element).transform)
    return { x: matrix.e, y: matrix.f, zoom: matrix.a }
  })
}
async function setZoomAndPan(page: Page, zoom: number) {
  const canvas = (await page.getByTestId('workflow-canvas-stage').boundingBox())!
  await page.mouse.move(canvas.x + canvas.width / 2, canvas.y + canvas.height / 2)
  // Native wheel deltas are integer pixels; correct once if that rounding is
  // visible, then compare every later operation with the actual viewport.
  for (let attempt = 0; attempt < 3; attempt++) {
    const current = (await viewport(page)).zoom
    if (Math.abs(current - zoom) < 0.002) break
    await page.mouse.wheel(0, Math.log2(current / zoom) * 500)
    await page.evaluate(
      () =>
        new Promise<void>((resolve) =>
          requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
        ),
    )
  }
  await expect.poll(async () => (await viewport(page)).zoom).toBeCloseTo(zoom, 2)
  const point = { x: canvas.x + canvas.width - 200, y: canvas.y + canvas.height - 100 }
  await page.mouse.move(point.x, point.y)
  await page.mouse.down()
  await page.mouse.move(point.x + 50, point.y - 30, { steps: 20 })
  await page.mouse.up()
}
async function settleFitAnimation(page: Page) {
  await page.evaluate(
    () =>
      new Promise<void>((resolve) => {
        const deadline = performance.now() + 220
        function next() {
          if (performance.now() >= deadline) resolve()
          else requestAnimationFrame(next)
        }
        requestAnimationFrame(next)
      }),
  )
}
async function savedDefinition(
  page: Page,
  fixture: Awaited<ReturnType<typeof seedEditor>>,
): Promise<WorkflowDefinition> {
  const response = await page.request.get(`/api/v1${fixture.root}/workflows`, {
    headers: fixture.headers,
  })
  expect(response.ok()).toBeTruthy()
  return (await response.json()).items.find(
    (item: { id: string }) => item.id === fixture.workflow.id,
  ).draft_definition
}
