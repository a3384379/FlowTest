import { expect, test } from '@playwright/test'
import { clickEdge, closeInspector, publishAndRun, seedEditor } from './support/workflow-editor'

for (const viewport of [
  { width: 1920, height: 1080 },
  { width: 1440, height: 900 },
  { width: 1280, height: 720 },
]) {
  test(`ACC01/LAY：${viewport.width} 下工作区、专注、配置、连线、节点库和历史`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize(viewport)
    await seedEditor(page)
    await page.getByRole('button', { name: 'Fit View', exact: true }).click()
    const canvas = page.getByLabel('工作流画布', { exact: true })
    expect((await canvas.boundingBox())!.height).toBeGreaterThan(150)
    expect(await page.evaluate(() => document.body.scrollHeight)).toBeLessThanOrEqual(
      viewport.height + 1,
    )
    await page.screenshot({ animations: 'disabled', path: testInfo.outputPath('normal.png') })
    await page.getByRole('button', { name: '专注模式', exact: true }).click()
    expect((await canvas.boundingBox())!.height).toBeGreaterThan(viewport.height - 180)
    await page.screenshot({ animations: 'disabled', path: testInfo.outputPath('focus.png') })
    await page.getByRole('button', { name: '退出专注模式', exact: true }).click()
    await page.locator('.react-flow__node[data-id=api]').click()
    const name = page.getByRole('textbox', { name: '名称', exact: true })
    await name.fill('配置输入保留')
    await page.getByRole('button', { name: '最大化配置', exact: true }).click()
    await expect(name).toHaveValue('配置输入保留')
    await page.screenshot({
      animations: 'disabled',
      path: testInfo.outputPath('configuration.png'),
    })
    await page.keyboard.press('Escape')
    await expect(name).toHaveValue('配置输入保留')
    await page.getByRole('button', { name: '应用节点配置', exact: true }).click()
    await closeInspector(page)
    await clickEdge(page)
    await expect(page.getByRole('heading', { name: '连线配置', exact: true })).toBeVisible()
    await page.screenshot({ animations: 'disabled', path: testInfo.outputPath('edge.png') })
    await closeInspector(page)
    await page.getByRole('button', { name: 'plus 添加节点', exact: true }).click()
    await expect(page.getByRole('searchbox', { name: '搜索节点类型', exact: true })).toBeVisible()
    await expect(
      page.getByRole('searchbox', { name: '搜索节点类型', exact: true }),
    ).toBeInViewport()
    await page.screenshot({ animations: 'disabled', path: testInfo.outputPath('library.png') })
    await page.getByRole('button', { name: '返回画布', exact: true }).click()
    await page.getByRole('button', { name: 'save 保存草稿', exact: true }).click()
    await expect(page.getByText('草稿已保存').last()).toBeVisible()
    await publishAndRun(page)
    await page.getByRole('button', { name: 'eye 查看快照', exact: true }).click()
    await expect(page.getByText('历史快照 · 只读')).toBeVisible()
    await expect(page.locator('.react-flow__edge')).toHaveCount(2)
    await expect.poll(async () => (await canvas.boundingBox())?.height ?? 0).toBeGreaterThan(100)
    if ((await canvas.boundingBox())!.height <= 320)
      await expect(page.locator('.react-flow__minimap')).toBeHidden()
    await page.screenshot({ animations: 'disabled', path: testInfo.outputPath('history.png') })
  })
}
