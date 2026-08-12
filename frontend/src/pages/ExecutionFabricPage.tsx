import { CloudServerOutlined, PlusOutlined, SafetyCertificateOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  Descriptions,
  Form,
  Input,
  InputNumber,
  Modal,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
} from 'antd'
import { useMemo, useState } from 'react'

import { useAuthStore } from '../features/auth/auth-store'
import {
  changeRunnerState,
  createFabricPool,
  createRegistrationToken,
  getRunnerFabricOverview,
  listFabricEvents,
  listFabricLeases,
  listFabricPools,
  listFabricTasks,
  type FabricEvent,
  type FabricPool,
  type FabricPoolInput,
  type FabricRunner,
  type FabricTask,
  type RegistrationToken,
  type RunnerFabricOverview,
} from '../features/execution-fabric/execution-fabric-service'

type PoolForm = Omit<FabricPoolInput, 'labels' | 'capabilities'> & {
  labels: string
}

export default function ExecutionFabricPage() {
  const isSystemAdmin = useAuthStore((state) => Boolean(state.user?.is_system_admin))
  if (!isSystemAdmin) {
    return <Alert showIcon type="error" title="仅系统管理员可管理分布式执行面" />
  }
  return <ExecutionFabricWorkspace />
}

function ExecutionFabricWorkspace() {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const [poolDialogOpen, setPoolDialogOpen] = useState(false)
  const [registration, setRegistration] = useState<RegistrationToken | null>(null)
  const overview = useQuery({
    queryKey: ['runner-fabric-overview'],
    queryFn: getRunnerFabricOverview,
  })
  const pools = useQuery({ queryKey: ['runner-fabric-pools'], queryFn: listFabricPools })
  const tasks = useQuery({ queryKey: ['runner-fabric-tasks'], queryFn: listFabricTasks })
  const leases = useQuery({ queryKey: ['runner-fabric-leases'], queryFn: listFabricLeases })
  const events = useQuery({ queryKey: ['runner-fabric-events'], queryFn: listFabricEvents })
  const invalidate = async () => {
    await queryClient.invalidateQueries({ queryKey: ['runner-fabric'] })
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['runner-fabric-overview'] }),
      queryClient.invalidateQueries({ queryKey: ['runner-fabric-pools'] }),
      queryClient.invalidateQueries({ queryKey: ['runner-fabric-tasks'] }),
      queryClient.invalidateQueries({ queryKey: ['runner-fabric-leases'] }),
      queryClient.invalidateQueries({ queryKey: ['runner-fabric-events'] }),
    ])
  }
  const createPool = useMutation({
    mutationFn: createFabricPool,
    onSuccess: async () => {
      setPoolDialogOpen(false)
      await invalidate()
      void message.success('Worker Pool 已创建')
    },
    onError: () => void message.error('Worker Pool 创建失败'),
  })
  const register = useMutation({
    mutationFn: createRegistrationToken,
    onSuccess: setRegistration,
    onError: () => void message.error('注册令牌签发失败'),
  })
  const action = useMutation({
    mutationFn: ({ runnerId, value }: { runnerId: string; value: 'drain' | 'resume' }) =>
      changeRunnerState(runnerId, value),
    onSuccess: async () => {
      await invalidate()
      void message.success('Runner 状态已更新')
    },
    onError: () => void message.error('Runner 状态更新失败'),
  })
  const poolItems = pools.data?.items ?? []
  const taskItems = tasks.data?.items ?? []
  const eventItems = events.data?.items ?? []
  const failed = [overview, pools, tasks, leases, events].some((query) => query.isError)
  return (
    <>
      <div className="page-heading">
        <div>
          <Space align="center">
            <Typography.Title level={2}>分布式执行面</Typography.Title>
            <Tag color="purple">V3 · S29</Tag>
          </Space>
          <Typography.Text type="secondary">
            管理 Worker Pool、队列、Lease 与 Fencing，故障转移时只允许当前 Fence 写入唯一终态。
          </Typography.Text>
        </div>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setPoolDialogOpen(true)}>
          新建 Worker Pool
        </Button>
      </div>
      <Alert
        showIcon
        type={failed ? 'error' : 'info'}
        className="page-alert"
        title={failed ? '执行面数据加载失败' : 'PostgreSQL 是任务、Lease 与 Fence 的唯一真相源'}
        description="Runner 仅执行平台生成并加密持久化的 Workflow Plan，不接受任意镜像、Compose、命令或脚本。"
      />
      <FabricOverview value={overview.data} />
      <div className="execution-fabric-grid">
        <Card title="Worker 列表" className="execution-fabric-workers" loading={pools.isLoading}>
          <Space wrap className="execution-pool-actions">
            {poolItems.map((pool) => (
              <Button key={pool.id} size="small" onClick={() => register.mutate(pool.id)}>
                {pool.name} · 签发注册令牌
              </Button>
            ))}
          </Space>
          <RunnerTable
            pools={poolItems}
            pending={action.isPending || register.isPending}
            onAction={(runnerId, value) => action.mutate({ runnerId, value })}
            onRegister={(poolId) => register.mutate(poolId)}
          />
        </Card>
        <Card title="队列状态" loading={tasks.isLoading}>
          <QueueSummary tasks={taskItems} />
        </Card>
      </div>
      <Card
        title="最近 Lease / Fencing 事件"
        className="performance-card"
        loading={events.isLoading}
      >
        <EventTable events={eventItems} />
      </Card>
      <PoolDialog
        open={poolDialogOpen}
        submitting={createPool.isPending}
        onClose={() => setPoolDialogOpen(false)}
        onCreate={(value) => createPool.mutate(value)}
      />
      <RegistrationDialog value={registration} onClose={() => setRegistration(null)} />
    </>
  )
}

function FabricOverview({ value }: { value?: RunnerFabricOverview }) {
  const overview = value ?? emptyOverview
  const items = [
    ['在线 Worker', overview.runners_online, <CloudServerOutlined key="worker" />],
    ['离线 Worker', overview.runners_offline, undefined],
    ['Drain 中', overview.runners_draining, undefined],
    ['排队任务', overview.queued_tasks, undefined],
    ['活跃 Lease', overview.active_leases, <SafetyCertificateOutlined key="lease" />],
  ] as const
  return (
    <Row gutter={16} className="execution-fabric-overview">
      {items.map(([title, count, icon]) => (
        <Col flex="1" key={title}>
          <Card>
            <Statistic title={title} value={count} prefix={icon} />
          </Card>
        </Col>
      ))}
    </Row>
  )
}

function RunnerTable({
  pools,
  pending,
  onAction,
  onRegister,
}: {
  pools: FabricPool[]
  pending: boolean
  onAction: (runnerId: string, action: 'drain' | 'resume') => void
  onRegister: (poolId: string) => void
}) {
  const rows = useMemo(
    () => pools.flatMap((pool) => pool.runners.map((runner) => ({ pool, runner }))),
    [pools],
  )
  return (
    <Table
      rowKey={({ runner }) => runner.id}
      size="small"
      dataSource={rows}
      pagination={{ pageSize: 8, hideOnSinglePage: true }}
      locale={{ emptyText: '暂无已注册 Runner，请先为 Pool 签发一次性注册令牌' }}
      columns={[
        {
          title: 'Worker',
          render: (_, { runner }) => (
            <Space orientation="vertical" size={0}>
              <Typography.Text strong>{runner.name}</Typography.Text>
              <Typography.Text type="secondary">
                {runner.runtime} · {runner.architecture}
              </Typography.Text>
            </Space>
          ),
        },
        { title: '池', render: (_, { pool }) => pool.name },
        {
          title: '能力',
          render: (_, { runner }) =>
            runner.capabilities.map((item) => <Tag key={item}>{item}</Tag>),
        },
        {
          title: '负载',
          render: (_, { runner }) => `${runner.current_load} / ${runner.max_concurrency}`,
        },
        { title: '心跳', render: (_, { runner }) => heartbeatLabel(runner.last_seen_at) },
        { title: '状态', render: (_, { runner }) => <RunnerStatus value={runner.status} /> },
        {
          title: '操作',
          render: (_, { pool, runner }) => (
            <Space>
              <Button
                size="small"
                loading={pending}
                disabled={runner.status === 'offline' || runner.status === 'disabled'}
                onClick={() =>
                  onAction(runner.id, runner.status === 'draining' ? 'resume' : 'drain')
                }
              >
                {runner.status === 'draining' ? '恢复' : 'Drain'}
              </Button>
              <Button size="small" onClick={() => onRegister(pool.id)}>
                注册令牌
              </Button>
            </Space>
          ),
        },
      ]}
      expandable={{
        expandedRowRender: ({ pool, runner }) => (
          <Descriptions size="small" column={4}>
            <Descriptions.Item label="Agent">{runner.agent_version}</Descriptions.Item>
            <Descriptions.Item label="网络区">{pool.network_zone}</Descriptions.Item>
            <Descriptions.Item label="Lease">{pool.lease_timeout_seconds} 秒</Descriptions.Item>
            <Descriptions.Item label="Fence">PostgreSQL 单调递增</Descriptions.Item>
          </Descriptions>
        ),
      }}
    />
  )
}

function QueueSummary({ tasks }: { tasks: FabricTask[] }) {
  const groups = useMemo(() => {
    const counts = new Map<string, { queued: number; leased: number; failed: number }>()
    for (const task of tasks) {
      const row = counts.get(task.required_runner_type) ?? { queued: 0, leased: 0, failed: 0 }
      if (task.status === 'queued') row.queued += 1
      if (task.status === 'leased') row.leased += 1
      if (task.status === 'failed') row.failed += 1
      counts.set(task.required_runner_type, row)
    }
    return [...counts.entries()]
  }, [tasks])
  if (!groups.length) return <Typography.Text type="secondary">当前队列为空</Typography.Text>
  return (
    <Space orientation="vertical" size="middle" className="execution-queue-list">
      {groups.map(([type, counts]) => (
        <Card size="small" key={type}>
          <Space orientation="vertical" size={2}>
            <Typography.Text strong>{runnerTypeLabel(type)}</Typography.Text>
            <Typography.Text type="secondary">
              排队 {counts.queued} · 运行 {counts.leased} · 失败 {counts.failed}
            </Typography.Text>
          </Space>
        </Card>
      ))}
    </Space>
  )
}

function EventTable({ events }: { events: FabricEvent[] }) {
  return (
    <Table
      rowKey="id"
      size="small"
      dataSource={events}
      pagination={{ pageSize: 20, hideOnSinglePage: true }}
      locale={{ emptyText: '暂无 Lease / Fencing 事件' }}
      columns={[
        { title: '时间', dataIndex: 'created_at', render: formatTime },
        { title: 'Runner', dataIndex: 'runner_id', render: shortId },
        { title: '任务', dataIndex: 'task_id', render: shortId },
        { title: '事件', dataIndex: 'message' },
        {
          title: 'Fencing Token',
          render: (_, event) => String(event.details.fencing_token ?? '—'),
        },
        {
          title: '结果',
          dataIndex: 'kind',
          render: (value) => <Tag color={eventColor(value)}>{eventLabel(value)}</Tag>,
        },
      ]}
    />
  )
}

function PoolDialog({
  open,
  submitting,
  onClose,
  onCreate,
}: {
  open: boolean
  submitting: boolean
  onClose: () => void
  onCreate: (value: FabricPoolInput) => void
}) {
  const [form] = Form.useForm<PoolForm>()
  return (
    <Modal
      title="新建 Worker Pool"
      open={open}
      confirmLoading={submitting}
      okText="创建 Pool"
      cancelText="取消"
      onCancel={onClose}
      onOk={() => void form.validateFields().then((value) => onCreate(poolInput(value)))}
      destroyOnHidden
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={{
          runner_type: 'general',
          runtime: 'docker',
          network_zone: 'default',
          labels: '',
          max_concurrency: 20,
          lease_timeout_seconds: 30,
          heartbeat_timeout_seconds: 90,
        }}
      >
        <Form.Item name="name" label="Pool 名称" rules={[{ required: true }]}>
          <Input placeholder="general-arm64" />
        </Form.Item>
        <Row gutter={12}>
          <Col span={12}>
            <Form.Item name="runner_type" label="Runner 类型" rules={[{ required: true }]}>
              <Select options={runnerTypeOptions} />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="runtime" label="Runtime" rules={[{ required: true }]}>
              <Select options={runtimeOptions} />
            </Form.Item>
          </Col>
        </Row>
        <Form.Item name="network_zone" label="网络区" rules={[{ required: true }]}>
          <Input />
        </Form.Item>
        <Form.Item name="labels" label="必需标签（逗号分隔）">
          <Input placeholder="arm64, zone.cn" />
        </Form.Item>
        <Row gutter={12}>
          <Col span={8}>
            <Form.Item name="max_concurrency" label="最大并发">
              <InputNumber min={1} max={500} />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="lease_timeout_seconds" label="Lease 秒数">
              <InputNumber min={10} max={300} />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="heartbeat_timeout_seconds" label="心跳超时">
              <InputNumber min={15} max={600} />
            </Form.Item>
          </Col>
        </Row>
      </Form>
    </Modal>
  )
}

function RegistrationDialog({
  value,
  onClose,
}: {
  value: RegistrationToken | null
  onClose: () => void
}) {
  return (
    <Modal title="一次性 Runner 注册令牌" open={Boolean(value)} footer={null} onCancel={onClose}>
      <Alert
        showIcon
        type="warning"
        title="令牌只显示一次"
        description="将其写入目标 Runner 的 Secret；完成注册后数据库只保留 SHA-256 摘要。"
      />
      <Typography.Paragraph copyable code className="registration-token-value">
        {value?.token}
      </Typography.Paragraph>
      <Typography.Text type="secondary">
        过期时间：{value ? formatTime(value.expires_at) : '—'}
      </Typography.Text>
    </Modal>
  )
}

const runnerTypeOptions = ['general', 'data', 'protocol', 'performance', 'environment'].map(
  (value) => ({ value, label: runnerTypeLabel(value) }),
)
const emptyOverview: RunnerFabricOverview = {
  pools: 0,
  runners_online: 0,
  runners_offline: 0,
  runners_draining: 0,
  queued_tasks: 0,
  active_leases: 0,
  completed_tasks: 0,
  failed_tasks: 0,
}
const runtimeOptions = [
  { value: 'docker', label: 'Docker Compose' },
  { value: 'kubernetes', label: 'Kubernetes' },
]

function poolInput(value: PoolForm): FabricPoolInput {
  return {
    ...value,
    labels: value.labels
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean),
    capabilities: ['flow.workflow'],
  }
}

function RunnerStatus({ value }: { value: FabricRunner['status'] }) {
  const labels = { online: '在线', offline: '离线', draining: 'Drain', disabled: '停用' }
  const colors = { online: 'success', offline: 'default', draining: 'warning', disabled: 'error' }
  return <Tag color={colors[value]}>{labels[value]}</Tag>
}

function heartbeatLabel(value: string | null): string {
  if (!value) return '从未'
  const seconds = Math.max(0, Math.round((Date.now() - new Date(value).getTime()) / 1000))
  return `${seconds}s 前`
}

function runnerTypeLabel(value: string): string {
  return (
    {
      general: 'General',
      data: 'Data',
      protocol: 'Protocol',
      performance: 'Performance',
      environment: 'Environment',
    }[value] ?? value
  )
}

function shortId(value: string | null): string {
  return value ? value.slice(0, 8) : '—'
}

function formatTime(value: string): string {
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

function eventColor(value: string): string {
  if (value.includes('expired') || value.includes('failed')) return 'warning'
  if (value.includes('fenced') || value.includes('disabled')) return 'error'
  return 'success'
}

function eventLabel(value: string): string {
  if (value.includes('expired')) return '已回收'
  if (value.includes('fenced')) return '已拒绝'
  if (value.includes('acquired')) return '已接管'
  if (value.includes('completed')) return '唯一终态'
  return '有效'
}
