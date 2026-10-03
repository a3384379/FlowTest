import { Alert, Button, Modal, Space, Table, Typography } from 'antd'
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
}

export default function ExecutionCheckpointLog({ projectId, executionId, running }: Props) {
  const [page, setPage] = useState(1)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const log = useQuery({
    queryKey: ['workflow-checkpoint-log', projectId, executionId, page],
    queryFn: () => listWorkflowCheckpointLog(projectId, executionId, page),
  })
  const detail = useQuery({
    queryKey: ['workflow-checkpoint-log-entry', projectId, executionId, selectedId],
    queryFn: () => getWorkflowCheckpointLogEntry(projectId, executionId, selectedId!),
    enabled: selectedId !== null,
  })

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
      {running && <Alert type="info" title="运行仍在进行，记录数量可能继续增加" />}
      {log.isError && <Alert type="error" title="执行记录加载失败，请重试" />}
      <Table<ExecutionCheckpointSummary>
        rowKey="id"
        size="small"
        loading={log.isPending}
        dataSource={log.data?.items ?? []}
        locale={{ emptyText: '暂无执行记录' }}
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
