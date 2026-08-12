import {
  ApiOutlined,
  ApartmentOutlined,
  BarChartOutlined,
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
  UserOutlined,
} from '@ant-design/icons'
import {
  Avatar,
  Breadcrumb,
  Button,
  Empty,
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
import { projectPath, type ProjectSection } from './features/projects/project-routing'
import { useProjectContext } from './features/projects/use-project-context'

const DashboardPage = lazy(() => import('./pages/DashboardPage'))
const ApiConsolePage = lazy(() => import('./pages/ApiConsolePage'))
const WorkflowsPage = lazy(() => import('./pages/WorkflowsPage'))
const TestAssetsPage = lazy(() => import('./pages/TestAssetsPage'))
const TestPlansPage = lazy(() => import('./pages/TestPlansPage'))
const PerformanceLabPage = lazy(() => import('./pages/PerformanceLabPage'))
const EnvironmentLabPage = lazy(() => import('./pages/EnvironmentLabPage'))
const ContractHubPage = lazy(() => import('./pages/ContractHubPage'))
const ImpactAnalysisPage = lazy(() => import('./pages/ImpactAnalysisPage'))
const ReportsPage = lazy(() => import('./pages/ReportsPage'))
const QualityCenterPage = lazy(() => import('./pages/QualityCenterPage'))
const AIAssistantPage = lazy(() => import('./pages/AIAssistantPage'))
const ProjectsPage = lazy(() => import('./pages/ProjectsPage'))
const DataMockPage = lazy(() => import('./pages/DataMockPage'))
const PlatformCapabilitiesPage = lazy(() => import('./pages/PlatformCapabilitiesPage'))
const ProtocolWorkbenchPage = lazy(() => import('./pages/ProtocolWorkbenchPage'))

const { Header, Content, Sider } = Layout

const sectionLabels: Record<ProjectSection, string> = {
  dashboard: '首页',
  settings: '项目管理',
  apis: '接口管理',
  protocols: '多协议工作台',
  assets: '测试资产',
  workflows: '流程编排',
  data: '数据与 Mock',
  tasks: '任务执行',
  performance: '性能实验室',
  environments: '环境实验室',
  contracts: '契约中心',
  impact: '影响分析',
  quality: '质量中心',
  ai: 'AI 助手',
  reports: '测试报告',
  platform: '平台管理',
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
            navigationItem('apis', <ApiOutlined />, pathFor('apis')),
            navigationItem('protocols', <CodeOutlined />, pathFor('protocols')),
            navigationItem('assets', <FundProjectionScreenOutlined />, pathFor('assets')),
            navigationItem('workflows', <ApartmentOutlined />, pathFor('workflows')),
            navigationItem('data', <DatabaseOutlined />, pathFor('data')),
            navigationItem('tasks', <ScheduleOutlined />, pathFor('tasks')),
            navigationItem('performance', <ExperimentOutlined />, pathFor('performance')),
            navigationItem('environments', <CloudServerOutlined />, pathFor('environments')),
            navigationItem('contracts', <ShareAltOutlined />, pathFor('contracts')),
            navigationItem('impact', <FileSearchOutlined />, pathFor('impact')),
            navigationItem('quality', <SafetyCertificateOutlined />, pathFor('quality')),
            navigationItem('ai', <RobotOutlined />, pathFor('ai')),
            navigationItem('reports', <BarChartOutlined />, pathFor('reports')),
            ...(user?.is_system_admin
              ? [navigationItem('platform', <ToolOutlined />, '/platform')]
              : []),
          ]}
        />
      </Sider>
      <Layout>
        <Header className="topbar">
          <Space>
            <Typography.Text strong>接口自动化测试平台</Typography.Text>
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
          <Suspense fallback={<PageLoading />}>
            <ApplicationRoutes key={projectId ?? 'global'} />
          </Suspense>
        </Content>
      </Layout>
    </Layout>
  )
}

function ApplicationRoutes() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/dashboard" replace />} />
      <Route path="/dashboard" element={<DashboardPage />} />
      <Route path="/projects/:projectId/dashboard" element={<DashboardPage />} />
      <Route path="/projects/:projectId/settings" element={<ProjectsPage />} />
      <Route path="/projects/:projectId/apis" element={<ApiConsolePage />} />
      <Route path="/projects/:projectId/protocols" element={<ProtocolWorkbenchPage />} />
      <Route path="/projects/:projectId/assets" element={<TestAssetsPage />} />
      <Route path="/projects/:projectId/workflows" element={<WorkflowsPage />} />
      <Route path="/projects/:projectId/data" element={<DataMockPage />} />
      <Route path="/projects/:projectId/tasks" element={<TestPlansPage />} />
      <Route path="/projects/:projectId/performance" element={<PerformanceLabPage />} />
      <Route path="/projects/:projectId/environments" element={<EnvironmentLabPage />} />
      <Route path="/projects/:projectId/contracts" element={<ContractHubPage />} />
      <Route path="/projects/:projectId/impact" element={<ImpactAnalysisPage />} />
      <Route path="/projects/:projectId/quality" element={<QualityCenterPage />} />
      <Route path="/projects/:projectId/ai" element={<AIAssistantPage />} />
      <Route path="/projects/:projectId/reports" element={<ReportsPage />} />
      <Route path="/platform" element={<PlatformCapabilitiesPage />} />
      <Route path="/projects/:projectId" element={<ProjectIndexRedirect />} />
      {(
        [
          'settings',
          'apis',
          'protocols',
          'assets',
          'workflows',
          'data',
          'tasks',
          'performance',
          'environments',
          'contracts',
          'impact',
          'quality',
          'ai',
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
  if (!projectId) return <Empty description="暂无可访问项目" />
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
