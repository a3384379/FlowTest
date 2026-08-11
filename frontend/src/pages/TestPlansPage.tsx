import {
  ClockCircleOutlined,
  KeyOutlined,
  PlayCircleOutlined,
  PlusOutlined,
  StopOutlined,
} from '@ant-design/icons'
import {
  Alert,
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd'

import type { CreateTestPlanInput } from '../features/task-plans/task-plan-service'
import type { TestPlanTargetType } from '../features/task-plans/task-plan-service'
import { useTestPlans } from '../features/task-plans/use-test-plans'
import type { TestPlan, TestPlanRun } from '../lib/api'

export default function TestPlansPage() {
  const state = useTestPlans()

  return (
    <>
      <TaskHeading state={state} />
      <TaskWorkspace state={state} />
      <TokenCard state={state} />
      <TaskDialogs state={state} />
    </>
  )
}

type TaskState = ReturnType<typeof useTestPlans>

function TaskHeading({ state }: { state: TaskState }) {
  const cannotCreate =
    !state.projectId ||
    (!state.workflows.data?.items.length &&
      !state.testCases.data?.items.some(isPublished) &&
      !state.testSuites.data?.items.some(isPublished))
  return (
    <div className="page-heading">
      <div>
        <Typography.Title level={2}>任务执行</Typography.Title>
        <Typography.Text type="secondary">
          通过 Worker 批量运行工作流，并支持定时、CI Token、签名 Webhook 和取消。
        </Typography.Text>
      </div>
      <Space wrap>
        <Select
          aria-label="任务项目"
          className="context-select"
          placeholder="选择项目"
          value={state.projectId}
          options={options(state.projects.data?.items)}
          onChange={state.setProjectSelection}
        />
        <Button
          icon={<KeyOutlined />}
          disabled={!state.projectId}
          onClick={() => void state.issueToken()}
        >
          生成 CI Token
        </Button>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          disabled={cannotCreate}
          onClick={() => state.setCreateOpen(true)}
        >
          新建计划
        </Button>
      </Space>
    </div>
  )
}

function TaskWorkspace({ state }: { state: TaskState }) {
  return (
    <div className="task-plan-grid">
      <Card title="测试计划" loading={state.plans.isLoading}>
        <PlanTable items={state.plans.data?.items ?? []} onRun={state.execute} />
      </Card>
      <Card title="运行队列" loading={state.runs.isLoading}>
        <RunTable items={state.runs.data?.items ?? []} onCancel={state.cancel} />
      </Card>
    </div>
  )
}

function TokenCard({ state }: { state: TaskState }) {
  return (
    <Card title="CI 凭据" className="workflow-result-card">
      <Table
        rowKey="id"
        size="small"
        pagination={false}
        dataSource={state.tokens.data ?? []}
        locale={{ emptyText: '暂无 CI Token' }}
        columns={[
          { title: '名称', dataIndex: 'name' },
          { title: '前缀', dataIndex: 'token_prefix', width: 140 },
          {
            title: '权限范围',
            dataIndex: 'scopes',
            render: (values: string[]) => values.map((value) => <Tag key={value}>{value}</Tag>),
          },
          {
            title: '最后使用',
            dataIndex: 'last_used_at',
            render: (value: string | null) => (value ? localTime(value) : '尚未使用'),
          },
        ]}
      />
    </Card>
  )
}

function TaskDialogs({ state }: { state: TaskState }) {
  return (
    <>
      <CreatePlanDialog
        open={state.createOpen}
        workflows={state.workflows.data?.items ?? []}
        environments={state.environments.data ?? []}
        testCases={state.testCases.data?.items.filter(isPublished) ?? []}
        testSuites={state.testSuites.data?.items.filter(isPublished) ?? []}
        submitting={state.creating}
        onClose={() => state.setCreateOpen(false)}
        onCreate={state.addPlan}
      />
      <Modal
        title={state.revealedSecret?.title}
        open={Boolean(state.revealedSecret)}
        width={680}
        footer={null}
        onCancel={state.dismissSecret}
      >
        {state.revealedSecret && <SecretValue value={state.revealedSecret.value} />}
      </Modal>
    </>
  )
}

function PlanTable({ items, onRun }: { items: TestPlan[]; onRun: (id: string) => void }) {
  return (
    <Table
      rowKey="id"
      size="small"
      pagination={false}
      dataSource={items}
      locale={{ emptyText: '暂无测试计划' }}
      columns={[
        { title: '名称', dataIndex: 'name' },
        {
          title: '执行项',
          dataIndex: 'items',
          width: 90,
          render: (value: unknown[]) => value.length,
        },
        {
          title: '调度',
          dataIndex: 'schedule_interval_seconds',
          render: (value: number | null, plan: TestPlan) =>
            plan.schedule_cron ? (
              <Tag icon={<ClockCircleOutlined />} color="purple">
                {plan.schedule_cron} · {plan.schedule_timezone}
              </Tag>
            ) : value ? (
              <Tag icon={<ClockCircleOutlined />} color="blue">
                每 {value / 60} 分钟
              </Tag>
            ) : (
              '手动'
            ),
        },
        {
          title: '优先级',
          dataIndex: 'queue_priority',
          width: 80,
        },
        {
          title: '操作',
          width: 90,
          render: (_, plan: TestPlan) => (
            <Button type="link" icon={<PlayCircleOutlined />} onClick={() => onRun(plan.id)}>
              运行
            </Button>
          ),
        },
      ]}
    />
  )
}

function RunTable({ items, onCancel }: { items: TestPlanRun[]; onCancel: (id: string) => void }) {
  return (
    <Table
      rowKey="id"
      size="small"
      pagination={false}
      dataSource={items}
      locale={{ emptyText: '暂无计划运行' }}
      columns={[
        { title: '触发', dataIndex: 'trigger_type', width: 90 },
        { title: '队列', dataIndex: 'queue_name', width: 90 },
        {
          title: '状态',
          dataIndex: 'status',
          width: 100,
          render: (value: string) => <StatusTag status={value} />,
        },
        {
          title: '入队时间',
          dataIndex: 'created_at',
          render: (value: string) => localTime(value),
        },
        {
          title: '操作',
          width: 90,
          render: (_, run: TestPlanRun) =>
            ['queued', 'running'].includes(run.status) ? (
              <Button type="link" danger icon={<StopOutlined />} onClick={() => onCancel(run.id)}>
                取消
              </Button>
            ) : null,
        },
      ]}
    />
  )
}

function CreatePlanDialog({
  open,
  workflows,
  environments,
  testCases,
  testSuites,
  submitting,
  onClose,
  onCreate,
}: {
  open: boolean
  workflows: Array<{ id: string; name: string }>
  environments: Array<{ id: string; name: string }>
  testCases: Array<{ id: string; name: string }>
  testSuites: Array<{ id: string; name: string }>
  submitting: boolean
  onClose: () => void
  onCreate: (input: CreateTestPlanInput) => Promise<void>
}) {
  type PlanForm = Omit<
    CreateTestPlanInput,
    'intervalSeconds' | 'environmentId' | 'cronExpression'
  > & {
    environmentId?: string
    scheduleMode: 'manual' | 'interval' | 'cron'
    intervalMinutes: number | null
    cronExpression?: string
  }
  const [form] = Form.useForm<PlanForm>()
  const targetType = Form.useWatch('targetType', form) ?? 'workflow'
  const scheduleMode = Form.useWatch('scheduleMode', form) ?? 'manual'
  const targetOptions = selectTargetOptions(targetType, workflows, testCases, testSuites)
  return (
    <Modal
      title="新建测试计划"
      open={open}
      confirmLoading={submitting}
      onCancel={onClose}
      onOk={() => form.submit()}
      destroyOnHidden
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={{
          targetType: 'workflow',
          maxRetries: 0,
          scheduleMode: 'manual',
          intervalMinutes: null,
          timezone: 'Asia/Shanghai',
          priority: 5,
        }}
        onFinish={(values) =>
          void onCreate({
            ...values,
            environmentId: values.environmentId ?? null,
            intervalSeconds:
              values.scheduleMode === 'interval' && values.intervalMinutes
                ? values.intervalMinutes * 60
                : null,
            cronExpression: values.scheduleMode === 'cron' ? (values.cronExpression ?? null) : null,
          })
        }
      >
        <Form.Item name="name" label="计划名称" rules={[{ required: true }]}>
          <Input maxLength={200} />
        </Form.Item>
        <Form.Item name="targetType" label="资产类型" rules={[{ required: true }]}>
          <Select
            options={[
              { value: 'workflow', label: '工作流' },
              { value: 'case', label: '测试用例' },
              { value: 'suite', label: '测试套件' },
            ]}
            onChange={() => {
              form.setFieldValue('targetId', undefined)
              form.setFieldValue('environmentId', undefined)
            }}
          />
        </Form.Item>
        <Form.Item name="targetId" label={targetLabel(targetType)} rules={[{ required: true }]}>
          <Select options={targetOptions} />
        </Form.Item>
        {targetType === 'workflow' && (
          <Form.Item name="environmentId" label="环境" rules={[{ required: true }]}>
            <Select options={options(environments)} />
          </Form.Item>
        )}
        <Form.Item name="scheduleMode" label="调度方式">
          <Select
            options={[
              { value: 'manual', label: '手动' },
              { value: 'interval', label: '固定间隔' },
              { value: 'cron', label: 'Cron' },
            ]}
          />
        </Form.Item>
        {scheduleMode === 'interval' && (
          <Form.Item name="intervalMinutes" label="定时间隔（分钟）" rules={[{ required: true }]}>
            <InputNumber min={1} max={43_200} precision={0} className="full-width" />
          </Form.Item>
        )}
        {scheduleMode === 'cron' && (
          <>
            <Form.Item name="cronExpression" label="Cron 表达式" rules={[{ required: true }]}>
              <Input placeholder="0 9 * * 1-5" maxLength={120} />
            </Form.Item>
            <Form.Item name="timezone" label="时区" rules={[{ required: true }]}>
              <Select
                options={[
                  { value: 'Asia/Shanghai', label: 'Asia/Shanghai' },
                  { value: 'UTC', label: 'UTC' },
                  { value: 'Asia/Tokyo', label: 'Asia/Tokyo' },
                ]}
              />
            </Form.Item>
          </>
        )}
        <Form.Item name="priority" label="队列优先级（0 最低，9 最高）">
          <InputNumber min={0} max={9} precision={0} className="full-width" />
        </Form.Item>
        <Form.Item name="maxRetries" label="失败重试次数">
          <InputNumber min={0} max={3} precision={0} className="full-width" />
        </Form.Item>
      </Form>
    </Modal>
  )
}

function SecretValue({ value }: { value: string }) {
  return (
    <Space orientation="vertical" className="full-width">
      <Alert type="warning" showIcon title="关闭后无法再次查看，请立即保存到安全的凭据库。" />
      <Typography.Paragraph copyable code className="secret-output">
        {value}
      </Typography.Paragraph>
    </Space>
  )
}

function StatusTag({ status }: { status: string }) {
  const colors: Record<string, string> = {
    queued: 'default',
    running: 'processing',
    passed: 'success',
    failed: 'error',
    cancelled: 'warning',
  }
  return <Tag color={colors[status]}>{status}</Tag>
}

function options(items?: Array<{ id: string; name: string }>) {
  return items?.map((item) => ({ value: item.id, label: item.name }))
}

function isPublished(item: { current_version: number | null }) {
  return item.current_version !== null
}

function targetLabel(targetType: TestPlanTargetType) {
  const labels: Record<TestPlanTargetType, string> = {
    workflow: '工作流',
    case: '测试用例',
    suite: '测试套件',
  }
  return labels[targetType]
}

function selectTargetOptions(
  targetType: TestPlanTargetType,
  workflows: Array<{ id: string; name: string }>,
  testCases: Array<{ id: string; name: string }>,
  testSuites: Array<{ id: string; name: string }>,
) {
  const targets = { workflow: workflows, case: testCases, suite: testSuites }
  return options(targets[targetType])
}

function localTime(value: string): string {
  return new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })
}
