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
  Descriptions,
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

import { ReportTrendChart } from '../features/reports/ReportTrendChart'
import type { CreateNotificationWebhookInput } from '../features/reports/report-service'
import { useReports } from '../features/reports/use-reports'
import type {
  FailureCategory,
  NotificationDelivery,
  NotificationWebhook,
  ReportExecution,
  ReportNode,
} from '../lib/api'

export default function ReportsPage() {
  const state = useReports()
  return (
    <>
      <ReportHeading state={state} />
      <ReportOverview state={state} />
      <ExecutionCard state={state} />
      <NotificationCard state={state} />
      <ReportDialogs state={state} />
    </>
  )
}

type ReportState = ReturnType<typeof useReports>

function ReportHeading({ state }: { state: ReportState }) {
  return (
    <div className="page-heading">
      <div>
        <Typography.Title level={2}>测试报告</Typography.Title>
        <Typography.Text type="secondary">
          查看执行趋势、失败分类和脱敏步骤详情，并导出可离线查看的 HTML 报告。
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
          disabled={!state.projectId}
          onClick={() => state.setWebhookOpen(true)}
        >
          配置通知
        </Button>
      </Space>
    </div>
  )
}

function ReportOverview({ state }: { state: ReportState }) {
  const items = state.reports.data?.items ?? []
  const passed = items.filter((item) => item.status === 'passed').length
  const failed = items.filter((item) => item.status === 'failed').length
  const passRate = items.length ? Math.round((passed * 1000) / items.length) / 10 : 0
  return (
    <>
      <div className="stat-grid">
        <Card>
          <Statistic title="执行总数" value={state.reports.data?.total ?? 0} />
        </Card>
        <Card>
          <Statistic title="通过" value={passed} styles={{ content: { color: '#22a06b' } }} />
        </Card>
        <Card>
          <Statistic title="失败" value={failed} styles={{ content: { color: '#dc4446' } }} />
        </Card>
        <Card>
          <Statistic title="通过率" value={passRate} suffix="%" />
          <Progress percent={passRate} showInfo={false} strokeColor="#22a06b" />
        </Card>
      </div>
      <div className="report-overview-grid">
        <Card title="最近 7 日趋势" loading={state.trend.isLoading}>
          <ReportTrendChart trend={state.trend.data} />
        </Card>
        <Card title="失败分类">
          <Space wrap>
            {(state.trend.data?.failures ?? []).map((item) => (
              <Tag color="red" key={item.category}>
                {failureLabel(item.category)} {item.count}
              </Tag>
            ))}
            {!state.trend.data?.failures.length && (
              <Typography.Text type="secondary">暂无失败</Typography.Text>
            )}
          </Space>
        </Card>
      </div>
    </>
  )
}

function ExecutionCard({ state }: { state: ReportState }) {
  return (
    <Card title="执行中心" className="workflow-result-card" loading={state.reports.isLoading}>
      <Table
        rowKey="id"
        size="small"
        pagination={false}
        dataSource={state.reports.data?.items ?? []}
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
      render: (value: number | null) => (value === null ? '运行中' : `${value} ms`),
    },
    {
      title: '开始时间',
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
      <ReportDetailDialog state={state} />
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

function ReportDetailDialog({ state }: { state: ReportState }) {
  const detail = state.detail.data
  return (
    <Modal
      title="执行报告详情"
      open={Boolean(state.selectedExecutionId)}
      width={1040}
      footer={null}
      loading={state.detail.isLoading}
      onCancel={() => state.selectExecution(null)}
    >
      {detail && (
        <>
          <Descriptions
            size="small"
            items={[
              { key: 'workflow', label: '工作流', children: detail.summary.workflow_name },
              { key: 'version', label: '版本', children: `v${detail.summary.workflow_version}` },
              {
                key: 'status',
                label: '状态',
                children: <StatusTag status={detail.summary.status} />,
              },
              { key: 'duration', label: '耗时', children: `${detail.summary.duration_ms ?? 0} ms` },
            ]}
          />
          <Table
            rowKey="id"
            size="small"
            pagination={false}
            dataSource={detail.nodes}
            expandable={{ expandedRowRender: (node) => <NodePayload node={node} /> }}
            columns={[
              { title: '步骤', dataIndex: 'name' },
              { title: '类型', dataIndex: 'node_type' },
              {
                title: '状态',
                dataIndex: 'status',
                render: (value: string) => <StatusTag status={value} />,
              },
              { title: '尝试', dataIndex: 'attempts' },
              {
                title: '耗时',
                dataIndex: 'duration_ms',
                render: (value: number | null) => `${value ?? 0} ms`,
              },
              { title: '错误', dataIndex: 'error_message' },
            ]}
          />
        </>
      )}
    </Modal>
  )
}

function NodePayload({ node }: { node: ReportNode }) {
  return (
    <div className="report-payload-grid">
      <Payload title="脱敏请求" value={node.request} />
      <Payload title="脱敏响应" value={node.response} />
      <Payload title="提取/断言" value={node.extraction ?? node.assertion} />
      <Payload title="变量映射" value={node.input_mappings} />
    </div>
  )
}

function Payload({ title, value }: { title: string; value: unknown }) {
  return (
    <div>
      <Typography.Text strong>{title}</Typography.Text>
      <pre className="report-code">{JSON.stringify(value, null, 2) ?? '—'}</pre>
    </div>
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
