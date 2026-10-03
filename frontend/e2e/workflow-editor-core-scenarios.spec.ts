import { expect, test, type Page, type TestInfo } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { readFileSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { createHash } from 'node:crypto'
import type {
  WorkflowDefinition,
  WorkflowNode,
  WorkflowRegion,
  WorkflowExecutionDetail,
} from '../src/lib/api'
import { seedEditor, settleCanvas, type EditorFixture } from './support/workflow-editor'

const viewports = [
  { width: 1280, height: 800 },
  { width: 1440, height: 900 },
]
for (const viewport of viewports) {
  test(`核心场景：完整编辑器、条件循环和失败证据 ${viewport.width}×${viewport.height}`, async ({
    page,
  }, info) => {
    test.setTimeout(90_000)
    await page.setViewportSize(viewport)
    const ordinary = await seedEditor(page)
    await page.locator('.react-flow__node[data-id=api]').click()
    await expect(page.getByRole('button', { name: '应用节点配置', exact: true })).toBeVisible()
    await capture(page, info, 'editor')

    const control = await seedEditor(page, conditionLoop)
    await page.locator('.react-flow__node[data-id=loop]').click()
    await expect(page.getByRole('heading', { name: 'body 区域', exact: true })).toBeVisible()
    await capture(page, info, 'condition-loop')
    await page.getByRole('button', { name: '打开区域画布', exact: true }).click()
    const body = page.getByRole('dialog', { name: 'body 区域画布', exact: true })
    await expect(body).toContainText('入口 · 循环内 HTTP 请求')
    await expect(body).toContainText('本轮出口 · 出口')
    await capture(page, info, 'condition-loop-body')
    await body.getByRole('button', { name: 'Close', exact: true }).click()
    const controlRun = await executeFrozen(page, control)
    expect(controlRun.execution.status).toBe('passed')
    const records = await page.request.get(
      `/api/v1${control.root}/workflow-executions/${controlRun.execution.id}/control-records?node_id=loop&kind=iteration`,
      { headers: control.headers },
    )
    expect(records.ok(), await records.text()).toBeTruthy()
    expect((await records.json()).items).toHaveLength(2)
    await page.goto(
      `${control.root}/workflows?focus=${control.workflow.id}&execution=${controlRun.execution.id}&node=loop&control_kind=iteration&control_ordinal=1`,
    )
    await expect(page.getByText('历史快照 · 不可修改')).toBeVisible()
    await expect(page.locator('.workflow-run-inspector')).toBeVisible()
    const instance = page
      .getByText('loop-request · passed', { exact: true })
      .locator('..')
      .getByRole('button', { name: '查看实例详情', exact: true })
    await expect(instance).toBeVisible()
    await capture(page, info, 'control-evidence')
    await instance.click()
    await expect(page.getByRole('region', { name: '实例执行证据', exact: true })).toContainText(
      '"status_code": 200',
    )
    await expect(page).toHaveURL(/instance=__nested_request__/)
    await page.goto(`${page.url()}&instance_attempt=1`)
    await expect(page.getByRole('region', { name: '实例执行证据', exact: true })).toContainText(
      '检查点尝试：1',
    )
    await page.getByRole('button', { name: '折叠运行面板', exact: true }).click()
    await page.getByRole('region', { name: '实例执行证据', exact: true }).scrollIntoViewIfNeeded()
    await capture(page, info, 'nested-evidence')

    const failed = await seedEditor(page, failureDefinition)
    const failure = await executeFrozen(page, failed)
    expect(failure.execution.status).toBe('failed')
    expect(failure.nodes.find((node) => node.node_id === 'api')?.status).toBe('passed')
    const assertion = failure.nodes.find((node) => node.node_id === 'assert')
    expect(assertion?.status).toBe('failed')
    expect(assertion?.output).toMatchObject({ actual: 200, expected: 201 })
    await page.goto(
      `${failed.root}/workflows?focus=${failed.workflow.id}&execution=${failure.execution.id}&node=assert&attempt=1`,
    )
    const inspector = page.locator('.workflow-run-inspector')
    await expect(inspector).toContainText('201')
    await expect(inspector).toContainText('200')
    await expect(inspector).toContainText('差值')
    await expect(inspector).toContainText('单位：未提供')
    await page.getByRole('button', { name: '折叠运行面板', exact: true }).click()
    await inspector.getByLabel('断言证据').scrollIntoViewIfNeeded()
    await expect(inspector.getByText('201', { exact: true })).toBeInViewport()
    await expect(inspector.getByText('200', { exact: true })).toBeInViewport()
    await expect(page.getByRole('button', { name: '保存草稿', exact: true })).toHaveCount(0)
    await capture(page, info, 'failed-assertion')
    const report = page.getByRole('link', { name: '查看完整报告', exact: true })
    await expect(report).toHaveAttribute(
      'href',
      new RegExp(`execution=${failure.execution.id}.*node=assert.*attempt=1`),
    )
    expect(ordinary.projectId).not.toBe(failed.projectId)
  })
}

function edge(source: string, target: string) {
  return { id: `${source}-${target}`, source, target, condition: null, mappings: [] }
}
function controlNode(
  id: string,
  capability: string,
  configuration: WorkflowNode['configuration'],
  x: number,
): WorkflowNode {
  return {
    id,
    type: 'capability',
    name: id === 'loop' ? '最多三轮，达到计数退出' : '只执行命中的分支',
    position: { x, y: 80 },
    config: {},
    capability_id: capability,
    capability_version: '1.0.0',
    configuration,
    bindings: [],
  }
}
function region(
  id: string,
  owner: string,
  role: string,
  node: WorkflowNode,
  exit?: WorkflowNode,
): WorkflowRegion {
  return {
    id,
    owner_node_id: owner,
    role,
    nodes: exit ? [node, exit] : [node],
    edges: exit ? [edge(node.id, exit.id)] : [],
    entry_node_id: node.id,
    exit_node_ids: [exit?.id ?? node.id],
    inputs: {},
    outputs: {},
  }
}
function conditionLoop(base: WorkflowDefinition): WorkflowDefinition {
  const branch = controlNode(
    'branch',
    'flow.control.if',
    {
      condition: {
        kind: 'compare',
        left: { kind: 'literal', value: true },
        operator: 'equals',
        right: { kind: 'literal', value: true },
      },
      true_body: { kind: 'inline', region_id: 'true-body' },
      false_body: { kind: 'inline', region_id: 'false-body' },
    },
    260,
  )
  const loop = controlNode(
    'loop',
    'flow.control.until',
    {
      condition: {
        kind: 'compare',
        left: { kind: 'variable', scope: 'state', path: ['counter'] },
        operator: 'gte',
        right: { kind: 'literal', value: 2 },
      },
      state: { counter: { kind: 'literal', value: 0 } },
      update: { counter: { kind: 'add', value: { kind: 'literal', value: 1 } } },
      body: { kind: 'inline', region_id: 'loop-body' },
      policy: { max_iterations: 3, timeout_seconds: 30 },
    },
    520,
  )
  const delay: WorkflowNode = {
    id: 'skip',
    type: 'delay',
    name: '备用分支',
    position: { x: 0, y: 0 },
    config: { seconds: 0 },
  }
  return {
    ...base,
    schema_version: '4.0',
    run_policy: {
      request_budget: 20,
      max_runtime_seconds: 60,
      cleanup_request_budget: null,
      force_cancel_skips_cleanup: true,
    },
    nodes: [base.nodes[0], branch, loop, { ...base.nodes[2], position: { x: 780, y: 80 } }],
    edges: [edge('start', 'branch'), edge('branch', 'loop'), edge('loop', 'end')],
    regions: [
      region('true-body', 'branch', 'true', {
        ...base.nodes[1],
        id: 'branch-request',
        name: '命中分支的请求',
        position: { x: 0, y: 0 },
      }),
      region('false-body', 'branch', 'false', delay),
      region(
        'loop-body',
        'loop',
        'body',
        {
          ...base.nodes[1],
          id: 'loop-request',
          name: '循环内 HTTP 请求',
          position: { x: 0, y: 0 },
        },
        { ...delay, id: 'loop-boundary', name: '本轮出口', position: { x: 260, y: 0 } },
      ),
    ],
  }
}
function failureDefinition(base: WorkflowDefinition): WorkflowDefinition {
  return {
    ...base,
    nodes: [
      base.nodes[0],
      base.nodes[1],
      {
        id: 'assert',
        type: 'assert',
        name: 'HTTP 成功后独立断言失败',
        position: { x: 520, y: 80 },
        config: {
          source_node_id: 'api',
          expression: 'status_code',
          operator: 'equals',
          expected: 201,
        },
      },
      { ...base.nodes[2], position: { x: 780, y: 80 } },
    ],
    edges: [edge('start', 'api'), edge('api', 'assert'), edge('assert', 'end')],
  }
}
async function executeFrozen(page: Page, fixture: EditorFixture): Promise<WorkflowExecutionDetail> {
  const published = await page.request.post(
    `/api/v1${fixture.root}/workflows/${fixture.workflow.id}/versions`,
    { headers: fixture.headers },
  )
  expect(published.ok(), await published.text()).toBeTruthy()
  const version = (await published.json()).version
  const environments = await page.request.get(`/api/v1${fixture.root}/environments`, {
    headers: fixture.headers,
  })
  const environment = (await environments.json())[0]
  const started = await page.request.post(
    `/api/v1${fixture.root}/workflows/${fixture.workflow.id}/executions`,
    { headers: fixture.headers, data: { environment_id: environment.id, version } },
  )
  expect(started.ok(), await started.text()).toBeTruthy()
  const execution = await started.json()
  let result!: WorkflowExecutionDetail
  await expect
    .poll(
      async () => {
        const response = await page.request.get(
          `/api/v1${fixture.root}/workflow-executions/${execution.id}`,
          { headers: fixture.headers },
        )
        expect(response.ok()).toBeTruthy()
        result = await response.json()
        return ['queued', 'running'].includes(result.execution.status)
      },
      { timeout: 30_000 },
    )
    .toBe(false)
  return result
}
async function capture(page: Page, info: TestInfo, scenario: string): Promise<void> {
  await page.evaluate(() => document.fonts.ready)
  await settleCanvas(page)
  await page.mouse.move(0, 0)
  const size = page.viewportSize()!
  const name = `${size.width}x${size.height}-${scenario}`
  const screenshot = info.outputPath(`${name}.png`)
  await page.screenshot({ path: screenshot, animations: 'disabled' })
  await info.attach(name, { path: screenshot, contentType: 'image/png' })
  const git = (args: string[]) => execFileSync('git', ['-C', '..', ...args])
  const frontendSource = createHash('sha256')
  const files = [
    ...new Set(
      git(['ls-files', '-co', '--exclude-standard', '-z', '--', 'frontend']).toString().split('\0'),
    ),
  ]
    .filter((file) => /\.(?:tsx?|css|json|ya?ml|conf)$/.test(file))
    .sort()
  for (const file of files)
    frontendSource.update(file + '\0').update(readFileSync(resolve('..', file)))
  const pixelGate =
    process.platform === 'darwin' &&
    ['editor', 'condition-loop-body', 'failed-assertion'].includes(scenario)
  const metadata = info.outputPath(`${name}.json`)
  writeFileSync(
    metadata,
    JSON.stringify(
      {
        sourceSha: git(['rev-parse', 'HEAD']).toString().trim(),
        frontendDiffSha256: createHash('sha256')
          .update(git(['diff', 'HEAD', '--', 'frontend']))
          .digest('hex'),
        frontendSourceSha256: frontendSource.digest('hex'),
        scenario,
        viewport: size,
        platform: process.platform,
        browserVersion: page.context().browser()?.version(),
        runtime: '实际 API/Worker，合成测试资产',
        geometry: await page.evaluate(() => {
          const selectors = [
            '.workflow-canvas-stage',
            '.workflow-canvas-toolbar',
            '.workflow-inspector',
            '.workflow-runtime-dock',
            '.workflow-region-canvas',
          ]
          return {
            surfaces: Object.fromEntries(
              selectors.map((selector) => {
                const element = document.querySelector(selector)
                const box = element?.getBoundingClientRect()
                return [
                  selector,
                  box ? { x: box.x, y: box.y, width: box.width, height: box.height } : null,
                ]
              }),
            ),
            page: {
              width: document.documentElement.scrollWidth,
              height: document.documentElement.scrollHeight,
            },
            theme: document.documentElement.dataset.flowtestTheme,
          }
        }),
        pixelGate: pixelGate ? 'ASSERTED (macOS)' : 'NOT RUN (capture and behavior only)',
      },
      null,
      2,
    ) + '\n',
  )
  await info.attach(`${name}-source`, { path: metadata, contentType: 'application/json' })
  if (pixelGate) {
    await expect(page).toHaveScreenshot(`${name}.png`, {
      animations: 'disabled',
      maxDiffPixelRatio: 0.003,
      mask: [
        page.locator('.global-project-select'),
        page.locator('.page-breadcrumb'),
        page.locator('.workflow-volatile-value'),
        page
          .locator('.workspace-navigation-tabs .ant-tabs-tab-btn')
          .filter({ hasText: '执行报告' }),
        page.locator('.workflow-runtime-panel-heading .ant-typography-secondary'),
        page.locator('.flow-node-status small'),
        page.locator('.workflow-runtime-dock'),
      ],
    })
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
    size.width,
  )
}
