import { Alert, Button, InputNumber, Modal, Segmented, Space, Table, Typography } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import type { ExecutionCheckpointSummary } from '../../lib/api'
import { getWorkflowCheckpointLogEntry, listWorkflowCheckpointLog } from './workflow-service'
import { WorkflowCheckpointEvidence } from '../../flow/WorkflowRunInspector'

const PAGE_SIZE = 20

type Props = {
  projectId: string
  executionId: string
  running: boolean
  nodeId?: string
}

export default function ExecutionCheckpointLog({ projectId, executionId, running, nodeId }: Props) {
  const {
    page,
    setPage,
    selectedId,
    setSelectedId,
    scope,
    setScope,
    attempt,
    setAttempt,
    filterNodeId,
    log,
    detail,
  } = useCheckpointLog(projectId, executionId, nodeId)

  return (
    <section aria-label="执行记录">
      <Space wrap>
        <Typography.Text strong>执行记录</Typography.Text>
        <Typography.Text type="secondary">
          按 checkpoint 完成时间排序，包含重试和区域实例
        </Typography.Text>
        <Button size="small" onClick={() => void log.refetch()}>
          刷新记录
        </Button>
      </Space>
      <CheckpointLogFilters
        nodeId={nodeId}
        scope={scope}
        attempt={attempt}
        filterNodeId={filterNodeId}
        onScope={(value) => {
          setScope(value)
          setPage(1)
          setSelectedId(null)
        }}
        onAttempt={(value) => {
          setAttempt(value)
          setPage(1)
          setSelectedId(null)
        }}
      />
      {running && <Alert type="info" title="运行仍在进行，记录数量可能继续增加" />}
      {log.isError && <Alert type="error" title="执行记录加载失败，请重试" />}
      <Table<ExecutionCheckpointSummary>
        rowKey="id"
        size="small"
        loading={log.isPending}
        dataSource={log.data?.items ?? []}
        locale={{ emptyText: checkpointLogEmptyText(filterNodeId) }}
        pagination={{
          current: page,
          pageSize: PAGE_SIZE,
          total: log.data?.total ?? 0,
          showSizeChanger: false,
          onChange: setPage,
        }}
        columns={[
          { title: '完成时间', dataIndex: 'finished_at', render: (value: string) => value },
          { title: '节点', dataIndex: 'node_name' },
          { title: '阶段', dataIndex: 'phase' },
          { title: '尝试', dataIndex: 'attempt' },
          { title: '状态', dataIndex: 'status' },
          {
            title: '详情',
            render: (_value: unknown, item: ExecutionCheckpointSummary) => (
              <Button size="small" type="link" onClick={() => setSelectedId(item.id)}>
                查看记录
              </Button>
            ),
          },
        ]}
      />
      <Modal
        title="执行记录详情"
        open={selectedId !== null}
        footer={null}
        onCancel={() => setSelectedId(null)}
        width={800}
      >
        {detail.isPending && <Typography.Text>加载中…</Typography.Text>}
        {detail.isError && <Alert type="error" title="记录详情加载失败，请重试" />}
        {detail.data && (
          <>
            <Typography.Paragraph>
              {detail.data.node_name} · 第 {detail.data.attempt} 次尝试 · {detail.data.status}
            </Typography.Paragraph>
            <WorkflowCheckpointEvidence checkpoint={detail.data} projectId={projectId} />
          </>
        )}
      </Modal>
    </section>
  )
}

function useCheckpointLog(projectId: string, executionId: string, nodeId?: string) {
  const [page, setPage] = useState(1)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [scope, setScope] = useState<'node' | 'all'>(nodeId ? 'node' : 'all')
  const [attempt, setAttempt] = useState<number | null>(null)
  const filterNodeId = scope === 'node' ? nodeId : undefined
  const log = useQuery({
    queryKey: ['workflow-checkpoint-log', projectId, executionId, filterNodeId, attempt, page],
    queryFn: () =>
      listWorkflowCheckpointLog(projectId, executionId, page, {
        nodeId: filterNodeId,
        attempt: attempt ?? undefined,
      }),
  })
  const detail = useQuery({
    queryKey: ['workflow-checkpoint-log-entry', projectId, executionId, selectedId],
    queryFn: () => getWorkflowCheckpointLogEntry(projectId, executionId, selectedId!),
    enabled: selectedId !== null,
  })

  return {
    page,
    setPage,
    selectedId,
    setSelectedId,
    scope,
    setScope,
    attempt,
    setAttempt,
    filterNodeId,
    log,
    detail,
  }
}

function checkpointLogEmptyText(nodeId: string | undefined): string {
  return nodeId ? '当前节点与尝试没有匹配记录，可切换全部执行查看旧记录' : '暂无执行记录'
}

function CheckpointLogFilters({
  nodeId,
  scope,
  attempt,
  filterNodeId,
  onScope,
  onAttempt,
}: {
  nodeId?: string
  scope: 'node' | 'all'
  attempt: number | null
  filterNodeId?: string
  onScope: (value: 'node' | 'all') => void
  onAttempt: (value: number | null) => void
}) {
  return (
    <Space wrap>
      {nodeId && (
        <Segmented
          value={scope}
          options={[
            { label: '当前节点', value: 'node' },
            { label: '全部执行', value: 'all' },
          ]}
          onChange={onScope}
        />
      )}
      <InputNumber
        aria-label="检查点尝试筛选"
        min={1}
        precision={0}
        placeholder="全部检查点尝试"
        value={attempt}
        onChange={onAttempt}
      />
      <Typography.Text type="secondary">
        {filterNodeId ? `节点：${filterNodeId}` : '范围：全部执行'} · 检查点尝试与 HTTP
        请求重试分别记录
      </Typography.Text>
    </Space>
  )
}
