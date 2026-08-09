import {
  ApiOutlined,
  ApartmentOutlined,
  CheckCircleOutlined,
  FolderOpenOutlined,
} from '@ant-design/icons'
import { Alert, Card, Empty, Progress, Statistic, Table, Tag, Typography } from 'antd'

import { DashboardTrendChart } from '../features/dashboard/DashboardTrendChart'
import { useDashboard } from '../features/dashboard/use-dashboard'
import { apiErrorMessage, type DashboardSummary, type Page, type RecentExecution } from '../lib/api'

const statusLabels: Record<string, string> = {
  running: '运行中',
  passed: '通过',
  failed: '失败',
  error: '异常',
  cancelled: '已取消',
}

const statusColors: Record<string, string> = {
  running: 'processing',
  passed: 'success',
  failed: 'error',
  error: 'error',
  cancelled: 'default',
}

const emptySummary: DashboardSummary = {
  project_count: 0,
  api_count: 0,
  workflow_count: 0,
  today_total: 0,
  today_passed: 0,
  today_failed: 0,
  pass_rate: 0,
  trend: [],
}

export default function DashboardPage() {
  const dashboard = useDashboard()
  const error = dashboard.summary.error ?? dashboard.recent.error
  const description = dashboard.currentProject
    ? `当前查看：${dashboard.currentProject.name}`
    : '汇总所有可访问项目的接口资产与执行质量。'
  return (
    <>
      <div className="page-heading">
        <div>
          <Typography.Title level={2}>工作台</Typography.Title>
          <Typography.Text type="secondary">{description}</Typography.Text>
        </div>
      </div>

      {error && (
        <Alert type="error" showIcon title="工作台加载失败" description={apiErrorMessage(error)} />
      )}

      <DashboardStats summary={dashboard.summary.data} loading={dashboard.summary.isLoading} />
      <DashboardActivity
        summary={dashboard.summary.data}
        summaryLoading={dashboard.summary.isLoading}
        recent={dashboard.recent.data}
        recentLoading={dashboard.recent.isLoading}
      />
    </>
  )
}

function DashboardStats({
  summary = emptySummary,
  loading,
}: {
  summary?: DashboardSummary
  loading: boolean
}) {
  return (
    <div className="stat-grid">
      <Card loading={loading}>
        <Statistic title="项目数" value={summary.project_count} prefix={<FolderOpenOutlined />} />
      </Card>
      <Card loading={loading}>
        <Statistic title="接口数" value={summary.api_count} prefix={<ApiOutlined />} />
      </Card>
      <Card loading={loading}>
        <Statistic title="工作流" value={summary.workflow_count} prefix={<ApartmentOutlined />} />
      </Card>
      <Card loading={loading}>
        <Statistic
          title="今日通过"
          value={summary.today_passed}
          suffix={`/ ${summary.today_total}`}
          prefix={<CheckCircleOutlined />}
        />
      </Card>
    </div>
  )
}

function DashboardActivity({
  summary,
  summaryLoading,
  recent,
  recentLoading,
}: {
  summary?: DashboardSummary
  summaryLoading: boolean
  recent?: Page<RecentExecution>
  recentLoading: boolean
}) {
  return (
    <div className="dashboard-grid">
      <Card title="最近 7 日执行" className="trend-card" loading={summaryLoading}>
        <DashboardTrendChart points={summary?.trend ?? []} />
        <div className="dashboard-pass-rate">
          <Typography.Text type="secondary">今日终态通过率</Typography.Text>
          <Progress percent={summary?.pass_rate ?? 0} status="active" />
        </div>
      </Card>
      <Card title="最近运行" loading={recentLoading}>
        <RecentExecutionTable items={recent?.items ?? []} />
      </Card>
    </div>
  )
}

function RecentExecutionTable({ items }: { items: RecentExecution[] }) {
  if (!items.length) return <Empty description="暂无执行记录" />
  return (
    <Table
      rowKey={(record) => `${record.kind}:${record.id}`}
      size="small"
      pagination={false}
      dataSource={items}
      columns={[
        {
          title: '类型',
          dataIndex: 'kind',
          width: 76,
          render: (kind: RecentExecution['kind']) => (kind === 'api' ? '接口' : '工作流'),
        },
        { title: '名称', dataIndex: 'target_name', ellipsis: true },
        { title: '项目', dataIndex: 'project_name', ellipsis: true },
        {
          title: '状态',
          dataIndex: 'status',
          width: 82,
          render: (status: string) => (
            <Tag color={statusColors[status] ?? 'default'}>{statusLabels[status] ?? status}</Tag>
          ),
        },
        {
          title: '开始时间',
          dataIndex: 'started_at',
          width: 150,
          render: (value: string) => formatShanghaiTime(value),
        },
      ]}
    />
  )
}

function formatShanghaiTime(value: string): string {
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(new Date(value))
}
