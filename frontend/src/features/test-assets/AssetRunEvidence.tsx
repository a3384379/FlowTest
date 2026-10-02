import { Alert, Button, Empty, Space, Table, Tag, Typography } from 'antd'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { apiErrorMessage, type TestCase } from '../../lib/api'
import { projectPath } from '../projects/project-routing'
import { reportExecutionPath, workflowExecutionPath } from '../workflows/execution-navigation'
import { assetRunLabels, reportItem, type AssetRunEntry } from './asset-run-view-model'
import type { AssetKind, AssetRunItem } from './asset-workspace-service'
import type { useAssetHistory } from './use-asset-history'
import { listLatestTestCaseRuns } from './test-asset-service'

export function AssetResultTag({ status }: { status: AssetRunItem['status'] }) {
  const colors: Partial<Record<AssetRunItem['status'], string>> = {
    passed: 'success',
    failed: 'error',
    running: 'processing',
    queued: 'warning',
  }
  return <Tag color={colors[status]}>{assetRunLabels[status]}</Tag>
}

export function AssetRecentResult({
  projectId,
  entry,
}: {
  projectId: string
  entry?: AssetRunEntry
}) {
  if (!entry) return <Typography.Text type="secondary">此范围无记录</Typography.Text>
  const item = reportItem(entry)
  return (
    <Space size={4} wrap>
      <AssetResultTag status={entry.status} />
      <Typography.Text type="secondary">
        {entry.versions.map((version) => `v${version}`).join(' / ')}
      </Typography.Text>
      {item?.workflow_execution_id && (
        <Link to={reportExecutionPath(projectId, { executionId: item.workflow_execution_id })}>
          报告 →
        </Link>
      )}
    </Space>
  )
}

export function AssetHistoryNotice({ history }: { history: ReturnType<typeof useAssetHistory> }) {
  if (history.error)
    return (
      <Alert
        type="warning"
        showIcon
        title="近期执行结果未完整加载"
        description={apiErrorMessage(history.error)}
        action={
          <Button size="small" onClick={() => void history.reload()}>
            重新加载
          </Button>
        }
      />
    )
  return (
    <Typography.Paragraph type="secondary" className="asset-loaded-scope">
      执行结果范围：最近 {history.count} 次计划运行 / 全部 {history.total ?? '—'} 次； 最多查询 20
      次，范围内无记录不表示从未执行。批量选择仅限当前页。
    </Typography.Paragraph>
  )
}

export default function AssetRunEvidence({
  projectId,
  kind,
  id,
  history,
  cases,
}: {
  projectId: string
  kind: AssetKind
  id: string
  history: ReturnType<typeof useAssetHistory>
  cases: TestCase[]
}) {
  const entries = history.history(kind, id)
  return (
    <div className="asset-run-evidence">
      {kind === 'case' && <LatestCaseRunEvidence projectId={projectId} id={id} />}
      <AssetHistoryNotice history={history} />
      {!entries.length ? (
        <Empty description={history.loading ? '正在读取执行记录' : '本次查询范围内没有关联执行'} />
      ) : (
        entries.map((entry) => (
          <div key={entry.run.id} className="asset-run-entry">
            <Space wrap>
              <AssetResultTag status={entry.status} />
              <Typography.Text>
                {new Date(entry.run.created_at).toLocaleString('zh-CN')}
              </Typography.Text>
              <Tag>{entry.versions.map((version) => `v${version}`).join(' / ')}</Tag>
              <Link to={`${projectPath(projectId, 'tasks')}?focus=${entry.run.test_plan_id}`}>
                查看计划
              </Link>
            </Space>
            <Table
              rowKey="id"
              size="small"
              pagination={false}
              dataSource={entry.items}
              columns={[
                {
                  title: '冻结用例版本',
                  render: (_, item) => (
                    <span>
                      {cases.find((asset) => asset.id === item.target_id)?.name ?? item.target_id} ·
                      v{item.target_version}
                    </span>
                  ),
                },
                { title: '结果', render: (_, item) => <AssetResultTag status={item.status} /> },
                {
                  title: '证据',
                  render: (_, item) => <RunItemLinks projectId={projectId} item={item} />,
                },
              ]}
            />
          </div>
        ))
      )}
    </div>
  )
}

function LatestCaseRunEvidence({ projectId, id }: { projectId: string; id: string }) {
  const latest = useQuery({
    queryKey: ['test-case-runs', projectId, id],
    queryFn: () => listLatestTestCaseRuns(projectId, [id]),
    refetchInterval: (query) =>
      query.state.data?.some((run) => ['queued', 'running'].includes(run.status)) ? 2000 : false,
  })
  const run = latest.data?.[0]
  if (latest.error) {
    return (
      <Alert type="warning" title="最近运行读取失败" description={apiErrorMessage(latest.error)} />
    )
  }
  if (!run)
    return (
      <Typography.Paragraph type="secondary">
        {latest.isPending ? '读取最近运行中' : '暂无用例运行记录'}
      </Typography.Paragraph>
    )
  const location = { executionId: run.execution_id, workflowId: run.workflow_id }
  return (
    <div className="asset-run-entry">
      <Typography.Title level={5}>最近用例运行</Typography.Title>
      <Space wrap>
        <AssetResultTag status={run.status} />
        <Tag>
          用例 v{run.case_version} · 流程 v{run.workflow_version}
        </Tag>
        <Typography.Text>{run.source === 'direct' ? '直接运行' : '测试计划'}</Typography.Text>
        <Link to={reportExecutionPath(projectId, location)}>报告</Link>
        <Link to={workflowExecutionPath(projectId, location)}>编排回看</Link>
      </Space>
    </div>
  )
}

function RunItemLinks({ projectId, item }: { projectId: string; item: AssetRunItem }) {
  if (!item.workflow_execution_id)
    return <Typography.Text type="secondary">尚无流程报告</Typography.Text>
  const location = { executionId: item.workflow_execution_id, workflowId: item.workflow_id }
  return (
    <Space wrap>
      <Link to={reportExecutionPath(projectId, location)}>报告</Link>
      <Link to={workflowExecutionPath(projectId, location)}>编排回看</Link>
    </Space>
  )
}
