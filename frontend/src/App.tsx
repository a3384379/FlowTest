import {
  ApiOutlined,
  AppstoreOutlined,
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
  LogoutOutlined,
  ScheduleOutlined,
  SafetyCertificateOutlined,
  ToolOutlined,
  RobotOutlined,
  ShareAltOutlined,
  TeamOutlined,
  UserOutlined,
} from '@ant-design/icons'
import {
  Avatar,
  Breadcrumb,
  Button,
  Layout,
  Menu,
  Select,
  Space,
  Spin,
  Tag,
  Typography,
} from 'antd'
import { lazy, Suspense, useEffect, type ReactNode } from 'react'
import { Link, Navigate, Route, Routes } from 'react-router-dom'

import LoginPage from './features/auth/LoginPage'
import PasswordChangePage from './features/auth/PasswordChangePage'
import { useAuthStore } from './features/auth/auth-store'
import ProjectProvider from './features/projects/ProjectProvider'
import ProjectEmptyState from './features/projects/ProjectEmptyState'
import { projectPath, type ProjectSection } from './features/projects/project-routing'
import { useProjectContext } from './features/projects/use-project-context'
import GlobalSearch from './features/search/GlobalSearch'

const DashboardPage = lazy(() => import('./pages/DashboardPage'))
const ServiceCatalogPage = lazy(() => import('./pages/ServiceCatalogPage'))
const ApiConsolePage = lazy(() => import('./pages/ApiConsolePage'))
const WorkflowsPage = lazy(() => import('./pages/WorkflowsPage'))
const TestAssetsPage = lazy(() => import('./pages/TestAssetsPage'))
const TestPlansPage = lazy(() => import('./pages/TestPlansPage'))
const PerformanceLabPage = lazy(() => import('./pages/PerformanceLabPage'))
const EnvironmentLabPage = lazy(() => import('./pages/EnvironmentLabPage'))
const ContractHubPage = lazy(() => import('./pages/ContractHubPage'))
const TestEngineeringPage = lazy(() => import('./pages/TestEngineeringPage'))
const ContextInspectorPage = lazy(() => import('./pages/ContextInspectorPage'))
const ImpactAnalysisPage = lazy(() => import('./pages/ImpactAnalysisPage'))
const ChangeRegressionPage = lazy(() => import('./pages/ChangeRegressionPage'))
const ReportsPage = lazy(() => import('./pages/ReportsPage'))
const QualityCenterPage = lazy(() => import('./pages/QualityCenterPage'))
const ReleaseGatePage = lazy(() => import('./pages/ReleaseGatePage'))
const AIAssistantPage = lazy(() => import('./pages/AIAssistantPage'))
const AIChangeSetsPage = lazy(() => import('./pages/AIChangeSetsPage'))
const ProjectsPage = lazy(() => import('./pages/ProjectsPage'))
const DataMockPage = lazy(() => import('./pages/DataMockPage'))
const PlatformCapabilitiesPage = lazy(() => import('./pages/PlatformCapabilitiesPage'))
const ExecutionFabricPage = lazy(() => import('./pages/ExecutionFabricPage'))
const ProtocolWorkbenchPage = lazy(() => import('./pages/ProtocolWorkbenchPage'))
const RequestTargetsPage = lazy(() => import('./pages/RequestTargetsPage'))
const OrganizationGovernancePage = lazy(() => import('./pages/OrganizationGovernancePage'))

const { Header, Content, Sider } = Layout

const sectionLabels: Record<ProjectSection, string> = {
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
  reports: '测试报告',
  platform: '平台管理',
  fabric: '分布式执行面',
  organization: '组织治理',
}

export default function App() {
  const initialized = useAuthStore((state) => state.initialized)
  const token = useAuthStore((state) => state.token)
  const user = useAuthStore((state) => state.user)
  const initialize = useAuthStore((state) => state.initialize)

  useEffect(() => {
    void initialize()
  }, [initialize])

  if (!initialized) return <FullPageLoading />
  if (!token || !user) return <LoginPage />
  if (user.requires_password_change) return <PasswordChangePage />
  return (
    <ProjectProvider>
      <AuthenticatedShell />
    </ProjectProvider>
  )
}

function AuthenticatedShell() {
  const user = useAuthStore((state) => state.user)
  const logout = useAuthStore((state) => state.logout)
  const { projects, projectId, currentProject, section, selectProject, pathFor } =
    useProjectContext()
  const hasNoProjects = isNoProjectView(projects.data?.items.length, projectId)
  const isGlobalAdministration = isGlobalAdministrationSection(section)
  return (
    <Layout className="app-shell">
      <Sider width={224} theme="dark" className="sidebar">
        <div className="brand">
          <ApiOutlined />
          <span>FlowTest</span>
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[section]}
          items={[
            navigationItem('dashboard', <DashboardOutlined />, pathFor('dashboard')),
            navigationItem('settings', <FolderOpenOutlined />, pathFor('settings')),
            navigationItem('services', <AppstoreOutlined />, pathFor('services')),
            navigationItem('request-targets', <ShareAltOutlined />, pathFor('request-targets')),
            navigationItem('apis', <ApiOutlined />, pathFor('apis')),
            navigationItem('protocols', <CodeOutlined />, pathFor('protocols')),
            navigationItem('assets', <FundProjectionScreenOutlined />, pathFor('assets')),
            navigationItem('workflows', <ApartmentOutlined />, pathFor('workflows')),
            navigationItem('data', <DatabaseOutlined />, pathFor('data')),
            navigationItem('tasks', <ScheduleOutlined />, pathFor('tasks')),
            navigationItem('performance', <ExperimentOutlined />, pathFor('performance')),
            navigationItem('environments', <CloudServerOutlined />, pathFor('environments')),
            navigationItem('contracts', <ShareAltOutlined />, pathFor('contracts')),
            navigationItem('test-engineering', <ExperimentOutlined />, pathFor('test-engineering')),
            navigationItem('contexts', <FileSearchOutlined />, pathFor('contexts')),
            navigationItem('impact', <FileSearchOutlined />, pathFor('impact')),
            navigationItem('change-regression', <BranchesOutlined />, pathFor('change-regression')),
            navigationItem('quality', <SafetyCertificateOutlined />, pathFor('quality')),
            navigationItem('release', <SafetyCertificateOutlined />, pathFor('release')),
            navigationItem('ai', <RobotOutlined />, pathFor('ai')),
            navigationItem('ai-changes', <RobotOutlined />, pathFor('ai-changes')),
            navigationItem('reports', <BarChartOutlined />, pathFor('reports')),
            navigationItem('organization', <TeamOutlined />, '/organization'),
            ...(user?.is_system_admin
              ? [
                  navigationItem('fabric', <CloudServerOutlined />, '/execution-fabric'),
                  navigationItem('platform', <ToolOutlined />, '/platform'),
                ]
              : []),
          ]}
        />
      </Sider>
      <Layout>
        <Header className="topbar">
          <Space>
            <Typography.Text strong>接口自动化测试平台</Typography.Text>
            <GlobalSearch />
            <Select
              aria-label="全局项目"
              className="global-project-select"
              allowClear
              loading={projects.isLoading}
              placeholder="全部项目"
              value={projectId ?? undefined}
              onChange={(value?: string) => selectProject(value ?? null)}
              options={projects.data?.items.map((project) => ({
                value: project.id,
                label: project.name,
              }))}
            />
          </Space>
          <Space>
            <Tag color="blue">LOCAL</Tag>
            <Avatar size="small" icon={<UserOutlined />} />
            <Typography.Text>{user?.display_name}</Typography.Text>
            <Button type="text" icon={<LogoutOutlined />} onClick={() => void logout()}>
              退出
            </Button>
          </Space>
        </Header>
        <Content className="content">
          <Breadcrumb
            className="page-breadcrumb"
            items={breadcrumbItems(currentProject?.name ?? null, section)}
          />
          <AuthenticatedContent
            hasNoProjects={hasNoProjects}
            isGlobalAdministration={isGlobalAdministration}
            projectId={projectId}
          />
        </Content>
      </Layout>
    </Layout>
  )
}

function AuthenticatedContent({
  hasNoProjects,
  isGlobalAdministration,
  projectId,
}: {
  hasNoProjects: boolean
  isGlobalAdministration: boolean
  projectId: string | null
}) {
  return (
    <Suspense fallback={<PageLoading />}>
      {hasNoProjects && !isGlobalAdministration ? (
        <ProjectEmptyState />
      ) : (
        <ApplicationRoutes key={projectId ?? 'global'} />
      )}
    </Suspense>
  )
}

function isNoProjectView(projectCount: number | undefined, projectId: string | null): boolean {
  return projectCount === 0 && projectId === null
}

function isGlobalAdministrationSection(section: ProjectSection): boolean {
  return section === 'platform' || section === 'fabric' || section === 'organization'
}

function ApplicationRoutes() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/dashboard" replace />} />
      <Route path="/dashboard" element={<DashboardPage />} />
      <Route path="/projects/:projectId/dashboard" element={<DashboardPage />} />
      <Route path="/projects/:projectId/settings" element={<ProjectsPage />} />
      <Route path="/projects/:projectId/services" element={<ServiceCatalogPage />} />
      <Route path="/projects/:projectId/request-targets" element={<RequestTargetsPage />} />
      <Route path="/projects/:projectId/apis" element={<ApiConsolePage />} />
      <Route path="/projects/:projectId/protocols" element={<ProtocolWorkbenchPage />} />
      <Route path="/projects/:projectId/assets" element={<TestAssetsPage />} />
      <Route path="/projects/:projectId/workflows" element={<WorkflowsPage />} />
      <Route path="/projects/:projectId/data" element={<DataMockPage />} />
      <Route path="/projects/:projectId/tasks" element={<TestPlansPage />} />
      <Route path="/projects/:projectId/performance" element={<PerformanceLabPage />} />
      <Route path="/projects/:projectId/environments" element={<EnvironmentLabPage />} />
      <Route path="/projects/:projectId/contracts" element={<ContractHubPage />} />
      <Route path="/projects/:projectId/test-engineering" element={<TestEngineeringPage />} />
      <Route path="/projects/:projectId/contexts" element={<ContextInspectorPage />} />
      <Route path="/projects/:projectId/impact" element={<ImpactAnalysisPage />} />
      <Route path="/projects/:projectId/change-regression" element={<ChangeRegressionPage />} />
      <Route path="/projects/:projectId/quality" element={<QualityCenterPage />} />
      <Route path="/projects/:projectId/release" element={<ReleaseGatePage />} />
      <Route path="/projects/:projectId/ai" element={<AIAssistantPage />} />
      <Route path="/projects/:projectId/ai-changes" element={<AIChangeSetsPage />} />
      <Route path="/projects/:projectId/reports" element={<ReportsPage />} />
      <Route path="/platform" element={<PlatformCapabilitiesPage />} />
      <Route path="/execution-fabric" element={<ExecutionFabricPage />} />
      <Route path="/organization" element={<OrganizationGovernancePage />} />
      <Route path="/projects/:projectId" element={<ProjectIndexRedirect />} />
      {(
        [
          'settings',
          'services',
          'request-targets',
          'apis',
          'protocols',
          'assets',
          'workflows',
          'data',
          'tasks',
          'performance',
          'environments',
          'contracts',
          'test-engineering',
          'contexts',
          'impact',
          'change-regression',
          'quality',
          'release',
          'ai',
          'ai-changes',
          'reports',
        ] as const
      ).map((section) => (
        <Route
          key={section}
          path={`/${section}`}
          element={<DefaultProjectRedirect section={section} />}
        />
      ))}
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  )
}

function DefaultProjectRedirect({ section }: { section: ProjectSection }) {
  const { projects } = useProjectContext()
  if (projects.isLoading) return <PageLoading />
  const projectId = projects.data?.items.at(0)?.id
  if (!projectId) return <ProjectEmptyState />
  return <Navigate to={projectPath(projectId, section)} replace />
}

function ProjectIndexRedirect() {
  const { projectId } = useProjectContext()
  return <Navigate to={projectId ? projectPath(projectId, 'dashboard') : '/dashboard'} replace />
}

function navigationItem(section: ProjectSection, icon: ReactNode, path: string) {
  return { key: section, icon, label: <Link to={path}>{sectionLabels[section]}</Link> }
}

function breadcrumbItems(projectName: string | null, section: ProjectSection) {
  const items = [{ title: <Link to="/dashboard">FlowTest</Link> }]
  if (projectName) items.push({ title: <span>{projectName}</span> })
  items.push({ title: <span>{sectionLabels[section]}</span> })
  return items
}

function FullPageLoading() {
  return (
    <main className="centered-page" aria-label="正在加载">
      <Spin size="large" />
    </main>
  )
}

function PageLoading() {
  return (
    <div className="page-loading">
      <Spin />
    </div>
  )
}
