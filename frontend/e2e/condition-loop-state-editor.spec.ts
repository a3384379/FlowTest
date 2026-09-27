import { expect, test } from '@playwright/test'

import { publishAndRun, seedEditor } from './support/workflow-editor'

test('可视化修改条件循环状态后保存、发布并运行', async ({ page }) => {
  const fixture = await seedEditor(page, (definition) => ({
    ...definition,
    schema_version: '4.0',
    variables: { tenant: 'flowtest' },
    run_policy: {
      request_budget: 20,
      max_runtime_seconds: 60,
      cleanup_request_budget: null,
      force_cancel_skips_cleanup: true,
    },
    nodes: [
      definition.nodes[0],
      {
        id: 'loop',
        type: 'capability',
        name: '分页循环',
        position: { x: 260, y: 80 },
        config: {},
        capability_id: 'flow.control.while',
        capability_version: '1.0.0',
        configuration: {
          condition: {
            kind: 'compare',
            left: { kind: 'variable', scope: 'state', path: ['page'] },
            operator: 'lt',
            right: { kind: 'literal', value: 3 },
          },
          body: { kind: 'inline', region_id: 'region' },
          inputs: {},
          state: { page: { kind: 'literal', value: 0 } },
          update: { page: { kind: 'add', value: { kind: 'literal', value: 1 } } },
          policy: { concurrency: 1, max_iterations: 5, timeout_seconds: 30, on_error: 'stop' },
        },
        bindings: [],
      },
      definition.nodes[2],
    ],
    edges: [
      { id: 'start-loop', source: 'start', target: 'loop', condition: null, mappings: [] },
      { id: 'loop-end', source: 'loop', target: 'end', condition: null, mappings: [] },
    ],
    regions: [
      {
        id: 'region',
        owner_node_id: 'loop',
        role: 'body',
        nodes: [
          {
            id: 'wait',
            type: 'delay',
            name: '本轮等待',
            position: { x: 0, y: 0 },
            config: { seconds: 0 },
          },
        ],
        edges: [],
        entry_node_id: 'wait',
        exit_node_ids: ['wait'],
        inputs: {},
        outputs: {},
      },
    ],
  }))

  await page.locator('.react-flow__node[data-id=loop]').click()
  const source = page.getByRole('textbox', { name: 'page 初始值 JSON 值' })
  await source.fill('1')
  await page.getByLabel('page 初始值').getByRole('button', { name: '应用值' }).click()
  await page.getByRole('textbox', { name: '新增控制块输入名称' }).fill('tenant')
  await page.getByRole('button', { name: '添加控制块输入' }).click()
  await page.getByRole('combobox', { name: '控制块输入 tenant 来源浏览器' }).click()
  await page.getByText('工作流变量 · tenant').click()
  await page.getByRole('button', { name: '应用节点配置' }).click()
  await page.getByRole('textbox', { name: '新增body 区域输入名称' }).fill('currentPage')
  await page.getByRole('button', { name: '添加body 区域输入' }).click()
  await page.getByRole('combobox', { name: 'body 区域输入 currentPage 来源浏览器' }).click()
  await page.locator('.ant-select-dropdown:visible').getByText('当前块状态 · page').click()
  await page.getByRole('textbox', { name: '新增body 区域输出名称' }).fill('lastWait')
  await page.getByRole('button', { name: '添加body 区域输出' }).click()
  await page.getByRole('combobox', { name: 'body 区域输出 lastWait 来源浏览器' }).click()
  await page.locator('.ant-select-dropdown:visible').getByText('节点输出 · 本轮等待').click()
  await page.getByRole('button', { name: '保存草稿' }).click()
  await expect(page.getByText('草稿已保存').last()).toBeVisible()
  const response = await page.request.get(
    `/api/v1${fixture.root}/workflows/${fixture.workflow.id}`,
    { headers: fixture.headers },
  )
  expect(response.ok()).toBeTruthy()
  const saved = (await response.json()) as {
    draft_definition: {
      nodes: Array<{ id: string; configuration?: Record<string, unknown> }>
      regions: Array<{
        inputs: Record<string, unknown>
        outputs: Record<string, unknown>
      }>
    }
  }
  expect(saved.draft_definition.nodes.find((node) => node.id === 'loop')?.configuration).toEqual(
    expect.objectContaining({
      state: { page: { kind: 'literal', value: 1 } },
      inputs: { tenant: { kind: 'variable', scope: 'workflow', path: ['tenant'] } },
    }),
  )
  expect(saved.draft_definition.regions[0].inputs.currentPage).toEqual({
    kind: 'variable',
    scope: 'state',
    path: ['page'],
  })
  expect(saved.draft_definition.regions[0].outputs.lastWait).toEqual({
    kind: 'node_output',
    node_id: 'wait',
    path: [],
  })
  await publishAndRun(page)
})
