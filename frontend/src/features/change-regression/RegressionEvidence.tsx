import { useQuery } from '@tanstack/react-query'
import { Card, Descriptions, Space, Table, Typography } from 'antd'
import { Link } from 'react-router-dom'
import type { ReactNode } from 'react'
import QueryFailureNotice from '../../components/QueryFailureNotice'
import ResponseCodeReader from '../api-console/ResponseCodeReader'
import { projectPath } from '../projects/project-routing'
import { QualityAssetEvidence } from '../quality/QualityEvidence'
import { getTestPlanRun } from '../task-plans/task-plan-service'
import { executionAttempt, reportExecutionPath } from '../workflows/execution-navigation'
import type {
  ChangeRegressionRun,
  FailureTriageResult,
  MissingTestProposal,
} from './change-regression-service'

type EvidenceTarget =
  | { kind: 'node'; executionId: string; nodeId: string; attempt?: number }
  | { kind: 'item'; runId: string; itemId: string }
type RunProof = Awaited<ReturnType<typeof getTestPlanRun>>

export function RegressionChainLinks({
  run,
  status,
}: {
  run: ChangeRegressionRun
  status: ReactNode
}) {
  return (
    <Descriptions
      size="small"
      bordered
      column={{ xs: 1, md: 2 }}
      items={[
        { label: '链路', children: run.title },
        { label: '状态', children: status },
        { label: '来源', children: run.source_ref || '未填写' },
        {
          label: '来源指纹',
          children: <Typography.Text copyable>{run.source_fingerprint}</Typography.Text>,
        },
        {
          label: 'Impact Run',
          children: (
            <Link
              to={`${projectPath(run.project_id, 'impact')}?${new URLSearchParams({ run: run.impact_run_id })}`}
            >
              查看冻结影响分析
            </Link>
          ),
        },
        {
          label: 'Test Plan Run',
          children: run.test_plan_run_id ? (
            <Link
              to={`${projectPath(run.project_id, 'tasks')}?${new URLSearchParams({ run: run.test_plan_run_id, focus: run.test_plan_id })}`}
            >
              查看计划运行
            </Link>
          ) : (
            '尚未执行'
          ),
        },
        {
          label: 'Release Decision',
          children: run.release_decision_id ? (
            <Link
              to={`${projectPath(run.project_id, 'release')}?${new URLSearchParams({ decision: run.release_decision_id })}`}
            >
              查看发布判断
            </Link>
          ) : (
            '尚未评估'
          ),
        },
      ]}
    />
  )
}

export function RegressionTriageReferences({
  run,
  value,
}: {
  run: ChangeRegressionRun
  value: FailureTriageResult
}) {
  const entries = value.evidence_refs.map((ref, index) => ({
    ref,
    index,
    target: parseEvidenceRef(ref),
  }))
  const proof = useQuery({
    queryKey: ['regression-triage-run', run.project_id, run.id, run.test_plan_run_id],
    queryFn: () => getTestPlanRun(run.project_id, run.test_plan_run_id!),
    enabled: Boolean(run.test_plan_run_id && entries.some((entry) => entry.target)),
  })
  return (
    <>
      <QueryFailureNotice queries={[proof]} />
      <Typography.Paragraph type="secondary">
        引用按本链路的冻结计划运行核对归属。原引用未记录的协议、尝试或迭代实例会明确标明；不会补执行来生成证据。
      </Typography.Paragraph>
      <Table
        rowKey="index"
        size="small"
        pagination={{ pageSize: 10, showSizeChanger: false }}
        scroll={{ x: 650 }}
        dataSource={entries}
        locale={{ emptyText: '未提供证据引用' }}
        columns={[
          {
            title: '原始引用',
            key: 'ref',
            render: (_, entry) => (
              <Typography.Text copyable style={{ overflowWrap: 'anywhere' }}>
                {entry.ref}
              </Typography.Text>
            ),
          },
          {
            title: '定位摘要',
            key: 'summary',
            render: (_, entry) => <ReferenceSummary target={entry.target} />,
          },
          {
            title: '证据入口',
            key: 'entry',
            render: (_, entry) => (
              <ReferenceLink
                projectId={run.project_id}
                parentRunId={run.test_plan_run_id}
                target={entry.target}
                index={entry.index}
                proof={proof.isSuccess ? proof.data : undefined}
                pending={proof.isFetching}
              />
            ),
          },
        ]}
      />
    </>
  )
}

function ReferenceSummary({ target }: { target: EvidenceTarget | null }) {
  if (!target)
    return <Typography.Text type="secondary">不支持的历史引用，保留原文供核对</Typography.Text>
  if (target.kind === 'item')
    return (
      <Space orientation="vertical">
        <Typography.Text>计划运行项：{target.itemId}</Typography.Text>
        <Typography.Text type="secondary">尝试次数与实际执行链接请在运行项中核对</Typography.Text>
      </Space>
    )
  return (
    <Space orientation="vertical">
      <Typography.Text>节点：{target.nodeId}</Typography.Text>
      <Typography.Text>尝试：{target.attempt ?? '未提供编号'}</Typography.Text>
      <Typography.Text type="secondary">
        业务协议、迭代/分支实例未在原引用中记录，请在报告核对
      </Typography.Text>
    </Space>
  )
}

function ReferenceLink({
  projectId,
  parentRunId,
  target,
  index,
  proof,
  pending,
}: {
  projectId: string
  parentRunId: string | null
  target: EvidenceTarget | null
  index: number
  proof?: RunProof
  pending: boolean
}) {
  if (!target) return null
  if (!parentRunId)
    return <Typography.Text type="secondary">缺少父计划运行，无法确认引用归属</Typography.Text>
  if (!proof)
    return (
      <Typography.Text type="secondary">
        {pending ? '正在核对冻结运行' : '运行证据未提供，暂不能确认引用归属'}
      </Typography.Text>
    )
  const item =
    target.kind === 'node'
      ? proof.items.find((entry) => entry.workflow_execution_id === target.executionId)
      : proof.items.find((entry) => entry.id === target.itemId && target.runId === parentRunId)
  if (!item)
    return <Typography.Text type="warning">原引用不属于本链路的计划运行，保留原文</Typography.Text>
  return (
    <Space orientation="vertical">
      <Typography.Text type="secondary">计划项已记录 {item.attempts} 次尝试</Typography.Text>
      {target.kind === 'node' ? (
        <Link to={reportExecutionPath(projectId, target)}>查看节点执行证据 {index + 1}</Link>
      ) : (
        <Link
          to={`${projectPath(projectId, 'tasks')}?${new URLSearchParams({ run: target.runId, item: target.itemId })}`}
        >
          查看运行项证据 {index + 1}
        </Link>
      )}
    </Space>
  )
}

function parseEvidenceRef(ref: string): EvidenceTarget | null {
  try {
    const url = new URL(ref)
    if (
      url.protocol !== 'flowtest:' ||
      [...url.searchParams.keys()].some((key) => key !== 'attempt')
    )
      return null
    const parts = url.pathname
      .split('/')
      .filter(Boolean)
      .map((part) => decodeURIComponent(part))
    if (url.hostname === 'runs') return nodeReference(parts, url.searchParams)
    if (url.hostname === 'test-plan-runs') return itemReference(parts)
    return null
  } catch (error) {
    if (error instanceof TypeError || error instanceof URIError) return null
    throw error
  }
}

function itemReference(parts: string[]): EvidenceTarget | null {
  if (parts.length !== 3 || parts[1] !== 'items' || !isUuid(parts[0]) || !isUuid(parts[2]))
    return null
  return { kind: 'item', runId: parts[0].toLowerCase(), itemId: parts[2].toLowerCase() }
}

function nodeReference(parts: string[], params: URLSearchParams): EvidenceTarget | null {
  if (
    parts.length !== 3 ||
    !isUuid(parts[0]) ||
    parts[1] !== 'nodes' ||
    !/^[A-Za-z0-9_.:-]{1,200}$/.test(parts[2])
  )
    return null
  const attempt = executionAttempt(params)
  if (params.has('attempt') && attempt === undefined) return null
  return { kind: 'node', executionId: parts[0].toLowerCase(), nodeId: parts[2], attempt }
}

function isUuid(value: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value)
}

export function RegressionMaterializedAssets({ run }: { run: ChangeRegressionRun }) {
  const accepted = run.missing_tests.filter((item) => item.materialized_resource_id)
  if (!accepted.length) return null
  return (
    <Card size="small" title="本链路生成资产">
      <Space orientation="vertical" className="full-width">
        <Typography.Paragraph type="secondary">
          保留生成时的设计与资产引用。生成时保存为草稿，当前发布状态须打开资产后确认；有固定版本时可独立读取。
        </Typography.Paragraph>
        {accepted.map((item) => (
          <MaterializedItem key={item.item_id} run={run} item={item} />
        ))}
      </Space>
    </Card>
  )
}

function MaterializedItem({ run, item }: { run: ChangeRegressionRun; item: MissingTestProposal }) {
  const assets = (run.selection_summary.generated_assets ?? []).filter(
    (asset) => asset.source_item_id === item.item_id,
  )
  return (
    <Card size="small" title={item.title}>
      <Descriptions
        column={1}
        items={[
          { label: '来源审核项', children: item.item_id },
          { label: '生成资源类型', children: item.materialized_resource_type ?? '未提供' },
          {
            label: '生成资源 ID',
            children: <Typography.Text copyable>{item.materialized_resource_id}</Typography.Text>,
          },
        ]}
      />
      {assets.length ? (
        assets.map((asset) => (
          <Space key={`${asset.target_type}:${asset.target_id}`} wrap className="page-alert">
            {asset.target_type === 'workflow' ? (
              <Link
                to={`${projectPath(run.project_id, 'workflows')}?${new URLSearchParams({ focus: asset.target_id })}`}
              >
                打开生成工作流 {asset.target_id}
              </Link>
            ) : (
              <Link
                to={`${projectPath(run.project_id, 'assets')}?${new URLSearchParams({ type: 'case', focus: asset.target_id, version: 'draft' })}`}
              >
                打开生成用例 {asset.target_id}
              </Link>
            )}
            {asset.target_version && (
              <QualityAssetEvidence
                projectId={run.project_id}
                type={asset.target_type}
                id={asset.target_id}
                version={asset.target_version}
              />
            )}
          </Space>
        ))
      ) : (
        <Typography.Paragraph type="secondary">
          该历史记录未提供流程或用例物化引用，无法从设计 ID 推断资产；下面保留审核时的设计内容。
        </Typography.Paragraph>
      )}
      <ResponseCodeReader value={item.proposed_content} title="生成时审核设计内容" />
    </Card>
  )
}
