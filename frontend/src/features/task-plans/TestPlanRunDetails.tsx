import { useQuery } from '@tanstack/react-query'
import { Alert, Descriptions, Modal, Table, Tag } from 'antd'
import { Link } from 'react-router-dom'

import QueryFailureNotice from '../../components/QueryFailureNotice'
import type { TestPlanRun, TestPlanRunItem } from '../../lib/api'
import { reportExecutionPath, workflowExecutionPath } from '../workflows/execution-navigation'
import { getTestPlanRun } from './task-plan-service'

export default function TestPlanRunDetails({
  projectId,
  runId,
  onClose,
}: {
  projectId: string
  runId: string
  onClose: () => void
}) {
  const detail = useQuery({
    queryKey: ['test-plan-run-detail', projectId, runId],
    queryFn: () => getTestPlanRun(projectId, runId),
    refetchInterval: (query) =>
      ['queued', 'running'].includes(query.state.data?.run.status ?? '') ? 1000 : false,
  })
  const run = detail.data?.run
  return (
    <Modal open title="计划运行详情" width={1040} footer={null} onCancel={onClose}>
      <QueryFailureNotice queries={[detail]} />
      <RunSummary runId={runId} run={run} failed={detail.isError} />
      <Table<TestPlanRunItem>
        rowKey="id"
        size="small"
        loading={detail.isPending}
        dataSource={detail.data?.items ?? []}
        pagination={{ pageSize: 20 }}
        scroll={{ x: 940 }}
        columns={[
          { title: '顺序', dataIndex: 'position', render: (value: number) => value + 1 },
          {
            title: '冻结目标',
            render: (_, item) =>
              `${item.target_type} · ${item.target_id} · v${item.target_version}`,
          },
          {
            title: '流程版本',
            render: (_, item) => `${item.workflow_id} · v${item.workflow_version}`,
          },
          { title: '环境', dataIndex: 'environment_id' },
          { title: '状态', dataIndex: 'status', render: (status: string) => <Tag>{status}</Tag> },
          {
            title: '尝试／重试上限',
            render: (_, item) => `${item.attempts} 次尝试 · 最多 ${item.max_retries} 次重试`,
          },
          {
            title: '失败原因',
            dataIndex: 'error_message',
            render: (value: string | null) => value ?? '未提供',
          },
          {
            title: '证据',
            render: (_, item) => <RunEvidenceLinks projectId={projectId} item={item} />,
          },
        ]}
      />
    </Modal>
  )
}

function RunEvidenceLinks({ projectId, item }: { projectId: string; item: TestPlanRunItem }) {
  if (!item.workflow_execution_id) return '尚无执行报告'
  const location = { executionId: item.workflow_execution_id, workflowId: item.workflow_id }
  return (
    <>
      <Link to={reportExecutionPath(projectId, location)}>查看报告</Link> ·{' '}
      <Link to={workflowExecutionPath(projectId, location)}>定位编排</Link>
    </>
  )
}

function RunSummary({ runId, run, failed }: { runId: string; run?: TestPlanRun; failed: boolean }) {
  return (
    <>
      <Descriptions
        column={{ xs: 1, sm: 2 }}
        styles={{ content: { overflowWrap: 'anywhere' } }}
        items={[
          { key: 'id', label: '运行 ID', children: runId },
          {
            key: 'status',
            label: '状态',
            children: run?.status ?? (failed ? '读取失败' : '加载中'),
          },
          { key: 'plan', label: '计划 ID', children: run?.test_plan_id ?? '未提供' },
          { key: 'baseline', label: '基线运行', children: run?.baseline_run_id ?? '未设置' },
        ]}
      />
      {run?.error_message && <Alert type="error" title={run.error_message} />}
    </>
  )
}
