import { expect, test, type Locator, type Page } from '@playwright/test'
import { seedEditor } from './support/workflow-editor'

const viewports = [
  { width: 1280, height: 800, minimumCanvasHeight: 460, listVisible: false },
  { width: 1440, height: 900, minimumCanvasHeight: 600, listVisible: true },
  { width: 1920, height: 1080, minimumCanvasHeight: 720, listVisible: true },
]

for (const viewport of viewports) {
  test(`Phase 1 geometry：${viewport.width}×${viewport.height}`, async ({ page }, testInfo) => {
    await page.setViewportSize(viewport)
    await seedEditor(page)

    const workbench = page.getByTestId('workflow-workbench')
    const editorMain = page.getByTestId('workflow-editor-main')
    const canvas = page.getByTestId('workflow-canvas-stage')
    const toolbar = page.getByTestId('workflow-canvas-toolbar')
    const list = page.getByTestId('workflow-list-panel')

    await expect(workbench).toBeVisible()
    await expect(canvas).toBeVisible()
    const header = page.getByTestId('workflow-workbench-header')
    const title = await requiredBox(header.locator('.workflow-workbench-header-left'))
    const modes = await requiredBox(header.locator('.workflow-workbench-header-center'))
    const actions = await requiredBox(header.locator('.workflow-workbench-header-right'))
    const toggle = await requiredBox(
      page.getByRole('button', { name: '切换工作流列表', exact: true }),
    )
    expect(toggle.x + toggle.width + 6).toBeLessThanOrEqual(title.x)
    expect(title.x + title.width).toBeLessThanOrEqual(modes.x)
    expect(modes.x + modes.width).toBeLessThanOrEqual(actions.x)
    expect((await requiredBox(canvas)).height).toBeGreaterThanOrEqual(viewport.minimumCanvasHeight)
    expect((await requiredBox(toolbar)).height).toBeLessThanOrEqual(56)
    await expectPageWithoutOverflow(page, viewport)

    if (viewport.listVisible) {
      await expect(list).toBeVisible()
      const listWidth = (await requiredBox(list)).width
      expect(listWidth).toBeGreaterThanOrEqual(240)
      expect(listWidth).toBeLessThanOrEqual(280)
    } else {
      await expect(list).toBeHidden()
    }

    await page.screenshot({ animations: 'disabled', path: testInfo.outputPath('default-edit.png') })

    await page.locator('.react-flow__node[data-id=api]').click()
    const inspector = page.getByTestId('workflow-inspector')
    await expect(inspector).toBeVisible()
    await expect
      .poll(async () => {
        const stage = await requiredBox(canvas)
        const node = await requiredBox(page.locator('.react-flow__node[data-id=api]'))
        const actions = await requiredBox(page.getByLabel('节点快捷操作', { exact: true }))
        return (
          Math.max(node.x + node.width, actions.x + actions.width) <= stage.x + stage.width - 12 &&
          Math.min(node.x, actions.x) >= stage.x + 12
        )
      })
      .toBeTruthy()
    const canvasShare = (await requiredBox(canvas)).width / (await requiredBox(editorMain)).width
    expect(canvasShare).toBeGreaterThanOrEqual(0.52)
    expect((await requiredBox(inspector)).width).toBeGreaterThanOrEqual(320)

    await page.getByRole('button', { name: '专注模式', exact: true }).click()
    const focusToolbar = page.getByTestId('workflow-focus-toolbar')
    await expect(focusToolbar).toBeVisible()
    await expect(list).toBeHidden()
    await expect(inspector).toBeHidden()
    expect((await requiredBox(canvas)).width / viewport.width).toBeGreaterThanOrEqual(0.88)
    for (const name of [
      '保存草稿',
      '运行已发布版本',
      '调试至断点',
      'plus 添加节点',
      'undo 撤销',
      'redo 重做',
      'apartment 自动布局',
      '退出专注模式',
    ]) {
      await expect(focusToolbar.getByRole('button', { name, exact: true })).toBeVisible()
    }
    await expect(
      focusToolbar.getByRole('button', { name: '运行已发布版本', exact: true }),
    ).toHaveCSS('color', 'rgb(71, 84, 103)')
    await page.screenshot({ animations: 'disabled', path: testInfo.outputPath('focus.png') })

    await focusToolbar.getByRole('button', { name: 'plus 添加节点', exact: true }).click()
    const nodeLibrary = page.getByRole('dialog', { name: '添加节点', exact: true })
    await expect(nodeLibrary).toBeVisible()
    await expect(page.getByRole('searchbox', { name: '搜索节点类型', exact: true })).toBeVisible()
    const libraryBox = await requiredBox(nodeLibrary)
    expect(libraryBox.y).toBeLessThanOrEqual(1)
    expect(libraryBox.height).toBeGreaterThanOrEqual(viewport.height - 1)
    await page.screenshot({
      animations: 'disabled',
      path: testInfo.outputPath('focus-node-library.png'),
    })
  })
}

async function requiredBox(locator: Locator) {
  const box = await locator.boundingBox()
  expect(box).not.toBeNull()
  return box!
}

async function expectPageWithoutOverflow(page: Page, viewport: { width: number; height: number }) {
  const size = await page.evaluate(() => ({
    height: document.body.scrollHeight,
    width: document.body.scrollWidth,
  }))
  expect(size.height).toBeLessThanOrEqual(viewport.height + 1)
  expect(size.width).toBeLessThanOrEqual(viewport.width + 1)
}
