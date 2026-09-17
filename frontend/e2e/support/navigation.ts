import { expect, type Page } from '@playwright/test'

const groups: Record<string, string[]> = {
  项目与接口: ['接口管理', '服务目录', '请求目标', '多协议工作台', '项目管理'],
  测试设计: ['流程编排', '测试资产', '数据与 Mock', '契约中心', '测试工程'],
  执行与环境: ['任务执行', '环境实验室', '性能实验室'],
  质量分析: ['测试报告', '影响分析', '变更回归', '质量中心', '发布门禁'],
  'AI 与集成': ['AI 助手', '上下文检查器', 'AI 变更集', 'MCP 变更集'],
  系统管理: ['组织治理', '分布式执行面', '平台管理'],
}

/** Navigate through the same visible parent/leaf controls as a person. */
export async function navigateMenu(page: Page, label: string): Promise<void> {
  const trigger = page.getByRole('button', { name: '打开导航', exact: true })
  if (await trigger.isVisible()) await trigger.click()
  const navigation = page.getByRole('navigation', { name: '功能导航' })
  const group = Object.entries(groups).find(([, leaves]) => leaves.includes(label))?.[0]
  if (group) {
    const parent = navigation.getByRole('menuitem', { name: group, exact: true })
    if ((await parent.getAttribute('aria-expanded')) !== 'true') await parent.click()
  }
  // Collapsed menus render the popup outside the sidebar.
  const leaf = navigation
    .getByRole('link', { name: label, exact: true })
    .or(page.locator('.ant-menu-submenu-popup').getByRole('link', { name: label, exact: true }))
    .filter({ visible: true })
  await expect(leaf).toHaveCount(1)
  await expect(leaf).toBeVisible()
  await leaf.click()
}
