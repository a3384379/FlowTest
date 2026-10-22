import QueryFailureNotice from '../components/QueryFailureNotice'
import CatalogPagination from '../components/CatalogPagination'
import {
  DownloadOutlined,
  EyeOutlined,
  PlusOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons'
import {
  Alert,
  Button,
  Card,
  Form,
  Input,
  Modal,
  Progress,
  Select,
  Space,
  Statistic,
  Switch,
  Table,
  Tag,
  Typography,
} from 'antd'
import { useSearchParams } from 'react-router-dom'
import ReportFilters from '../features/reports/ReportFilters'
import ReportExecutionWorkspace from '../features/reports/ReportExecutionWorkspace'
import {
  clearExecutionEvidence,
  executionAttempt,
  executionEvidence,
  writeExecutionEvidence,
} from '../features/workflows/execution-navigation'
import { iceColors } from '../theme/ice-theme'

import { ReportTrendChart } from '../features/reports/ReportTrendChart'
import type { CreateNotificationWebhookInput } from '../features/reports/report-service'
import { useReports } from '../features/reports/use-reports'
import { useProjectContext } from '../features/projects/use-project-context'
import type {
  FailureCategory,
  NotificationDelivery,
  NotificationWebhook,
  ReportExecution,
  ReportTrend,
} from '../lib/api'

export default function ReportsPage() {
  const { projectId } = useProjectContext()
  return <ReportWorkspace key={projectId ?? 'global'} />
}

function ReportWorkspace() {
  const [searchParams, setSearchParams] = useSearchParams()
  const reports = useReports(searchParams.get('execution') ?? undefined)
  const state = {
    ...reports,
    selectExecution: (executionId: string | null) => {
      const next = new URLSearchParams(searchParams)
      next.delete('node')
      next.delete('attempt')
      clearExecutionEvidence(next)
      if (executionId) next.set('execution', executionId)
      else next.delete('execution')
      setSearchParams(next)
    },
  }
  if (state.selectedExecutionId && state.projectId)
    return (
      <ReportExecutionWorkspace
        projectId={state.projectId}
        executionId={state.selectedExecutionId}
        detail={state.detail.data}
        loading={state.detail.isLoading}
        error={state.detail.error}
        nodeId={searchParams.get('node')}
        attempt={executionAttempt(searchParams)}
        evidence={executionEvidence(searchParams)}
        onSelectEvidence={(evidence) => {
          const next = new URLSearchParams(searchParams)
          writeExecutionEvidence(next, evidence)
          setSearchParams(next, { replace: true })
        }}
        onSelectNode={(nodeId) => {
          const next = new URLSearchParams(searchParams)
          next.set('node', nodeId)
          if (nodeId !== searchParams.get('node')) {
            next.delete('attempt')
            clearExecutionEvidence(next)
          }
          setSearchParams(next, { replace: true })
        }}
        onSelectAttempt={(nodeId, attempt) => {
          const next = new URLSearchParams(searchParams)
          if (nodeId !== searchParams.get('node')) clearExecutionEvidence(next)
          next.set('node', nodeId)
          next.set('attempt', String(attempt))
          setSearchParams(next, { replace: true })
        }}
        onBack={() => state.selectExecution(null)}
        onRetry={() => void state.detail.refetch()}
        onExport={() => void state.exportHtml(state.selectedExecutionId!)}
      />
    )
  return (
    <div className="reports-page">
      <ReportHeading state={state} />
      <QueryFailureNotice
        queries={[state.reports, state.trend, state.webhooks, state.permissions]}
      />
      <ReportFilters
        projectId={state.projectId}
        state={state.reportScope}
        onRefresh={() => void state.refreshReports()}
      />
      <ReportOverview state={state} />
      <ExecutionCard state={state} />
      <div className="catalog-controls">
        <CatalogPagination query={state.deliveries} label="通知投递" />
      </div>
      <NotificationCard state={state} />
      <ReportDialogs state={state} />
    </div>
  )
}

type ReportState = ReturnType<typeof useReports>

function ReportHeading({ state }: { state: ReportState }) {
  return (
    <div className="page-heading">
      <div>
        <Typography.Title level={2}>测试报告</Typography.Title>
        <Typography.Text type="secondary">
          查看执行趋势、失败分类和步骤详情，并导出可离线查看的 HTML 报告。
        </Typography.Text>
      </div>
      <Space>
        <Select
          aria-label="报告项目"
          className="context-select"
          placeholder="选择项目"
          value={state.projectId}
          options={state.projects.data?.items.map((item) => ({ value: item.id, label: item.name }))}
          onChange={state.setProjectSelection}
        />
        <Button
          type="primary"
          icon={<PlusOutlined />}
          disabled={!state.projectId || !state.canManageNotifications}
          onClick={() => state.setWebhookOpen(true)}
        >
          配置通知
        </Button>
      </Space>
    </div>
  )
}

function ReportOverview({ state }: { state: ReportState }) {
  return (
    <>
      <ReportCounts data={state.trend.data} />
      <div className="report-overview-grid">
        <Card title="当前范围趋势（UTC）" loading={state.trend.isLoading}>
          <ReportTrendChart trend={state.trend.data} />
        </Card>
        <Card title="失败分类">
          <FailureCategories trend={state.trend.data} />
        </Card>
      </div>
    </>
  )
}

function ReportCounts({ data }: { data: ReportState['trend']['data'] }) {
  const summary = data?.summary
  return (
    <div className="stat-grid">
      <Card>
        <Statistic title="范围内执行总数" value={summary?.total ?? '—'} />
        <Typography.Text type="secondary">
          <ReportPendingCaption summary={summary} />
        </Typography.Text>
      </Card>
      <Card>
        <Statistic
          title="范围内通过"
          value={summary?.passed ?? '—'}
          styles={{ content: { color: iceColors.success } }}
        />
      </Card>
      <Card>
        <Statistic
          title="范围内失败"
          value={summary?.failed ?? '—'}
          styles={{ content: { color: iceColors.danger } }}
        />
      </Card>
      <ReportPassRate summary={summary} />
    </div>
  )
}

function ReportPendingCaption({ summary }: { summary: ReportTrend['summary'] | undefined }) {
  return (
    <>
      待完成 {summary?.pending ?? '—'} 条 · 已取消 {summary?.cancelled ?? '—'} 条
    </>
  )
}

function ReportPassRate({ summary }: { summary: ReportTrend['summary'] | undefined }) {
  const rate = summary?.pass_rate ?? null
  return (
    <Card>
      <Statistic
        title="范围内通过率"
        value={rate ?? '—'}
        suffix={rate === null ? undefined : '%'}
      />
      <Typography.Text type="secondary">
        {summary
          ? `${summary.passed}/${summary.completed} 条已完成记录（含取消，排除排队与运行中）`
          : '未提供统计数据'}
      </Typography.Text>
      {rate !== null && (
        <Progress percent={rate} showInfo={false} strokeColor={iceColors.success} />
      )}
    </Card>
  )
}

function FailureCategories({ trend }: { trend: ReportState['trend']['data'] }) {
  return (
    <Space wrap>
      {trend?.failures.map((item) => (
        <Tag color="error" key={item.category}>
          {failureLabel(item.category)} {item.count}
        </Tag>
      ))}
      {!trend?.failures.length && (
        <Typography.Text type="secondary">
          {trend ? '当前范围暂无失败' : '未提供分类数据'}
        </Typography.Text>
      )}
    </Space>
  )
}

function ExecutionCard({ state }: { state: ReportState }) {
  const items = state.reports.data?.items ?? []
  return (
    <Card title="执行记录" className="workflow-result-card" loading={state.reports.isLoading}>
      <Typography.Paragraph type="secondary">
        当前页 {items.length} 条 · 当前筛选共 {state.reports.data?.total ?? '—'} 条
      </Typography.Paragraph>
      <Table
        rowKey="id"
        size="small"
        pagination={{
          current: state.page,
          pageSize: 50,
          total: state.reports.data?.total ?? 0,
          showSizeChanger: false,
          onChange: state.setPage,
        }}
        scroll={{ x: 800 }}
        dataSource={items}
        locale={{ emptyText: '暂无执行记录' }}
        columns={executionColumns(state)}
      />
    </Card>
  )
}

function executionColumns(state: ReportState) {
  return [
    {
      title: '工作流',
      width: 220,
      render: (_: unknown, item: ReportExecution) =>
        `${item.workflow_name} · v${item.workflow_version}`,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (value: string) => <StatusTag status={value} />,
    },
    {
      title: '步骤',
      width: 150,
      render: (_: unknown, item: ReportExecution) =>
        `${item.passed_nodes}/${item.total_nodes} 通过 · ${item.failed_nodes} 失败`,
    },
    {
      title: '失败分类',
      dataIndex: 'failure_category',
      width: 120,
      render: (value: FailureCategory) => (value === 'none' ? '—' : failureLabel(value)),
    },
    {
      title: '耗时',
      dataIndex: 'duration_ms',
      width: 100,
      render: (value: number | null, item: ReportExecution) =>
        value === null ? (item.status === 'running' ? '运行中' : '未提供') : `${value} ms`,
    },
    {
      title: '开始时间（北京时间）',
      dataIndex: 'started_at',
      render: (value: string) => localTime(value),
    },
    {
      title: '操作',
      width: 160,
      render: (_: unknown, item: ReportExecution) => (
        <Space size={0}>
          <Button type="link" icon={<EyeOutlined />} onClick={() => state.selectExecution(item.id)}>
            详情
          </Button>
          <Button
            type="link"
            icon={<DownloadOutlined />}
            onClick={() => void state.exportHtml(item.id)}
          >
            HTML
          </Button>
        </Space>
      ),
    },
  ]
}

function NotificationCard({ state }: { state: ReportState }) {
  return (
    <div className="report-notification-grid">
      <Card title="通知 Webhook">
        <Table
          rowKey="id"
          size="small"
          pagination={false}
          dataSource={state.webhooks.data ?? []}
          locale={{ emptyText: '暂无通知配置' }}
          columns={[
            { title: '名称', dataIndex: 'name' },
            { title: '地址', dataIndex: 'url', ellipsis: true },
            {
              title: '启用',
              width: 80,
              render: (_: unknown, item: NotificationWebhook) => (
                <Switch
                  checked={item.enabled}
                  disabled={!state.canManageNotifications}
                  aria-label={`启用 ${item.name}`}
                  onChange={(enabled) => void state.setWebhookEnabled(item.id, enabled)}
                />
              ),
            },
          ]}
        />
      </Card>
      <Card title="最近投递">
        <Table
          rowKey="id"
          size="small"
          pagination={false}
          dataSource={state.deliveries.data?.items ?? []}
          locale={{ emptyText: '暂无投递记录' }}
          columns={[
            { title: '事件', dataIndex: 'event_type' },
            {
              title: '状态',
              dataIndex: 'status',
              render: (value: string) => <StatusTag status={value} />,
            },
            {
              title: 'HTTP',
              dataIndex: 'response_status',
              width: 80,
              render: (value: number | null, item: NotificationDelivery) =>
                value ?? item.error_message ?? '—',
            },
          ]}
        />
      </Card>
    </div>
  )
}

function ReportDialogs({ state }: { state: ReportState }) {
  return (
    <>
      <WebhookDialog
        open={state.webhookOpen}
        submitting={state.creatingWebhook}
        onClose={() => state.setWebhookOpen(false)}
        onCreate={state.addWebhook}
      />
      <Modal
        title="Webhook Secret（仅显示一次）"
        open={Boolean(state.revealedSecret)}
        footer={null}
        onCancel={state.dismissSecret}
      >
        <Alert type="warning" showIcon title="关闭后无法再次查看，请保存到安全的凭据库。" />
        <Typography.Paragraph copyable code className="secret-output">
          {state.revealedSecret}
        </Typography.Paragraph>
      </Modal>
    </>
  )
}

function WebhookDialog({
  open,
  submitting,
  onClose,
  onCreate,
}: {
  open: boolean
  submitting: boolean
  onClose: () => void
  onCreate: (input: CreateNotificationWebhookInput) => Promise<void>
}) {
  const [form] = Form.useForm<CreateNotificationWebhookInput>()
  return (
    <Modal
      title="配置签名通知 Webhook"
      open={open}
      confirmLoading={submitting}
      onCancel={onClose}
      onOk={() => form.submit()}
      destroyOnHidden
    >
      <Alert
        type="info"
        showIcon
        icon={<SafetyCertificateOutlined />}
        title="FlowTest 使用时间戳和 HMAC-SHA256 对原始 JSON 请求体签名。"
        className="form-alert"
      />
      <Form
        form={form}
        disabled={submitting}
        layout="vertical"
        initialValues={{ events: ['workflow.completed', 'test_plan.completed'] }}
        onFinish={(values) => void onCreate(values)}
      >
        <Form.Item name="name" label="名称" rules={[{ required: true }]}>
          <Input maxLength={160} />
        </Form.Item>
        <Form.Item name="url" label="HTTPS 地址" rules={[{ required: true }, { type: 'url' }]}>
          <Input placeholder="https://example.com/hooks/flowtest" />
        </Form.Item>
        <Form.Item name="events" label="通知事件" rules={[{ required: true }]}>
          <Select
            mode="multiple"
            options={[
              { value: 'workflow.completed', label: '工作流完成' },
              { value: 'test_plan.completed', label: '测试计划完成' },
            ]}
          />
        </Form.Item>
      </Form>
    </Modal>
  )
}

function StatusTag({ status }: { status: string }) {
  const colors: Record<string, string> = {
    running: 'processing',
    passed: 'success',
    delivered: 'success',
    failed: 'error',
    cancelled: 'warning',
    skipped: 'default',
    pending: 'processing',
  }
  return <Tag color={colors[status]}>{status}</Tag>
}

function failureLabel(category: FailureCategory): string {
  const labels: Record<FailureCategory, string> = {
    assertion: '断言失败',
    timeout: '超时',
    network: '网络错误',
    http_client: 'HTTP 4xx',
    http_server: 'HTTP 5xx',
    configuration: '配置错误',
    cancelled: '已取消',
    runtime: '运行错误',
    none: '无',
  }
  return labels[category]
}

function localTime(value: string): string {
  return new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })
}
