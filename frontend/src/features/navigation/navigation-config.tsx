import {
  ApiOutlined,
  AppstoreOutlined,
  AuditOutlined,
  ApartmentOutlined,
  BarChartOutlined,
  BranchesOutlined,
  CodeOutlined,
  CloudServerOutlined,
  DashboardOutlined,
  DatabaseOutlined,
  FolderOpenOutlined,
  FundProjectionScreenOutlined,
  FileSearchOutlined,
  ExperimentOutlined,
  ScheduleOutlined,
  SafetyCertificateOutlined,
  ToolOutlined,
  RobotOutlined,
  ShareAltOutlined,
  TeamOutlined,
} from '@ant-design/icons'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import type { ProjectSection } from '../projects/project-routing'

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

export function shellNavigationItems(
  isSystemAdmin: boolean,
  pathFor: (section: ProjectSection) => string,
) {
  const projectItems = (Object.keys(sectionLabels) as ProjectSection[])
    .filter((section) => !['organization', 'fabric', 'platform'].includes(section))
    .map((section) => navigationItem(section, navigationIcon(section), pathFor(section)))
  const globalItems = [navigationItem('organization', <TeamOutlined />, '/organization')]
  if (isSystemAdmin) {
    globalItems.push(navigationItem('fabric', <CloudServerOutlined />, '/execution-fabric'))
    globalItems.push(navigationItem('platform', <ToolOutlined />, '/platform'))
  }
  return [...projectItems, ...globalItems]
}

function navigationIcon(section: ProjectSection): ReactNode {
  const icons: Partial<Record<ProjectSection, ReactNode>> = {
    dashboard: <DashboardOutlined />,
    settings: <FolderOpenOutlined />,
    services: <AppstoreOutlined />,
    'request-targets': <ShareAltOutlined />,
    apis: <ApiOutlined />,
    protocols: <CodeOutlined />,
    assets: <FundProjectionScreenOutlined />,
    workflows: <ApartmentOutlined />,
    data: <DatabaseOutlined />,
    tasks: <ScheduleOutlined />,
    performance: <ExperimentOutlined />,
    environments: <CloudServerOutlined />,
    contracts: <ShareAltOutlined />,
    'test-engineering': <ExperimentOutlined />,
    contexts: <FileSearchOutlined />,
    impact: <FileSearchOutlined />,
    'change-regression': <BranchesOutlined />,
    quality: <SafetyCertificateOutlined />,
    release: <SafetyCertificateOutlined />,
    ai: <RobotOutlined />,
    'ai-changes': <RobotOutlined />,
    'mcp-changes': <AuditOutlined />,
    reports: <BarChartOutlined />,
  }
  return icons[section] ?? <AppstoreOutlined />
}

function navigationItem(section: ProjectSection, icon: ReactNode, path: string) {
  return { key: section, icon, label: <Link to={path}>{sectionLabels[section]}</Link> }
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
