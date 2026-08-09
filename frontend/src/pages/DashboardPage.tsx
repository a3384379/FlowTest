import {
  ApiOutlined,
  ApartmentOutlined,
  CheckCircleOutlined,
  FolderOpenOutlined,
} from '@ant-design/icons'
import { Card, Empty, Progress, Space, Statistic, Typography } from 'antd'

export default function DashboardPage() {
  return (
    <>
      <div className="page-heading">
        <div>
          <Typography.Title level={2}>工作台</Typography.Title>
          <Typography.Text type="secondary">
            从接口管理创建第一个请求，并立即查看断言和执行历史。
          </Typography.Text>
        </div>
      </div>

      <div className="stat-grid">
        <Card>
          <Statistic title="项目数" value={0} prefix={<FolderOpenOutlined />} />
        </Card>
        <Card>
          <Statistic title="接口数" value={0} prefix={<ApiOutlined />} />
        </Card>
        <Card>
          <Statistic title="工作流" value={0} prefix={<ApartmentOutlined />} />
        </Card>
        <Card>
          <Statistic title="今日通过" value={0} prefix={<CheckCircleOutlined />} />
        </Card>
      </div>

      <div className="dashboard-grid">
        <Card title="最近 7 日执行" className="trend-card">
          <Space orientation="vertical" size="middle" className="full-width">
            <Typography.Text type="secondary">执行后将在此展示通过趋势。</Typography.Text>
            <Progress percent={0} />
          </Space>
        </Card>
        <Card title="最近运行">
          <Empty description="暂无执行记录" />
        </Card>
      </div>
    </>
  )
}
