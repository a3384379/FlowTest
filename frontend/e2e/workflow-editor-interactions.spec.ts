import { expect, test } from '@playwright/test'
import {
  canvasKey,
  clickEdge,
  closeInspector,
  dragBetween,
  publishAndRun,
  reconnectEdgeBetween,
  seedEditor,
} from './support/workflow-editor'

test.use({ viewport: { width: 1920, height: 1080 } })
test('SEL/DEL/EDGE：真实连线命中、创建、重连、映射确认与撤销', async ({ page }) => {
  await seedEditor(page)
  await clickEdge(page)
  await expect(page.getByRole('heading', { name: '连接关系' })).toBeVisible()
  await canvasKey(page, 'Delete')
  await expect(page.locator('.react-flow__edge')).toHaveCount(1)
  await dragBetween(
    page,
    page.locator('.react-flow__node[data-id=start] .source'),
    page.locator('.react-flow__node[data-id=api] .target'),
  )
  await expect(page.locator('.react-flow__edge')).toHaveCount(2)
  await canvasKey(page, 'ControlOrMeta+z')
  await expect(page.locator('.react-flow__edge')).toHaveCount(1)
  await canvasKey(page, 'ControlOrMeta+z')
  await expect(page.locator('.react-flow__edge')).toHaveCount(2)
  await page.getByRole('button', { name: '添加映射', exact: true }).click()
  await page.getByRole('button', { name: 'aim 适应画布', exact: true }).click()
  await reconnectEdgeBetween(
    page,
    page.locator('.react-flow__edge[data-id=start-api] .react-flow__edgeupdater-target'),
    page.locator('.react-flow__node[data-id=end] .target'),
  )
  const reconnect = page.getByRole('dialog', { name: '重新绑定映射端点', exact: true })
  await reconnect.getByRole('button', { name: /取\s*消/ }).click()
  await expect(reconnect).toBeHidden()
  await expect(page.locator('.react-flow__edge[data-id=start-api]')).toHaveAttribute(
    'aria-label',
    '从 开始 到 健康检查 的连线',
  )
  await page.getByRole('button', { name: '删除连线', exact: true }).click()
  const removal = page.getByRole('dialog', { name: '删除选中对象', exact: true })
  await expect(removal).toContainText('1 条字段映射')
  await removal.getByRole('button', { name: '确认删除', exact: true }).click()
  await expect(removal).toBeHidden()
  await canvasKey(page, 'ControlOrMeta+z')
  await expect(page.getByRole('textbox', { name: '映射源表达式' })).toHaveValue('body')
})

test('HIST/KEY/PAL：拖动单事务、输入焦点保护和节点库新增', async ({ page }) => {
  await seedEditor(page)
  const node = page.locator('.react-flow__node[data-id=api]')
  const before = await node.evaluate((element) => element.style.transform)
  const box = (await node.boundingBox())!
  await page.mouse.move(box.x + 50, box.y + 30)
  await page.mouse.down()
  await page.mouse.move(box.x + 130, box.y + 90, { steps: 50 })
  await page.mouse.up()
  await expect.poll(() => node.evaluate((element) => element.style.transform)).not.toBe(before)
  await canvasKey(page, 'ControlOrMeta+z')
  await expect.poll(() => node.evaluate((element) => element.style.transform)).toBe(before)
  await node.click()
  const name = page.getByRole('textbox', { name: '名称', exact: true })
  await name.fill('输入焦点')
  await name.press('Backspace')
  await expect(page.locator('.react-flow__node')).toHaveCount(3)
  await page.getByRole('button', { name: '应用节点配置', exact: true }).click()
  await canvasKey(page, 'ControlOrMeta+z')
  await expect(name).toHaveValue('健康检查')
  await name.fill('撤销后继续编辑')
  await page.getByRole('button', { name: '应用节点配置', exact: true }).click()
  await expect(page.getByText('节点内容已从外部更新', { exact: false })).toHaveCount(0)
  await closeInspector(page)
  await page.getByRole('button', { name: 'plus 添加节点', exact: true }).click()
  await page.getByRole('button', { name: '基础', exact: true }).click()
  await page
    .locator('.workflow-library-card')
    .filter({ hasText: '等待' })
    .dragTo(page.getByLabel('工作流画布', { exact: true }), { targetPosition: { x: 180, y: 140 } })
  await expect(page.locator('.react-flow__node')).toHaveCount(4)
  await page.getByRole('button', { name: '返回画布', exact: true }).click()
  await page.getByRole('button', { name: 'undo 撤销', exact: true }).click()
  await expect(page.locator('.react-flow__node')).toHaveCount(3)
})

test('FORM/LIFE：原始请求会话、保存、固定版本运行和只读历史', async ({ page }) => {
  const fixture = await seedEditor(page)
  await page.locator('.react-flow__node[data-id=api]').click()
  await page.getByRole('button', { name: 'setting 配置节点请求', exact: true }).click()
  const drawer = page.getByRole('dialog', { name: '节点请求配置', exact: true })
  await page
    .getByRole('tabpanel', { name: /^Params/ })
    .getByText('节点自定义', { exact: true })
    .click()
  await page
    .getByRole('tabpanel', { name: /^Params/ })
    .getByRole('button', { name: '批量编辑', exact: true })
    .click()
  await page.getByRole('textbox', { name: '批量编辑 Params' }).fill('未完成的原始输入')
  await drawer.getByRole('button', { name: '最大化', exact: true }).click()
  await drawer.getByRole('button', { name: /还\s*原/ }).click()
  await drawer.getByRole('button', { name: '关闭', exact: true }).click()
  await page.getByRole('button', { name: 'setting 配置节点请求', exact: true }).click()
  await expect(page.getByRole('textbox', { name: '批量编辑 Params' })).toHaveValue(
    '未完成的原始输入',
  )
  await page.getByRole('textbox', { name: '批量编辑 Params' }).fill('acceptance: preserved')
  await page.getByRole('button', { name: '应用并返回表格', exact: true }).click()
  await page.getByRole('button', { name: '保存节点配置', exact: true }).click()
  await page.getByRole('button', { name: '保存草稿', exact: true }).click()
  await expect(page.getByText('草稿已保存').last()).toBeVisible()
  const saved = await page.request.get(`/api/v1${fixture.root}/workflows`, {
    headers: fixture.headers,
  })
  expect(saved.ok()).toBeTruthy()
  expect(
    (await saved.json()).items[0].draft_definition.nodes[1].config.request_overrides
      .query_parameters,
  ).toEqual([{ name: 'acceptance', value: 'preserved', enabled: true }])
  await publishAndRun(page)
  const editorMain = page.getByTestId('workflow-editor-main')
  const runtimeDock = editorMain.getByTestId('workflow-runtime-dock')
  await expect(runtimeDock).toBeVisible()
  await expect
    .poll(async () => (await runtimeDock.boundingBox())?.height ?? 0)
    .toBeGreaterThanOrEqual(200)
  await expect
    .poll(async () => (await runtimeDock.boundingBox())?.height ?? 999)
    .toBeLessThanOrEqual(280)
  await page.getByTestId('workflow-runtime-tab-history').click()
  await page.locator('[data-testid^="workflow-history-"]').first().click()
  await expect(page.getByText('历史快照 · 只读')).toBeVisible()
  await expect(page.locator('.react-flow__edge')).toHaveCount(2)
  await canvasKey(page, 'ControlOrMeta+a')
  await canvasKey(page, 'Delete')
  await expect(page.locator('.react-flow__node')).toHaveCount(3)
  await expect(page.locator('.react-flow__edge')).toHaveCount(2)
})

test('ACC/FORM/PAL：从节点库建立四节点流程，保存前不执行，断言不冒充 HTTP 响应', async ({
  page,
}) => {
  const fixture = await seedEditor(page)
  const executions: string[] = []
  page.on('request', (request) => {
    if (request.method() === 'POST' && /\/executions(?:\?|$)/.test(request.url()))
      executions.push(request.postData() ?? '')
  })
  await page.locator('.react-flow__node[data-id=api]').click()
  await closeInspector(page)
  await page.getByRole('button', { name: 'plus 添加节点', exact: true }).click()
  await page.getByRole('button', { name: '控制与校验', exact: true }).click()
  await page.getByRole('button', { name: 'plus 添加断言校验', exact: true }).click()
  await page.getByRole('button', { name: '返回画布', exact: true }).click()
  const assertion = page.locator('.react-flow__node').filter({ hasText: '断言校验' })
  await expect(assertion).toHaveCount(1)
  const assertionId = await assertion.getAttribute('data-id')
  await closeInspector(page)
  await page.getByRole('button', { name: 'apartment 自动布局', exact: true }).click()
  await page.getByRole('button', { name: 'aim 适应画布', exact: true }).click()
  await clickEdge(page, 'api-end')
  await canvasKey(page, 'Delete')
  await closeInspector(page)
  await dragBetween(
    page,
    page.locator('.react-flow__node[data-id=api] .source'),
    assertion.locator('.target'),
  )
  await expect(page.locator('.react-flow__edge')).toHaveCount(2)
  await dragBetween(
    page,
    assertion.locator('.source'),
    page.locator('.react-flow__node[data-id=end] .target'),
  )
  await expect(page.locator('.react-flow__edge')).toHaveCount(3)
  await page.getByRole('button', { name: '保存草稿', exact: true }).click()
  await expect(page.getByText('草稿已保存').last()).toBeVisible()
  expect(executions).toEqual([])
  const saved = await page.request.get(`/api/v1${fixture.root}/workflows`, {
    headers: fixture.headers,
  })
  expect(saved.ok()).toBeTruthy()
  const definition = (await saved.json()).items[0].draft_definition
  expect(
    definition.nodes.find((node: { id: string }) => node.id === assertionId).config.source_node_id,
  ).toBe('api')
  await publishAndRun(page)
  expect(executions).toHaveLength(1)
  expect(JSON.parse(executions[0])).toMatchObject({ version: 1 })
  await assertion.click()
  const inspector = page.locator('.workflow-run-inspector')
  await inspector.getByRole('tab', { name: '请求', exact: true }).click()
  await expect(inspector.getByText('该节点没有 HTTP 请求记录')).toBeVisible()
  await inspector.getByRole('tab', { name: '响应', exact: true }).click()
  await expect(inspector.getByText('暂无响应数据')).toBeVisible()
  await expect(inspector.getByText('HTTP 200', { exact: true })).toHaveCount(0)
})

test('SEL/HIST/KEY：单选互斥、单节点移动撤销、取消拖动与输入焦点保护', async ({ page }) => {
  await seedEditor(page)
  const api = page.locator('.react-flow__node[data-id=api]')
  const end = page.locator('.react-flow__node[data-id=end]')
  await api.click()
  await page.getByRole('button', { name: 'aim 适应画布', exact: true }).click()
  await expect(page.locator('.react-flow__node.selected')).toHaveCount(1)
  await end.click({ modifiers: ['Shift'] })
  await expect(page.locator('.react-flow__node.selected')).toHaveCount(1)
  await expect(end).toHaveClass(/selected/)
  const original = await Promise.all(
    [api, end].map((node) => node.evaluate((element) => element.style.transform)),
  )
  const bounds = (await end.boundingBox())!
  await page.mouse.move(bounds.x + 45, bounds.y + 25)
  await page.mouse.down()
  await page.mouse.move(bounds.x + 95, bounds.y + 75, { steps: 30 })
  await page.mouse.up()
  await expect.poll(() => api.evaluate((element) => element.style.transform)).toBe(original[0])
  await expect.poll(() => end.evaluate((element) => element.style.transform)).not.toBe(original[1])
  await canvasKey(page, 'ControlOrMeta+z')
  for (const [index, node] of [api, end].entries())
    await expect
      .poll(() => node.evaluate((element) => element.style.transform))
      .toBe(original[index])
  await api.click()
  const name = page.getByRole('textbox', { name: '名称', exact: true })
  await name.fill('焦点保护')
  await page.getByLabel('工作流画布', { exact: true }).hover()
  await page.keyboard.press('Backspace')
  await expect(name).toHaveValue('焦点保')
  await expect(page.locator('.react-flow__node')).toHaveCount(3)
  await page.getByRole('button', { name: '应用节点配置', exact: true }).click()
  await closeInspector(page)
  const beforeCancel = await api.evaluate((element) => element.style.transform)
  const box = (await api.boundingBox())!
  await page.getByLabel('工作流画布', { exact: true }).focus()
  await page.mouse.move(box.x + 45, box.y + 25)
  await page.mouse.down()
  await page.mouse.move(box.x + 115, box.y + 70, { steps: 20 })
  await page.keyboard.press('Escape')
  await page.mouse.up()
  await expect.poll(() => api.evaluate((element) => element.style.transform)).toBe(beforeCancel)
})

test('EDGE/DEL：同目标真假分支的交换、删除确认、撤销和非法连接', async ({ page }) => {
  await seedEditor(page, (definition) => ({
    ...definition,
    nodes: [
      ...definition.nodes.map((node) =>
        node.id === 'end' ? { ...node, position: { x: 780, y: 80 } } : node,
      ),
      {
        id: 'condition',
        type: 'condition',
        name: '状态分支',
        position: { x: 520, y: 80 },
        config: {
          source_node_id: 'api',
          expression: 'status_code',
          operator: 'equals',
          expected: 200,
        },
      },
    ],
    edges: [
      definition.edges[0],
      { id: 'api-condition', source: 'api', target: 'condition', condition: null, mappings: [] },
      { id: 'true-end', source: 'condition', target: 'end', condition: 'true', mappings: [] },
      { id: 'false-end', source: 'condition', target: 'end', condition: 'false', mappings: [] },
    ],
  }))
  await clickEdge(page, 'true-end')
  await expect(
    page.locator('.workflow-inspector').getByText('条件为真', { exact: true }),
  ).toBeVisible()
  await page.getByRole('button', { name: '交换真假分支', exact: true }).click()
  await expect(
    page.locator('.workflow-inspector').getByText('条件为假', { exact: true }),
  ).toBeVisible()
  await canvasKey(page, 'ControlOrMeta+z')
  await expect(
    page.locator('.workflow-inspector').getByText('条件为真', { exact: true }),
  ).toBeVisible()
  await canvasKey(page, 'Delete')
  const removal = page.getByRole('dialog', { name: '删除选中对象', exact: true })
  await removal.getByRole('button', { name: '确认删除', exact: true }).click()
  await expect(removal).toBeHidden()
  await expect(page.locator('.react-flow__edge')).toHaveCount(3)
  await canvasKey(page, 'ControlOrMeta+z')
  await expect(page.locator('.react-flow__edge[data-id=true-end]')).toHaveCount(1)
  await expect(
    page.locator('.workflow-inspector').getByText('条件为真', { exact: true }),
  ).toBeVisible()
  await closeInspector(page)
  await dragBetween(
    page,
    page.locator('.react-flow__node[data-id=api] .source'),
    page.locator('.react-flow__node[data-id=api] .target'),
  )
  await expect(page.locator('.react-flow__edge')).toHaveCount(4)
})

test('FORM/KEY/LIFE：无效 JSON 保留、顶栏写保护及路由往返恢复请求会话', async ({ page }) => {
  await seedEditor(page)
  await page.locator('.react-flow__node[data-id=api]').click()
  await page.getByRole('button', { name: 'setting 配置节点请求', exact: true }).click()
  const drawer = page.getByRole('dialog', { name: '节点请求配置', exact: true })
  await drawer.getByRole('tab', { name: 'Body', exact: true }).click()
  const body = drawer.getByRole('tabpanel', { name: /^Body/ })
  await body.getByText('节点自定义', { exact: true }).click()
  await body.getByText('raw', { exact: true }).click()
  const json = page.getByRole('textbox', { name: 'JSON Body', exact: true })
  await json.fill('{"unfinished":')
  await drawer.getByRole('button', { name: '保存节点配置', exact: true }).click()
  await expect(json).toHaveValue('{"unfinished":')
  await expect(drawer.getByText('请修正请求字段和 JSON 格式后再应用。')).toBeVisible()
  await drawer.getByRole('button', { name: '最大化', exact: true }).click()
  await page.keyboard.press('Escape')
  await expect(drawer).toBeVisible()
  await expect(drawer.getByRole('button', { name: '最大化', exact: true })).toBeVisible()
  await expect(json).toBeVisible()
  await expect(json).toHaveValue('{"unfinished":')
  await drawer.getByRole('button', { name: '关闭', exact: true }).click()
  await page.getByRole('button', { name: '保存草稿', exact: true }).click()
  await expect(page.getByText(/有尚未应用的节点配置/).last()).toBeVisible()
  await page.getByRole('menuitem', { name: '接口管理' }).click()
  await page.getByRole('button', { name: '保留草稿并切换', exact: true }).click()
  await expect(page.locator('.workflow-workspace-page')).toHaveCount(0)
  await page.getByRole('menuitem', { name: '流程编排' }).click()
  await page.getByRole('button', { name: '保留草稿并切换', exact: true }).click()
  await page.locator('.react-flow__node[data-id=api]').click()
  await page.getByRole('button', { name: 'setting 配置节点请求', exact: true }).click()
  await expect(json).toHaveValue('{"unfinished":')
  await expect(drawer.getByRole('tab', { name: /^Body/ })).toHaveAttribute('aria-selected', 'true')
  await json.fill('{"complete":true}')
  await drawer.getByRole('button', { name: '保存节点配置', exact: true }).click()
  await page.getByRole('button', { name: '保存草稿', exact: true }).click()
  await expect(page.getByText('草稿已保存').last()).toBeVisible()
})

test('FORM：全屏请求编辑在还原后仍由外层应用动作提交', async ({ page }) => {
  const fixture = await seedEditor(page)
  await page.locator('.react-flow__node[data-id=api]').click()
  await page.getByRole('button', { name: '最大化配置', exact: true }).click()
  await page.getByRole('tab', { name: 'Body', exact: true }).click()
  const body = page.getByRole('tabpanel', { name: /^Body/ })
  await body.getByText('节点自定义', { exact: true }).click()
  await body.getByText('raw', { exact: true }).click()
  await page.getByRole('textbox', { name: 'JSON Body', exact: true }).fill('{"preserved":true}')
  await page.getByRole('button', { name: '还原配置', exact: true }).click()
  await page.getByRole('button', { name: '应用节点配置', exact: true }).click()
  await page.getByRole('button', { name: '保存草稿', exact: true }).click()
  await expect(page.getByText('草稿已保存').last()).toBeVisible()

  const saved = await page.request.get(`/api/v1${fixture.root}/workflows`, {
    headers: fixture.headers,
  })
  expect(saved.ok()).toBeTruthy()
  expect((await saved.json()).items[0].draft_definition.nodes[1].config).toMatchObject({
    api_version: 1,
    request_overrides: { body: { kind: 'json', value: { preserved: true } } },
  })
})
