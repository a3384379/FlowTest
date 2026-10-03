import { Alert, Button, Empty, Pagination, Select, Space, Table, Tag, Typography } from 'antd'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { apiErrorMessage, type Page, type TestCase } from '../../lib/api'
import { useRouteScopedState } from '../../lib/use-route-scoped-state'
import { projectPath } from '../projects/project-routing'
import { reportExecutionPath, workflowExecutionPath } from '../workflows/execution-navigation'
import {
  assetRunHistory,
  assetRunLabels,
  reportItem,
  type AssetRunEntry,
} from './asset-run-view-model'
import {
  listCaseRunHistory,
  listSuiteRunHistory,
  type AssetKind,
  type AssetRunItem,
  type AssetRunDetail,
  type CaseRunHistory,
} from './asset-workspace-service'
import type { useAssetHistory } from './use-asset-history'

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
  if (!entry) return <Typography.Text type="secondary">暂无套件运行</Typography.Text>
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
  if (!history.error) return null
  return (
    <Alert
      type="warning"
      showIcon
      title="套件最近结果读取失败"
      description={apiErrorMessage(history.error)}
      action={
        <Button size="small" onClick={() => void history.reload()}>
          重新加载
        </Button>
      }
    />
  )
}

type AssetRunEvidenceProps = {
  projectId: string
  kind: AssetKind
  id: string
  cases: TestCase[]
  version?: number | 'draft'
  versions?: number[]
}

export default function AssetRunEvidence(props: AssetRunEvidenceProps) {
  const { history, page, setPage, selectedVersion, changeVersion } = useRunHistory(props)
  const data = history.data
  const count = data?.data.items.length ?? 0
  const total = data?.data.total
  return (
    <div className="asset-run-evidence">
      <HistoryToolbar
        kind={props.kind}
        versions={props.versions ?? []}
        selectedVersion={selectedVersion}
        onVersion={changeVersion}
        loading={history.isFetching}
        onReload={() => void history.refetch()}
      />
      <Typography.Paragraph type="secondary">
        当前页 {count} 条 · 当前筛选共 {total ?? '—'} 条；记录保留执行时的固定版本。
      </Typography.Paragraph>
      {history.error && (
        <Alert
          type="warning"
          title="执行历史读取失败"
          description={apiErrorMessage(history.error)}
        />
      )}
      <HistoryRecords {...props} data={data} loading={history.isPending} error={history.error} />
      <Pagination
        current={page}
        pageSize={20}
        total={total ?? 0}
        showSizeChanger={false}
        hideOnSinglePage
        onChange={setPage}
        showTotal={(size) => `共 ${size} 条执行记录`}
      />
    </div>
  )
}

function useRunHistory({ projectId, kind, id, version }: AssetRunEvidenceProps) {
  const scope = `asset-run-history:${kind}:${id}:${version ?? 'all'}`
  const [page, setPage] = useRouteScopedState(projectId, `${scope}:page`, 1)
  const [selectedVersion, setVersion] = useRouteScopedState<number | 'all'>(
    projectId,
    `${scope}:version`,
    typeof version === 'number' ? version : 'all',
  )
  const filter = selectedVersion === 'all' ? undefined : selectedVersion
  const history = useQuery({
    queryKey: ['asset-run-history', projectId, kind, id, page, filter],
    queryFn: async () =>
      kind === 'case'
        ? { kind: 'case' as const, data: await listCaseRunHistory(projectId, id, page, filter) }
        : { kind: 'suite' as const, data: await listSuiteRunHistory(projectId, id, page, filter) },
    refetchInterval: (query) => (historyIsActive(query.state.data) ? 2000 : false),
  })
  return {
    history,
    page,
    setPage,
    selectedVersion,
    changeVersion: (value: number | 'all') => {
      setVersion(value)
      setPage(1)
    },
  }
}

function HistoryToolbar({
  kind,
  versions,
  selectedVersion,
  onVersion,
  loading,
  onReload,
}: {
  kind: AssetKind
  versions: number[]
  selectedVersion: number | 'all'
  onVersion: (value: number | 'all') => void
  loading: boolean
  onReload: () => void
}) {
  return (
    <Space wrap>
      <Typography.Title level={5}>
        {kind === 'case' ? '用例运行历史' : '套件运行历史'}
      </Typography.Title>
      <Select
        aria-label="历史资产版本"
        style={{ minWidth: 150 }}
        value={selectedVersion}
        options={[
          { value: 'all', label: '全部发布版本' },
          ...versions.map((item) => ({ value: item, label: `已发布 v${item}` })),
        ]}
        onChange={onVersion}
      />
      <Button size="small" aria-label="刷新历史" loading={loading} onClick={onReload}>
        刷新历史
      </Button>
    </Space>
  )
}

type AssetHistoryPage =
  { kind: 'case'; data: Page<CaseRunHistory> } | { kind: 'suite'; data: Page<AssetRunDetail> }

function HistoryRecords({
  projectId,
  kind,
  id,
  cases,
  data,
  loading,
  error,
}: AssetRunEvidenceProps & {
  data?: AssetHistoryPage
  loading: boolean
  error: Error | null
}) {
  if (!data?.data.items.length) {
    return error ? null : (
      <Empty description={loading ? '正在读取执行历史' : '当前版本筛选下没有执行记录'} />
    )
  }
  if (data.kind === 'case')
    return data.data.items.map((run) => (
      <CaseHistoryEntry key={run.id} projectId={projectId} run={run} />
    ))
  return assetRunHistory(data.data.items, kind, id).map((entry) => (
    <SuiteHistoryEntry key={entry.run.id} projectId={projectId} entry={entry} cases={cases} />
  ))
}

type HistoryData =
  | { kind: 'case'; data: { items: CaseRunHistory[] } }
  | { kind: 'suite'; data: { items: Array<{ items: AssetRunItem[] }> } }

function historyIsActive(data?: HistoryData): boolean {
  const statuses =
    data?.kind === 'case' ? data.data.items : data?.data.items.flatMap((entry) => entry.items)
  return statuses?.some((item) => ['queued', 'running'].includes(item.status)) ?? false
}

function CaseHistoryEntry({ projectId, run }: { projectId: string; run: CaseRunHistory }) {
  const location = run.execution_id
    ? { executionId: run.execution_id, workflowId: run.workflow_id }
    : null
  return (
    <div className="asset-run-entry">
      <Space wrap>
        <AssetResultTag status={run.status} />
        <Typography.Text>
          {new Date(run.started_at ?? run.created_at).toLocaleString('zh-CN')}
        </Typography.Text>
        <Tag>
          用例 v{run.case_version} · 流程 v{run.workflow_version}
        </Tag>
        <Typography.Text>{run.source === 'direct' ? '直接运行' : '测试计划'}</Typography.Text>
        {location ? (
          <>
            <Link to={reportExecutionPath(projectId, location)}>报告</Link>
            <Link to={workflowExecutionPath(projectId, location)}>编排回看</Link>
          </>
        ) : (
          <Typography.Text type="secondary">尚无流程报告</Typography.Text>
        )}
        {run.plan_id && (
          <Link to={`${projectPath(projectId, 'tasks')}?focus=${run.plan_id}`}>查看计划</Link>
        )}
      </Space>
      <Typography.Paragraph type="secondary" copyable>
        {run.execution_id ?? run.plan_run_id}
      </Typography.Paragraph>
    </div>
  )
}

function SuiteHistoryEntry({
  projectId,
  entry,
  cases,
}: {
  projectId: string
  entry: AssetRunEntry
  cases: TestCase[]
}) {
  return (
    <div className="asset-run-entry">
      <Space wrap>
        <AssetResultTag status={entry.status} />
        <Typography.Text>{new Date(entry.run.created_at).toLocaleString('zh-CN')}</Typography.Text>
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
                {cases.find((asset) => asset.id === item.target_id)?.name ?? item.target_id} · v
                {item.target_version}
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
