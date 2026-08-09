import {
  ApiOutlined,
  ApartmentOutlined,
  BarChartOutlined,
  CheckCircleOutlined,
  DashboardOutlined,
  FolderOpenOutlined,
} from '@ant-design/icons'
import { Card, Layout, Menu, Progress, Space, Statistic, Table, Tag, Typography } from 'antd'

const { Header, Content, Sider } = Layout

const recentRuns = [
  { key: '1', name: '用户登录流程', project: '示例项目', status: '通过', rate: '100%' },
  { key: '2', name: '订单回归流程', project: '示例项目', status: '等待', rate: '—' },
]

export default function App() {
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
          defaultSelectedKeys={['dashboard']}
          items={[
            { key: 'dashboard', icon: <DashboardOutlined />, label: '首页' },
            { key: 'projects', icon: <FolderOpenOutlined />, label: '项目管理' },
            { key: 'apis', icon: <ApiOutlined />, label: '接口管理' },
            { key: 'workflows', icon: <ApartmentOutlined />, label: '流程编排' },
            { key: 'reports', icon: <BarChartOutlined />, label: '测试报告' },
          ]}
        />
      </Sider>
      <Layout>
        <Header className="topbar">
          <Typography.Text strong>接口自动化测试平台</Typography.Text>
          <Tag color="blue">LOCAL</Tag>
        </Header>
        <Content className="content">
          <div className="page-heading">
            <div>
              <Typography.Title level={2}>工作台</Typography.Title>
              <Typography.Text type="secondary">项目工程已初始化，下一步从单接口闭环开始。</Typography.Text>
            </div>
          </div>

          <div className="stat-grid">
            <Card><Statistic title="项目数" value={0} prefix={<FolderOpenOutlined />} /></Card>
            <Card><Statistic title="接口数" value={0} prefix={<ApiOutlined />} /></Card>
            <Card><Statistic title="工作流" value={0} prefix={<ApartmentOutlined />} /></Card>
            <Card><Statistic title="今日通过" value={0} prefix={<CheckCircleOutlined />} /></Card>
          </div>

          <div className="dashboard-grid">
            <Card title="最近 7 日执行" className="trend-card">
              <Space direction="vertical" size="middle" className="full-width">
                <Typography.Text type="secondary">执行引擎接入后在此展示趋势。</Typography.Text>
                <Progress percent={0} />
              </Space>
            </Card>
            <Card title="最近运行">
              <Table
                size="small"
                pagination={false}
                dataSource={recentRuns}
                columns={[
                  { title: '名称', dataIndex: 'name' },
                  { title: '项目', dataIndex: 'project' },
                  {
                    title: '状态',
                    dataIndex: 'status',
                    render: (status: string) => <Tag color={status === '通过' ? 'green' : 'default'}>{status}</Tag>,
                  },
                  { title: '通过率', dataIndex: 'rate' },
                ]}
              />
            </Card>
          </div>
        </Content>
      </Layout>
    </Layout>
  )
}
