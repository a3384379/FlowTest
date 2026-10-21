import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Descriptions, Drawer, Pagination, Space, Table, Typography } from 'antd'
import { useState } from 'react'
import type { UseQueryResult } from '@tanstack/react-query'
import type { Page } from '../../lib/api'
import { useFabricPolling } from './use-fabric-polling'

import QueryFailureNotice from '../../components/QueryFailureNotice'
import { reportExecutionPath, workflowExecutionPath } from '../workflows/execution-navigation'
import {
  getFabricPool,
  getFabricRunner,
  getFabricTask,
  listFabricEvents,
  listFabricLeases,
  type FabricLease,
  type FabricEvent,
  type FabricTask,
} from './execution-fabric-service'

export function FabricTaskTable({
  items,
  onSelect,
}: {
  items: FabricTask[]
  onSelect: (id: string) => void
}) {
  return (
    <Table
      rowKey="id"
      size="small"
      dataSource={items}
      pagination={false}
      locale={{ emptyText: '此页没有任务记录' }}
      columns={[
        {
          title: '任务',
          render: (_, task) => (
            <Button type="link" onClick={() => onSelect(task.id)}>
              {task.id}
            </Button>
          ),
        },
        { title: '类型', dataIndex: 'required_runner_type' },
        { title: '状态', dataIndex: 'status' },
        { title: '尝试次数', render: (_, task) => `${task.attempts} / ${task.max_attempts}` },
        { title: '创建时间', dataIndex: 'created_at', render: time },
      ]}
    />
  )
}

export default function FabricInspection({
  scope,
  taskId,
  poolId,
  runnerId,
  onClose,
}: {
  scope: string
  taskId: string | null
  poolId: string | null
  runnerId: string | null
  onClose: () => void
}) {
  if (taskId)
    return (
      <TaskInspection key={`${scope}:${taskId}`} scope={scope} taskId={taskId} onClose={onClose} />
    )
  if (poolId || runnerId)
    return (
      <WorkerInspection
        key={`${scope}:${poolId}:${runnerId}`}
        scope={scope}
        poolId={poolId}
        runnerId={runnerId}
        onClose={onClose}
      />
    )
  return null
}

function TaskInspection({
  scope,
  taskId,
  onClose,
}: {
  scope: string
  taskId: string
  onClose: () => void
}) {
  const [leasePage, setLeasePage] = useState(1)
  const [eventPage, setEventPage] = useState(1)
  const polling = useFabricPolling()
  const task = useQuery({
    queryKey: ['runner-fabric', scope, 'task', taskId],
    queryFn: () => getFabricTask(taskId),
    ...polling,
  })
  const leases = useQuery({
    queryKey: ['runner-fabric', scope, 'task-leases', taskId, leasePage],
    queryFn: () => listFabricLeases(leasePage, taskId),
    enabled: task.isSuccess,
    ...polling,
  })
  const events = useQuery({
    queryKey: ['runner-fabric', scope, 'task-events', taskId, eventPage],
    queryFn: () => listFabricEvents(eventPage, taskId),
    enabled: task.isSuccess,
    ...polling,
  })
  return (
    <Drawer title="任务与 Lease 只读证据" open onClose={onClose} size="min(1000px, 100vw)">
      <QueryFailureNotice queries={[task, leases, events]} />
      <StaleInspectionNotice reads={[task, leases, events]} />
      {task.isError && task.data && (
        <Alert type="warning" title="任务刷新失败，以下为上次成功读取的证据" />
      )}
      {task.isPending && <Typography.Text>正在读取任务</Typography.Text>}
      {task.data && (
        <>
          <TaskDetails task={task.data} />
          <TaskLeaseHistory
            query={leases}
            task={task.data}
            fresh={!task.isError}
            page={leasePage}
            onPage={setLeasePage}
          />
          <TaskEventHistory query={events} page={eventPage} onPage={setEventPage} />
        </>
      )}
    </Drawer>
  )
}

function TaskLeaseHistory({
  query,
  task,
  page,
  onPage,
  fresh,
}: {
  query: UseQueryResult<Page<FabricLease>>
  fresh: boolean
  task: FabricTask
  page: number
  onPage: (page: number) => void
}) {
  return (
    <>
      {' '}
      <Typography.Title level={5}>Lease 历史（当前任务）</Typography.Title>
      <Table
        rowKey="id"
        dataSource={query.data?.items ?? []}
        loading={query.isPending}
        size="small"
        pagination={false}
        columns={[
          { title: 'Lease', dataIndex: 'id' },
          {
            title: 'Runner',
            dataIndex: 'runner_id',
            render: (id: string) => (
              <Typography.Link href={`/execution-fabric?runner=${encodeURIComponent(id)}`}>
                {id}
              </Typography.Link>
            ),
          },
          { title: 'Fence', dataIndex: 'fencing_token' },
          {
            title: '有效性',
            render: (_, lease) => leaseValidity(lease, task, fresh && !query.isError),
          },
          { title: '记录状态', dataIndex: 'status' },
          { title: '取得时间', dataIndex: 'acquired_at', render: time },
          { title: '过期时间', dataIndex: 'expires_at', render: time },
          { title: '最近续租', dataIndex: 'last_renewed_at', render: time },
        ]}
      />
      <Pagination
        current={page}
        pageSize={20}
        total={query.data?.total ?? 0}
        showSizeChanger={false}
        onChange={onPage}
      />
    </>
  )
}

function TaskEventHistory({
  query,
  page,
  onPage,
}: {
  query: UseQueryResult<Page<FabricEvent>>
  page: number
  onPage: (page: number) => void
}) {
  return (
    <>
      {' '}
      <Typography.Title level={5}>关联事件（当前任务）</Typography.Title>
      <Table
        rowKey="id"
        size="small"
        dataSource={query.data?.items ?? []}
        loading={query.isPending}
        pagination={false}
        columns={[
          { title: '时间', dataIndex: 'created_at', render: time },
          { title: '事件', dataIndex: 'message' },
          { title: 'Lease', dataIndex: 'lease_id' },
          {
            title: 'Fence',
            render: (_, event) => String(event.details.fencing_token ?? '未提供'),
          },
        ]}
      />
      <Pagination
        current={page}
        pageSize={20}
        total={query.data?.total ?? 0}
        showSizeChanger={false}
        onChange={onPage}
      />
    </>
  )
}

function TaskDetails({ task }: { task: FabricTask }) {
  return (
    <Space orientation="vertical" className="full-width">
      <Descriptions
        column={1}
        items={[
          { label: '任务 ID', children: task.id },
          { label: '项目', children: task.project_id },
          { label: '执行 ID', children: task.execution_id },
          { label: '状态', children: task.status },
          { label: 'Runner', children: task.selected_runner_id ?? '尚未分配' },
          { label: '最近 Lease', children: task.last_lease_id ?? '无' },
          { label: '当前 Fence', children: task.fencing_token },
          { label: '尝试次数', children: `${task.attempts} / ${task.max_attempts}` },
          { label: '优先级', children: task.priority },
          { label: '最早可执行', children: time(task.available_at) },
          { label: '完成时间', children: time(task.completed_at) },
          { label: '必需标签', children: task.required_labels.join('、') || '无' },
          { label: '必需能力', children: task.required_capabilities.join('、') || '无' },
          { label: '错误代码', children: task.error_code ?? '未提供' },
          { label: '错误说明', children: task.error_message ?? '未提供' },
        ]}
      />
      <Space>
        <Typography.Link
          href={workflowExecutionPath(task.project_id, { executionId: task.execution_id })}
        >
          查看工作流执行
        </Typography.Link>
        <Typography.Link
          href={reportExecutionPath(task.project_id, { executionId: task.execution_id })}
        >
          查看执行报告
        </Typography.Link>
      </Space>
    </Space>
  )
}

function WorkerInspection({
  scope,
  poolId,
  runnerId,
  onClose,
}: {
  scope: string
  poolId: string | null
  runnerId: string | null
  onClose: () => void
}) {
  const polling = useFabricPolling()
  const runner = useQuery({
    queryKey: ['runner-fabric', scope, 'runner', runnerId],
    queryFn: () => getFabricRunner(runnerId!),
    enabled: Boolean(runnerId),
    ...polling,
  })
  const effectivePool = poolId ?? runner.data?.pool_id
  const pool = useQuery({
    queryKey: ['runner-fabric', scope, 'pool', effectivePool],
    queryFn: () => getFabricPool(effectivePool!),
    enabled: Boolean(effectivePool),
    ...polling,
  })
  return (
    <Drawer title="Pool / Runner 只读详情" open onClose={onClose}>
      <QueryFailureNotice queries={[pool, runner]} />
      <StaleInspectionNotice reads={[pool, runner]} />
      {pool.data && (
        <Descriptions
          column={1}
          items={[
            { label: 'Pool', children: pool.data.name },
            { label: 'Pool ID', children: pool.data.id },
            { label: '网络区', children: pool.data.network_zone },
            { label: '运行时', children: pool.data.runtime },
            { label: '状态', children: pool.data.enabled ? '启用' : '停用' },
            { label: '能力', children: pool.data.capabilities.join('、') || '未提供' },
            {
              label: 'Runner',
              children: pool.data.runners.map((item) => item.name).join('、') || '无',
            },
          ]}
        />
      )}
      {runner.data && (
        <Descriptions
          column={1}
          items={[
            { label: '选中 Runner', children: runner.data.name },
            { label: 'Runner ID', children: runner.data.id },
            { label: '状态', children: runner.data.status },
            { label: '心跳', children: time(runner.data.last_seen_at) },
            {
              label: '当前负载 / 上限',
              children: `${runner.data.current_load} / ${runner.data.max_concurrency}`,
            },
          ]}
        />
      )}
    </Drawer>
  )
}

function leaseValidity(lease: FabricLease, task: FabricTask, fresh: boolean): string {
  if (!fresh) return '有效性待刷新核对'
  if (lease.status !== 'active') return '历史 Lease'
  if (new Date(lease.expires_at).getTime() <= Date.now()) return '已过期，等待回收'
  if (
    task.status !== 'leased' ||
    task.last_lease_id !== lease.id ||
    task.fencing_token !== lease.fencing_token
  )
    return '已失效 Fence'
  return '当前有效 Lease'
}

function time(value: string | null): string {
  return value ? new Date(value).toLocaleString() : '未提供'
}

function StaleInspectionNotice({ reads }: { reads: { isError: boolean; data: unknown }[] }) {
  if (!reads.some((query) => query.isError && query.data !== undefined)) return null
  return <Alert type="warning" title="部分详情刷新失败，保留的 Lease、事件或 Worker 数据可能过期" />
}
