import {
  ApiOutlined,
  ApartmentOutlined,
  BarChartOutlined,
  DashboardOutlined,
  FolderOpenOutlined,
  LogoutOutlined,
  ScheduleOutlined,
  UserOutlined,
} from '@ant-design/icons'
import { Avatar, Button, Layout, Menu, Space, Spin, Tag, Typography } from 'antd'
import { lazy, Suspense, useEffect, useState } from 'react'

import LoginPage from './features/auth/LoginPage'
import PasswordChangePage from './features/auth/PasswordChangePage'
import { useAuthStore } from './features/auth/auth-store'

const DashboardPage = lazy(() => import('./pages/DashboardPage'))
const ApiConsolePage = lazy(() => import('./pages/ApiConsolePage'))
const WorkflowsPage = lazy(() => import('./pages/WorkflowsPage'))
const TestPlansPage = lazy(() => import('./pages/TestPlansPage'))
const ReportsPage = lazy(() => import('./pages/ReportsPage'))

const { Header, Content, Sider } = Layout
type PageKey = 'dashboard' | 'apis' | 'workflows' | 'tasks' | 'reports'

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
  return <AuthenticatedShell />
}

function AuthenticatedShell() {
  const user = useAuthStore((state) => state.user)
  const logout = useAuthStore((state) => state.logout)
  const [page, setPage] = useState<PageKey>('dashboard')
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
          selectedKeys={[page]}
          onClick={({ key }) => setPage(key as PageKey)}
          items={[
            { key: 'dashboard', icon: <DashboardOutlined />, label: '首页' },
            { key: 'projects', icon: <FolderOpenOutlined />, label: '项目管理', disabled: true },
            { key: 'apis', icon: <ApiOutlined />, label: '接口管理' },
            { key: 'workflows', icon: <ApartmentOutlined />, label: '流程编排' },
            { key: 'tasks', icon: <ScheduleOutlined />, label: '任务执行' },
            { key: 'reports', icon: <BarChartOutlined />, label: '测试报告' },
          ]}
        />
      </Sider>
      <Layout>
        <Header className="topbar">
          <Typography.Text strong>接口自动化测试平台</Typography.Text>
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
          <Suspense fallback={<PageLoading />}>
            {page === 'dashboard' && <DashboardPage />}
            {page === 'apis' && <ApiConsolePage />}
            {page === 'workflows' && <WorkflowsPage />}
            {page === 'tasks' && <TestPlansPage />}
            {page === 'reports' && <ReportsPage />}
          </Suspense>
        </Content>
      </Layout>
    </Layout>
  )
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
