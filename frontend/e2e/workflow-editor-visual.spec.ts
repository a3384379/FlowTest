import { expect, test, type Locator, type Page, type TestInfo } from '@playwright/test'
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { resolve } from 'node:path'

import { clickEdge, closeInspector, publishAndRun, seedEditor } from './support/workflow-editor'

const matrixRoot = resolve(
  process.cwd(),
  '../output/playwright/workflow-final-matrix',
  process.platform,
)
const viewports = [
  { width: 1280, height: 800 },
  { width: 1440, height: 900 },
  { width: 1920, height: 1080 },
]

for (const viewport of viewports) {
  test(`Visual matrix：${viewport.width}×${viewport.height}`, async ({ page }, testInfo) => {
    test.setTimeout(90_000)
    await page.setViewportSize(viewport)
    await seedEditor(page)
    await page.evaluate(() => document.fonts.ready)
    await settleViewport(page)
    await fitCanvas(page)
    const directory = resolve(matrixRoot, `${viewport.width}x${viewport.height}`)
    mkdirSync(directory, { recursive: true })

    const captureState = (name: string) => capture(page, directory, name, testInfo)
    await captureState('01-default-edit')

    await page.getByRole('button', { name: 'plus 添加节点', exact: true }).click()
    await expect(page.getByRole('dialog', { name: '添加节点', exact: true })).toBeVisible()
    await captureState('02-add-node')
    await page.getByRole('button', { name: '返回画布', exact: true }).click()

    await page.locator('.react-flow__node[data-id=api]').click()
    await expect(page.getByTestId('workflow-inspector')).toBeVisible()
    await captureState('03-node-selected')

    await clickEdge(page)
    await captureState('04-edge-selected')

    await page.locator('.react-flow__node[data-id=api]').click()
    await resizeInspector(page, 100)
    await captureState('05-inspector-resized')

    await page.getByRole('button', { name: '最大化配置', exact: true }).click()
    const fullscreen = page.getByRole('dialog', { name: '节点与连线配置', exact: true })
    await expect(fullscreen).toBeVisible()
    await expect(fullscreen.getByRole('tab', { name: 'Params', exact: true })).toBeVisible()
    await captureState('06-fullscreen-config')
    await page.getByRole('button', { name: '还原配置', exact: true }).click()
    await closeInspector(page)

    await page.getByRole('button', { name: '专注模式', exact: true }).click()
    await expect(page.getByTestId('workflow-focus-toolbar')).toBeVisible()
    const referenceToggle = page
      .getByTestId('workflow-focus-toolbar')
      .locator('.ant-checkbox-wrapper')
    expect((await requiredBox(referenceToggle)).height).toBeLessThanOrEqual(28)
    await settleViewport(page)
    await fitCanvas(page)
    await captureState('07-focus-mode')
    await page.getByRole('button', { name: '退出专注模式', exact: true }).click()

    await publishAndRun(page)
    const runtimeDock = page.getByTestId('workflow-runtime-dock')
    await expect(runtimeDock).toBeVisible()
    const runtimeHeight = (await requiredBox(runtimeDock)).height
    expect(runtimeHeight).toBeGreaterThanOrEqual(200)
    expect(runtimeHeight).toBeLessThanOrEqual(280)
    await expect(page.locator('.ant-message-notice')).toHaveCount(0, { timeout: 6_000 })
    await expect(page.locator('.flow-node.is-passed')).toHaveCount(3)
    await settleViewport(page)
    await fitCanvas(page)
    await captureState('08-run-mode')

    await page.getByTestId('workflow-runtime-tab-history').click()
    const historicalRun = page.locator('[data-testid^="workflow-history-"]').first()
    const historicalRunId = await historicalRun.getAttribute('data-testid')
    await historicalRun.click()
    await expect(page.getByText('历史快照 · 不可修改')).toBeVisible()
    await expect(page.locator('.workflow-workbench-card .ant-card-loading-content')).toHaveCount(0)
    await expect(page.locator('.workflow-workbench-card .react-flow__node').first()).toBeVisible()
    await expect(page.getByTestId(historicalRunId!)).toBeVisible()
    await settleViewport(page)
    await fitCanvas(page)
    await captureState('09-history-mode')
  })
}

async function capture(
  page: Page,
  directory: string,
  name: string,
  testInfo: TestInfo,
): Promise<void> {
  await expectNoOverflow(page)
  await page.mouse.move(0, 0)
  await page.evaluate(() => document.fonts.ready)
  await settleViewport(page)
  const screenshot = resolve(directory, `${name}.png`)
  await page.screenshot({
    animations: 'disabled',
    path: screenshot,
  })
  const measurements = await measureWorkbench(page)
  const metadata = {
    ...sourceIdentity(),
    scenario: name,
    viewport: page.viewportSize(),
    platform: process.platform,
    browserVersion: page.context().browser()?.version(),
    measurements,
    pixelGate: process.platform === 'linux' ? 'ASSERTED' : 'NOT RUN (Linux baseline)',
    fixtureOnly: true,
  }
  const geometry = resolve(directory, `${name}.json`)
  writeFileSync(geometry, JSON.stringify(metadata, null, 2) + '\n')
  await testInfo.attach(name, { path: screenshot, contentType: 'image/png' })
  await testInfo.attach(`${name}-geometry`, { path: geometry, contentType: 'application/json' })
  if (process.platform !== 'linux') {
    testInfo.annotations.push({
      type: 'NOT RUN',
      description: `${name}: pixel regression uses reviewed Linux Chromium baselines`,
    })
    return
  }
  await expect(page).toHaveScreenshot(
    `${page.viewportSize()!.width}x${page.viewportSize()!.height}-${name}.png`,
    {
      animations: 'disabled',
      maxDiffPixelRatio: 0.003,
      mask: visualFixtureMasks(page, name),
    },
  )
}
function sourceIdentity() {
  const git = (args: string[]) => execFileSync('git', ['-C', '..', ...args])
  const files = [
    ...new Set(
      git(['ls-files', '-co', '--exclude-standard', '-z', '--', 'frontend']).toString().split('\0'),
    ),
  ]
    .filter((file) => /\.(?:tsx?|css|json|ya?ml|conf)$/.test(file))
    .sort()
  const source = createHash('sha256')
  for (const file of files) source.update(file + '\0').update(readFileSync(resolve('..', file)))
  return {
    sourceSha: git(['rev-parse', 'HEAD']).toString().trim(),
    frontendDiffSha256: createHash('sha256')
      .update(git(['diff', 'HEAD', '--', 'frontend']))
      .digest('hex'),
    frontendSourceSha256: source.digest('hex'),
  }
}

function visualFixtureMasks(page: Page, name: string): Locator[] {
  const masks = [
    page.locator('.global-project-select'),
    page.locator('.page-breadcrumb'),
    page.locator('.workflow-runtime-panel-heading .ant-typography-secondary'),
    page.locator('.workflow-meta .ant-tag').filter({ hasText: /^执行 / }),
    page.locator('.flow-node-status small'),
    page.locator('.workflow-volatile-value'),
  ]
  if (name === '09-history-mode')
    masks.push(
      page.locator(
        '.workflow-runtime-dock .ant-table-tbody td:nth-child(1), .workflow-runtime-dock .ant-table-tbody td:nth-child(6), .workflow-runtime-dock .ant-table-tbody td:nth-child(7)',
      ),
    )
  return masks
}
async function settleViewport(page: Page): Promise<void> {
  await expect
    .poll(() =>
      page.evaluate(() =>
        Array.from(document.querySelectorAll('.react-flow__node')).every((node) => {
          const body = node.querySelector('.flow-node')
          if (!body) return true
          return (
            Math.abs(node.getBoundingClientRect().height - body.getBoundingClientRect().height) < 1
          )
        }),
      ),
    )
    .toBe(true)
  await page.evaluate(async () => {
    let previous = ''
    let stableFrames = 0
    while (stableFrames < 10) {
      await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()))
      const current = JSON.stringify({
        viewport: document.querySelector('.react-flow__viewport')?.getAttribute('style'),
        nodes: Array.from(document.querySelectorAll('.react-flow__node'), (element) => {
          const { x, y, width, height } = element.getBoundingClientRect()
          return { x, y, width, height }
        }),
      })
      stableFrames = current === previous ? stableFrames + 1 : 0
      previous = current
    }
  })
}
async function fitCanvas(page: Page): Promise<void> {
  const fit = page.getByRole('button', { name: /适应画布/ })
  await fit.click()
  await settleViewport(page)
  await expect
    .poll(async () => {
      const offset = await graphCenterOffset(page)
      if (offset > 1) {
        await fit.click()
        await settleViewport(page)
      }
      return graphCenterOffset(page)
    })
    .toBeLessThanOrEqual(1)
}
async function graphCenterOffset(page: Page): Promise<number> {
  return page.evaluate(() => {
    const canvas = document.querySelector('.react-flow')!.getBoundingClientRect()
    const nodes = Array.from(document.querySelectorAll('.react-flow__node'), (element) =>
      element.getBoundingClientRect(),
    )
    const centerX =
      (Math.min(...nodes.map((node) => node.left)) + Math.max(...nodes.map((node) => node.right))) /
      2
    const centerY =
      (Math.min(...nodes.map((node) => node.top)) + Math.max(...nodes.map((node) => node.bottom))) /
      2
    return Math.max(
      Math.abs(centerX - canvas.x - canvas.width / 2),
      Math.abs(centerY - canvas.y - canvas.height / 2),
    )
  })
}
async function measureWorkbench(page: Page) {
  return page.evaluate(() => {
    const ids = [
      'workflow-workbench',
      'workflow-editor-main',
      'workflow-canvas-stage',
      'workflow-canvas-toolbar',
      'workflow-list-panel',
      'workflow-inspector',
      'workflow-runtime-dock',
      'workflow-focus-toolbar',
    ]
    const boxes = Object.fromEntries(
      ids.map((id) => {
        const element = document.querySelector(`[data-testid="${id}"]`)
        const box = element?.getBoundingClientRect()
        return [id, box ? { x: box.x, y: box.y, width: box.width, height: box.height } : null]
      }),
    )
    const palette = document.querySelector('.workflow-node-library [role="dialog"]')
    const paletteBox = palette?.getBoundingClientRect()
    return {
      boxes,
      palette: paletteBox ? { width: paletteBox.width, height: paletteBox.height } : null,
      canvasShare:
        (boxes['workflow-canvas-stage']?.width ?? 0) / (boxes['workflow-editor-main']?.width ?? 1),
      body: { width: document.body.scrollWidth, height: document.body.scrollHeight },
    }
  })
}

async function resizeInspector(page: Page, growBy: number): Promise<void> {
  const inspector = page.getByTestId('workflow-inspector')
  const before = await requiredBox(inspector)
  const divider = page.locator('.workflow-split-body .ant-splitter-bar').last()
  const box = await requiredBox(divider)
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  await page.mouse.down()
  await page.mouse.move(box.x - growBy, box.y + box.height / 2, { steps: 20 })
  await page.mouse.up()
  await expect.poll(async () => (await requiredBox(inspector)).width).toBeGreaterThan(before.width)
}

async function requiredBox(locator: Locator) {
  const box = await locator.boundingBox()
  expect(box).not.toBeNull()
  return box!
}

async function expectNoOverflow(page: Page): Promise<void> {
  const overflow = await page.evaluate(() => ({
    bodyWidth: document.body.scrollWidth,
    viewportWidth: window.innerWidth,
  }))
  expect(overflow.bodyWidth).toBeLessThanOrEqual(overflow.viewportWidth + 1)
}
