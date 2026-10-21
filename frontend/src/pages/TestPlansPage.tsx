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
  Modal,
  Popconfirm,
  Switch,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd'
import { useSearchParams } from 'react-router-dom'

import CreatePlanDialog from '../features/task-plans/CreatePlanDialog'
import EditTestPlanDialog from '../features/task-plans/EditTestPlanDialog'
import TestPlanRunDetails from '../features/task-plans/TestPlanRunDetails'
import { useTestPlans } from '../features/task-plans/use-test-plans'
import { useProjectContext } from '../features/projects/use-project-context'
import { apiErrorMessage, type TestPlan, type TestPlanRun } from '../lib/api'

export default function TestPlansPage() {
  const { projectId } = useProjectContext()
  return <TaskPlanWorkspace key={projectId ?? 'none'} />
}

function TaskPlanWorkspace() {
  const [searchParams] = useSearchParams()
  const state = useTestPlans()

  return (
    <>
      <TaskHeading state={state} />
      <TaskErrorAlert state={state} />
      <TaskWorkspace state={state} focusedId={searchParams.get('focus') ?? undefined} />
      <TokenCard state={state} />
      <TaskDialogs state={state} />
    </>
  )
}

type TaskState = ReturnType<typeof useTestPlans>

function TaskErrorAlert({ state }: { state: TaskState }) {
  const queries = [
    state.permissions,
    state.plans,
    state.runs,
    state.tokens,
    state.workflows,
    state.testCases,
    state.testSuites,
    state.environments,
  ]
  const error = queries.find((query) => query.isError)?.error
  if (!error) return null
  return (
    <Alert
      type="error"
      showIcon
      title="任务工作区加载失败"
      description={apiErrorMessage(error)}
      action={
        <Button
          onClick={() => {
            queries.filter((query) => query.isError).forEach((query) => void query.refetch())
          }}
        >
          重试
        </Button>
      }
    />
  )
}

function TaskHeading({ state }: { state: TaskState }) {
  const cannotCreate = !state.canEdit || !state.projectId
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
          disabled={!state.canManageTokens}
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

function TaskWorkspace({ state, focusedId }: { state: TaskState; focusedId?: string }) {
  return (
    <div className="task-plan-grid">
      <Card title="测试计划" loading={state.plans.isLoading}>
        <PlanTable
          items={state.plans.data?.items ?? []}
          focusedId={focusedId}
          readOnly={!state.canEdit}
          page={state.planPage}
          total={state.plans.data?.total ?? 0}
          onPageChange={state.setPlanPage}
          onRun={state.execute}
          onEdit={state.setEditingPlan}
          onToggle={state.togglePlan}
          updating={state.updatingPlan}
        />
      </Card>
      <Card title="运行队列" loading={state.runs.isLoading}>
        <RunTable
          page={state.runPage}
          total={state.runs.data?.total ?? 0}
          onPageChange={state.setRunPage}
          items={state.runs.data?.items ?? []}
          readOnly={!state.canEdit}
          onCancel={state.cancel}
          onView={state.setSelectedRunId}
        />
      </Card>
    </div>
  )
}

function TokenCard({ state }: { state: TaskState }) {
  if (!state.canManageTokens) return null
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
          { title: '状态', render: (_, token) => (token.revoked_at ? '已撤销' : '有效') },
          {
            title: '操作',
            render: (_, token) => (
              <Popconfirm
                title="撤销 CI Token？"
                description="使用此凭据的 CI 将失去执行权限。"
                okText="撤销"
                cancelText="取消"
                onConfirm={() => state.revoke(token.id)}
              >
                <Button
                  danger
                  size="small"
                  disabled={Boolean(token.revoked_at) || state.revokingToken}
                >
                  撤销
                </Button>
              </Popconfirm>
            ),
          },
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
      <TaskMaintenanceDialogs state={state} />
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

function PlanTable({
  items,
  focusedId,
  readOnly,
  page,
  total,
  onPageChange,
  onRun,
  onEdit,
  onToggle,
  updating,
}: {
  items: TestPlan[]
  focusedId?: string
  readOnly: boolean
  page: number
  total: number
  onPageChange: (page: number) => void
  onRun: (id: string) => void
  onEdit: (plan: TestPlan) => void
  onToggle: (plan: TestPlan) => Promise<void>
  updating: boolean
}) {
  return (
    <Table
      rowKey="id"
      size="small"
      pagination={{
        current: page,
        pageSize: 20,
        total,
        showSizeChanger: false,
        onChange: onPageChange,
      }}
      dataSource={items}
      rowClassName={(item) => (item.id === focusedId ? 'selected-row' : '')}
      locale={{ emptyText: '暂无测试计划' }}
      columns={[
        { title: '名称', dataIndex: 'name' },
        {
          title: '启用',
          render: (_, plan: TestPlan) => (
            <Switch
              aria-label={`启停计划 ${plan.name}`}
              checked={plan.enabled}
              loading={updating}
              disabled={readOnly}
              onChange={() => void onToggle(plan)}
            />
          ),
        },
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
          width: 150,
          render: (_, plan: TestPlan) => (
            <Space>
              <Button type="link" disabled={readOnly || updating} onClick={() => onEdit(plan)}>
                编辑
              </Button>
              <Button
                type="link"
                disabled={readOnly}
                icon={<PlayCircleOutlined />}
                onClick={() => onRun(plan.id)}
              >
                运行
              </Button>
            </Space>
          ),
        },
      ]}
    />
  )
}

function RunTable({
  items,
  readOnly,
  page,
  total,
  onPageChange,
  onCancel,
  onView,
}: {
  items: TestPlanRun[]
  readOnly: boolean
  page: number
  total: number
  onPageChange: (page: number) => void
  onCancel: (id: string) => void
  onView: (id: string) => void
}) {
  return (
    <Table
      rowKey="id"
      size="small"
      pagination={{
        current: page,
        pageSize: 20,
        total,
        showSizeChanger: false,
        onChange: onPageChange,
      }}
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
          render: (_, run: TestPlanRun) => (
            <Space>
              <Button type="link" onClick={() => onView(run.id)}>
                详情
              </Button>
              {['queued', 'running'].includes(run.status) && (
                <Button
                  type="link"
                  danger
                  disabled={readOnly}
                  icon={<StopOutlined />}
                  onClick={() => onCancel(run.id)}
                >
                  取消
                </Button>
              )}
            </Space>
          ),
        },
      ]}
    />
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

function localTime(value: string): string {
  return new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })
}

function TaskMaintenanceDialogs({ state }: { state: TaskState }) {
  return (
    <>
      {state.editingPlan && (
        <EditTestPlanDialog
          key={state.editingPlan.id}
          plan={state.editingPlan}
          saving={state.updatingPlan}
          onClose={() => state.setEditingPlan(null)}
          onSave={state.editPlan}
        />
      )}
      {state.projectId && state.selectedRunId && (
        <TestPlanRunDetails
          key={state.selectedRunId}
          projectId={state.projectId}
          runId={state.selectedRunId}
          onClose={() => state.setSelectedRunId(null)}
        />
      )}
    </>
  )
}
