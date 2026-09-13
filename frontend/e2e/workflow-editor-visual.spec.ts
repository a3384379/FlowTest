import { expect, test, type Locator, type Page } from '@playwright/test'
import { mkdirSync } from 'node:fs'
import { resolve } from 'node:path'

import { clickEdge, closeInspector, publishAndRun, seedEditor } from './support/workflow-editor'

const matrixRoot = resolve(process.cwd(), '../output/playwright/workflow-final-matrix')
const viewports = [
  { width: 1280, height: 800 },
  { width: 1440, height: 900 },
  { width: 1920, height: 1080 },
]

for (const viewport of viewports) {
  test(`Visual matrix：${viewport.width}×${viewport.height}`, async ({ page }) => {
    test.setTimeout(90_000)
    await page.setViewportSize(viewport)
    await seedEditor(page)
    const directory = resolve(matrixRoot, `${viewport.width}x${viewport.height}`)
    mkdirSync(directory, { recursive: true })

    await capture(page, directory, '01-default-edit')

    await page.getByRole('button', { name: 'plus 添加节点', exact: true }).click()
    await expect(page.getByRole('dialog', { name: '添加节点', exact: true })).toBeVisible()
    await capture(page, directory, '02-add-node')
    await page.getByRole('button', { name: '返回画布', exact: true }).click()

    await page.locator('.react-flow__node[data-id=api]').click()
    await expect(page.getByTestId('workflow-inspector')).toBeVisible()
    await capture(page, directory, '03-node-selected')

    await clickEdge(page)
    await capture(page, directory, '04-edge-selected')

    await page.locator('.react-flow__node[data-id=api]').click()
    await resizeInspector(page, 100)
    await capture(page, directory, '05-inspector-resized')

    await page.getByRole('button', { name: '最大化配置', exact: true }).click()
    const fullscreen = page.getByRole('dialog', { name: '节点与连线配置', exact: true })
    await expect(fullscreen).toBeVisible()
    await expect(fullscreen.getByRole('tab', { name: 'Params', exact: true })).toBeVisible()
    await capture(page, directory, '06-fullscreen-config')
    await page.getByRole('button', { name: '还原配置', exact: true }).click()
    await closeInspector(page)

    await page.getByRole('button', { name: '专注模式', exact: true }).click()
    await expect(page.getByTestId('workflow-focus-toolbar')).toBeVisible()
    await capture(page, directory, '07-focus-mode')
    await page.getByRole('button', { name: '退出专注模式', exact: true }).click()

    await publishAndRun(page)
    const runtimeDock = page.getByTestId('workflow-runtime-dock')
    await expect(runtimeDock).toBeVisible()
    const runtimeHeight = (await requiredBox(runtimeDock)).height
    expect(runtimeHeight).toBeGreaterThanOrEqual(200)
    expect(runtimeHeight).toBeLessThanOrEqual(280)
    await expect(page.locator('.ant-message-notice')).toHaveCount(0, { timeout: 6_000 })
    await capture(page, directory, '08-run-mode')

    await page.getByTestId('workflow-runtime-tab-history').click()
    await page.locator('[data-testid^="workflow-history-"]').first().click()
    await expect(page.getByText('历史快照 · 不可修改')).toBeVisible()
    await expect(page.locator('.workflow-workbench-card .ant-card-loading-content')).toHaveCount(0)
    await expect(page.locator('.workflow-workbench-card .react-flow__node').first()).toBeVisible()
    await capture(page, directory, '09-history-mode')
  })
}

async function capture(page: Page, directory: string, name: string): Promise<void> {
  await expectNoOverflow(page)
  await page.screenshot({
    animations: 'disabled',
    path: resolve(directory, `${name}.png`),
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
