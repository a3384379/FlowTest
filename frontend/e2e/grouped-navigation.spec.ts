import { expect, test } from '@playwright/test'

import { navigateMenu } from './support/navigation'
import { seedEditor } from './support/workflow-editor'

for (const viewport of [
  { width: 1366, height: 768 },
  { width: 1440, height: 900 },
  { width: 1920, height: 1080 },
]) {
  test(`N03/N05/N07/N14/N15/N16：${viewport.width}×${viewport.height} navigation preserves editor`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize(viewport)
    const fixture = await seedEditor(page)
    const deepLink = `${fixture.root}/workflows?focus=${fixture.workflow.id}#navigation`
    await page.goto(deepLink)
    await expect(page.locator('.react-flow__node')).toHaveCount(3)
    await page.reload()
    await expect(page.locator('.react-flow__node')).toHaveCount(3)
    await expect(
      page
        .getByRole('navigation', { name: '常用任务' })
        .getByRole('link', { name: '流程编排', exact: true }),
    ).toHaveAttribute('aria-current', 'page')
    await expect(page.locator('.page-breadcrumb')).toContainText('测试设计')
    await page.locator('.react-flow__node[data-id=api]').click()
    const name = page.getByRole('textbox', { name: '名称', exact: true })
    await name.fill('导航测试未应用草稿')
    const editor = await page.getByTestId('workflow-workbench').elementHandle()
    const beforeURL = page.url()
    const tabs = await page.locator('.workspace-navigation-tabs').textContent()
    const navigation = await openDirectory(page)
    const parent = navigation.getByRole('menuitem', { name: '测试设计', exact: true })
    await expect(parent).toHaveAttribute('aria-expanded', 'true')
    await expect(navigation.getByRole('link', { name: '流程编排', exact: true })).toHaveAttribute(
      'aria-current',
      'page',
    )
    await parent.click()
    await expect(parent).toHaveAttribute('aria-expanded', 'false')
    const projectGroup = navigation.getByRole('menuitem', { name: '项目与接口', exact: true })
    await projectGroup.click()
    await expect(name).toHaveValue('导航测试未应用草稿')
    expect(page.url()).toBe(beforeURL)
    expect(await page.locator('.workspace-navigation-tabs').textContent()).toBe(tabs)
    await page.keyboard.press('Escape')
    await openDirectory(page)
    await expect(projectGroup).toHaveAttribute('aria-expanded', 'true')
    await expect(name).toHaveValue('导航测试未应用草稿')
    await page.keyboard.press('Escape')
    expect(await editor!.evaluate((element) => element.isConnected)).toBe(true)
    await expect(page.getByTestId('workflow-canvas-stage')).toBeVisible()
    await expect(page.locator('.sidebar')).toHaveCSS('width', '68px')
    const sidebar = await page.locator('.sidebar').boundingBox()
    const header = await page.locator('.topbar').boundingBox()
    const logout = await page.getByRole('button', { name: /退出$/ }).boundingBox()
    expect(sidebar!.height).toBe(viewport.height)
    expect(logout!.x + logout!.width).toBeLessThanOrEqual(viewport.width)
    expect(header!.x).toBe(68)
    await page.screenshot({
      path: testInfo.outputPath(`navigation-${viewport.width}.png`),
      animations: 'disabled',
    })
  })
}

for (const viewport of [
  { width: 1366, height: 768 },
  { width: 1920, height: 1080 },
]) {
  test(`workflow → services keeps sidebar fixed on every animation frame (${viewport.width})`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport)
    await seedEditor(page)
    await expect(page.getByTestId('workflow-workbench')).toBeVisible()
    const navigation = await openDirectory(page)
    await navigation.getByRole('menuitem', { name: '项目与接口', exact: true }).click()
    const service = navigation.getByRole('link', { name: '服务目录', exact: true })
    await expect(service).toBeVisible()
    const footerBottom = await page
      .locator('.shell-rail-footer')
      .evaluate((element) => element.getBoundingClientRect().bottom)
    const [samples] = await Promise.all([
      page.evaluate(
        () =>
          new Promise<{ height: number; footerBottom: number; services: boolean }[]>((resolve) => {
            const frames: { height: number; footerBottom: number; services: boolean }[] = []
            const started = performance.now()
            function sample() {
              const sidebar = document.querySelector('.sidebar')!
              const footer = document.querySelector('.shell-rail-footer')!
              frames.push({
                services: location.pathname.endsWith('/services'),
                height: sidebar.getBoundingClientRect().height,
                footerBottom: footer.getBoundingClientRect().bottom,
              })
              if (performance.now() - started < 900) requestAnimationFrame(sample)
              else resolve(frames)
            }
            requestAnimationFrame(sample)
          }),
      ),
      service.click(),
    ])
    await expect(page.getByRole('heading', { name: '服务目录', exact: true })).toBeVisible()
    expect(samples.length).toBeGreaterThan(5)
    expect(samples.some((sample) => sample.services)).toBe(true)
    for (const sample of samples) {
      expect(sample.height).toBeCloseTo(viewport.height, 0)
      expect(sample.footerBottom).toBeCloseTo(footerBottom, 0)
    }
    await page.getByRole('tab', { name: '流程编排', exact: true }).click()
    await expect(page.getByTestId('workflow-workbench')).toBeVisible()
  })
}

test('N06/N08：module directory supports keyboard selection, Escape, tabs and browser history', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await seedEditor(page)
  await navigateMenu(page, '服务目录')
  await expect(page.getByRole('heading', { name: '服务目录', exact: true })).toBeVisible()
  await page.goBack()
  await expect(page.getByTestId('workflow-workbench')).toBeVisible()
  const trigger = page.getByRole('button', { name: '全部模块', exact: true })
  await trigger.focus()
  await page.keyboard.press('Enter')
  const navigation = page.getByRole('navigation', { name: '功能导航' })
  const parent = navigation.getByRole('menuitem', { name: '测试设计', exact: true })
  await expect(parent).toHaveAttribute('aria-expanded', 'true')
  await page.keyboard.press('Escape')
  await expect(trigger).toBeFocused()
  await trigger.press('Enter')
  const search = page.getByLabel('搜索模块', { exact: true })
  await search.fill('服务目录')
  const service = navigation.getByRole('link', { name: '服务目录', exact: true })
  await service.focus()
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/services$/)
  await expect(trigger).toBeFocused()
  const overview = page
    .getByRole('navigation', { name: '常用任务' })
    .getByRole('link', { name: '质量总览', exact: true })
  await overview.focus()
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/dashboard$/)
  await page.getByRole('tab', { name: /服务目录/ }).click()
  await expect(page).toHaveURL(/services$/)
  await openDirectory(page)
  await search.clear()
  await expect(
    navigation.getByRole('menuitem', { name: '项目与接口', exact: true }),
  ).toHaveAttribute('aria-expanded', 'true')
  await page.keyboard.press('Escape')
  await page.getByRole('tab', { name: /流程编排/ }).click()
  await openDirectory(page)
  await expect(parent).toHaveAttribute('aria-expanded', 'true')
})

test('N10：all global administration pages select a project dashboard', async ({ page }) => {
  const fixture = await seedEditor(page)
  for (const route of ['/organization', '/platform', '/execution-fabric']) {
    await page.goto(route)
    await expect(page.locator('.page-breadcrumb')).toContainText('系统管理')
    await expect(page.locator('.page-breadcrumb')).not.toContainText('流程编辑验收')
    const selector = page.locator('.global-project-select')
    await selector.click()
    const projectName = (await page.request
      .get(`/api/v1/projects/${fixture.projectId}`, { headers: fixture.headers })
      .then((response) => response.json())) as { name: string }
    await page.locator('.ant-select-dropdown').getByText(projectName.name, { exact: true }).click()
    await expect(page).toHaveURL(new RegExp(`/projects/${fixture.projectId}/dashboard$`))
  }
})

test('N08/N16：responsive defaults and mobile drawer closure restore focus', async ({
  page,
}, testInfo) => {
  await page.setViewportSize({ width: 1100, height: 800 })
  const fixture = await seedEditor(page)
  await expect(page.getByRole('button', { name: '全部模块', exact: true })).toBeVisible()
  await page.setViewportSize({ width: 1440, height: 900 })
  await expect(page.locator('.sidebar')).toHaveCSS('width', '68px')
  await page.setViewportSize({ width: 390, height: 844 })
  const trigger = page.getByRole('button', { name: '打开导航', exact: true })
  await trigger.click()
  await page.keyboard.press('Escape')
  await expect(trigger).toBeFocused()
  await trigger.click()
  await page.locator('.ant-drawer-mask').click({ position: { x: 350, y: 300 } })
  await expect(trigger).toBeFocused()
  await navigateMenu(page, '服务目录')
  await expect(page).toHaveURL(new RegExp(`${fixture.root}/services$`))
  await expect(trigger).toBeFocused()
  await trigger.click()
  await page.screenshot({
    path: testInfo.outputPath('navigation-mobile.png'),
    animations: 'disabled',
  })
  await page.keyboard.press('Escape')
  await page.setViewportSize({ width: 320, height: 740 })
  const logout = page.getByRole('button', { name: /退出$/ })
  const accountBox = await logout.boundingBox()
  expect(accountBox!.x + accountBox!.width).toBeLessThanOrEqual(320)
  await expect(page.getByLabel('全局搜索')).toBeInViewport()
  await expect(page.locator('.global-project-select')).toBeInViewport()
  await page.setViewportSize({ width: 1920, height: 1080 })
  await expect(page.getByRole('button', { name: '全部模块', exact: true })).toBeVisible()
})

test('N15：menu scroll keeps brand and footer fixed without scrolling the workspace', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 600 })
  await seedEditor(page)
  const navigation = await openDirectory(page)
  await expect(
    navigation.locator('.ant-menu-root > .ant-menu-item, .ant-menu-root > .ant-menu-submenu'),
  ).toHaveCount(7)
  const footer = page.locator('.shell-rail-footer')
  const before = await footer.boundingBox()
  const pageScroll = await page.evaluate(() => window.scrollY)
  await navigation.getByRole('menuitem', { name: '项目与接口', exact: true }).click()
  await navigation.evaluate((element) => {
    element.scrollTop = element.scrollHeight
  })
  await expect(navigation.getByRole('menuitem', { name: '系统管理', exact: true })).toBeInViewport()
  await expect(page.locator('.shell-brand')).toBeInViewport()
  await expect(footer).toBeInViewport()
  const after = await footer.boundingBox()
  expect(after!.y).toBeCloseTo(before!.y, 0)
  expect(after!.x).toBe(before!.x)
  expect(after!.height).toBe(before!.height)
  expect(await page.evaluate(() => window.scrollY)).toBe(pageScroll)
  expect(await navigation.evaluate((element) => element.scrollTop)).toBeGreaterThan(0)
})

async function openDirectory(page: import('@playwright/test').Page) {
  const trigger = page
    .getByRole('button', { name: '全部模块', exact: true })
    .or(page.getByRole('button', { name: '打开导航', exact: true }))
  await trigger.click()
  await expect(page.getByRole('dialog', { name: '全部模块', exact: true })).toBeVisible()
  return page.getByRole('navigation', { name: '功能导航' })
}
