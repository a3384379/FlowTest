import {
  ApiOutlined,
  ApartmentOutlined,
  BarChartOutlined,
  DashboardOutlined,
  RobotOutlined,
  ScheduleOutlined,
  ToolOutlined,
} from '@ant-design/icons'
import type { MenuProps } from 'antd'

import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import {
  globalPath,
  isGlobalAdministrationSection,
  type ProjectSection,
} from '../projects/project-routing'

export const sectionLabels: Record<ProjectSection, string> = {
  dashboard: '质量总览',
  settings: '项目管理',
  services: '服务目录',
  'request-targets': '请求目标',
  apis: '接口管理',
  protocols: '多协议工作台',
  assets: '测试资产',
  workflows: '流程编排',
  data: '数据与 Mock',
  tasks: '任务执行',
  performance: '性能实验室',
  environments: '环境实验室',
  contracts: '契约中心',
  'test-engineering': '测试工程',
  contexts: '上下文检查器',
  impact: '影响分析',
  'change-regression': '变更回归',
  quality: '质量中心',
  release: '发布门禁',
  ai: 'AI 助手',
  'ai-changes': 'AI 变更集',
  'mcp-changes': 'MCP 变更集',
  reports: '测试报告',
  platform: '平台管理',
  fabric: '分布式执行面',
  organization: '组织治理',
}

export const navigationGroups = [
  {
    key: 'nav:project-api',
    label: '项目与接口',
    sections: ['apis', 'services', 'request-targets', 'protocols', 'settings'],
    icon: <ApiOutlined />,
  },
  {
    key: 'nav:test-design',
    label: '测试设计',
    sections: ['workflows', 'assets', 'data', 'contracts', 'test-engineering'],
    icon: <ApartmentOutlined />,
  },
  {
    key: 'nav:execution',
    label: '执行与环境',
    sections: ['tasks', 'environments', 'performance'],
    icon: <ScheduleOutlined />,
  },
  {
    key: 'nav:quality',
    label: '质量分析',
    sections: ['reports', 'impact', 'change-regression', 'quality', 'release'],
    icon: <BarChartOutlined />,
  },
  {
    key: 'nav:ai',
    label: 'AI 与集成',
    sections: ['ai', 'contexts', 'ai-changes', 'mcp-changes'],
    icon: <RobotOutlined />,
  },
  {
    key: 'nav:system',
    label: '系统管理',
    sections: ['organization', 'fabric', 'platform'],
    icon: <ToolOutlined />,
  },
] as const satisfies readonly {
  key: string
  label: string
  sections: readonly ProjectSection[]
  icon: ReactNode
}[]

export type NavigationGroupKey = (typeof navigationGroups)[number]['key']

export function groupForSection(section: ProjectSection) {
  return navigationGroups.find((group) =>
    (group.sections as readonly ProjectSection[]).includes(section),
  )
}

export function visibleSections(isSystemAdmin: boolean): ProjectSection[] {
  return (Object.keys(sectionLabels) as ProjectSection[]).filter(
    (section) => isSystemAdmin || (section !== 'fabric' && section !== 'platform'),
  )
}

export function navigationPath(
  section: ProjectSection,
  pathFor: (section: ProjectSection) => string,
): string {
  return isGlobalAdministrationSection(section) ? globalPath(section) : pathFor(section)
}

export function shellNavigationItems(
  isSystemAdmin: boolean,
  activeSection: ProjectSection,
  pathFor: (section: ProjectSection) => string,
): MenuProps['items'] {
  const allowed = visibleSections(isSystemAdmin)
  const leaf = (section: ProjectSection) => ({
    key: section,
    'aria-label': sectionLabels[section],
    label: (
      <Link
        to={navigationPath(section, pathFor)}
        aria-current={activeSection === section ? 'page' : undefined}
      >
        {sectionLabels[section]}
      </Link>
    ),
  })
  const groups = navigationGroups.flatMap((group) => {
    const sections = group.sections.filter((section) => allowed.includes(section))
    if (!sections.length) return []
    return [
      {
        key: group.key,
        icon: (
          <span aria-hidden="true" title={group.label}>
            {group.icon}
          </span>
        ),
        label: group.label,
        className:
          group.key === groupForSection(activeSection)?.key ? 'navigation-active-group' : undefined,
        children: sections.map(leaf),
      },
    ]
  })
  return [
    { ...leaf('dashboard'), icon: <DashboardOutlined aria-hidden="true" /> },
    ...groups.slice(0, 5),
    { type: 'divider', key: 'nav:global-divider', className: 'navigation-global-divider' },
    ...groups.slice(5),
  ]
}
