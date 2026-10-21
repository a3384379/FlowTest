import { useQuery } from '@tanstack/react-query'
import { Alert, Card, Descriptions, Modal, Space, Table, Typography } from 'antd'
import { Link, useSearchParams } from 'react-router-dom'
import QueryFailureNotice from '../../components/QueryFailureNotice'
import ResponseCodeReader from '../api-console/ResponseCodeReader'
import ContractEvidenceViewer from '../contracts/ContractEvidenceDrawer'
import { projectPath } from '../projects/project-routing'
import {
  getReleaseRunnerEvidence,
  type ReleaseDecision,
  type ReleaseReason,
} from './release-gate-service'

import { releaseEvidenceLabels, type ReleaseEvidenceKind } from './release-evidence-types'

type Source = {
  kind: ReleaseEvidenceKind
  id: string | null
  valid: boolean
  reason: string
  snapshot: unknown
  metadata: Array<{ key: string; label: string; children: string }>
}

export default function ReleaseEvidenceSources({ decision }: { decision: ReleaseDecision }) {
  const [params, setParams] = useSearchParams()
  const sources = evidenceSources(decision)
  const sourceKind = params.get('source')
  const active = sources.find((source) => source.kind === sourceKind && source.valid)
  function closeSource() {
    setParams((current) => {
      const next = new URLSearchParams(current)
      next.delete('source')
      return next
    })
  }
  return (
    <section aria-label="判断的冻结来源">
      <Typography.Paragraph type="secondary">
        下列身份、版本和时间来自本判断快照；打开原始对象只读，不重新评估。原始对象后续状态可能变化，以此处冻结内容为准。
      </Typography.Paragraph>
      <Space orientation="vertical" className="full-width">
        {sources.map((source) => (
          <Card key={source.kind} size="small" title={releaseEvidenceLabels[source.kind]}>
            <Descriptions column={1} size="small" items={source.metadata} />
            <SourceAction decision={decision} source={source} />
            <Table<ReleaseReason>
              rowKey="code"
              size="small"
              pagination={false}
              scroll={{ x: 520 }}
              dataSource={decision.reasons.filter((reason) => reason.evidence_type === source.kind)}
              locale={{ emptyText: '本判断未提供此类证据的逐项理由' }}
              columns={[
                { title: '冻结结果', dataIndex: 'status' },
                { title: '代码', dataIndex: 'code' },
                { title: '依据', dataIndex: 'message' },
                { title: '实际', render: (_, reason) => JSON.stringify(reason.actual) ?? '未提供' },
                {
                  title: '期望',
                  render: (_, reason) => JSON.stringify(reason.expected) ?? '未提供',
                },
              ]}
            />
          </Card>
        ))}
      </Space>
      <ContractEvidenceViewer
        projectId={decision.project_id}
        selection={
          active?.kind === 'contract_compatibility' ? { kind: 'check', id: active.id! } : null
        }
        onClose={closeSource}
      />
      {active?.kind === 'runner' && (
        <RunnerSource
          key={`${decision.id}:${active.id}`}
          projectId={decision.project_id}
          taskId={active.id!}
          onClose={closeSource}
        />
      )}
      {sourceKind && !active && (
        <Alert type="warning" title="指定来源无法从本判断快照确认，保留原始证据供核对" />
      )}
    </section>
  )
}

function SourceAction({ decision, source }: { decision: ReleaseDecision; source: Source }) {
  const [params] = useSearchParams()
  if (!source.valid || !source.id)
    return <Typography.Paragraph type="secondary">{source.reason}</Typography.Paragraph>
  const next = new URLSearchParams(params)
  next.set('decision', decision.id)
  next.set('source', source.kind)
  return (
    <Typography.Paragraph>
      <Link to={sourcePath(decision.project_id, source) ?? `?${next}`}>
        查看{releaseEvidenceLabels[source.kind]}来源
      </Link>
    </Typography.Paragraph>
  )
}

function sourcePath(projectId: string, source: Source): string | null {
  const targets = {
    quality_gate: ['tasks', 'run'],
    impact: ['impact', 'run'],
    release_risk: ['quality', 'risk'],
    performance: ['performance', 'run'],
  } as const
  if (source.kind === 'contract_compatibility' || source.kind === 'runner') return null
  const [section, key] = targets[source.kind]
  return `${projectPath(projectId, section)}?${new URLSearchParams({ [key]: source.id! })}`
}

function evidenceSources(decision: ReleaseDecision): Source[] {
  const fields: Array<{ kind: ReleaseEvidenceKind; key: string; expected: string | null }> = [
    { kind: 'quality_gate', key: 'test_plan_run_id', expected: decision.test_plan_run_id },
    { kind: 'contract_compatibility', key: 'check_id', expected: decision.deployment_check_id },
    { kind: 'impact', key: 'run_id', expected: decision.impact_run_id },
    { kind: 'release_risk', key: 'risk_id', expected: decision.release_risk_id },
    { kind: 'performance', key: 'run_id', expected: decision.performance_run_id },
    { kind: 'runner', key: 'task_id', expected: decision.runner_task_id },
  ]
  return fields.map((field) => {
    const raw = decision.evidence_snapshot?.[field.kind]
    const snapshot = objectSnapshot(raw)
    const id = stringValue(snapshot[field.key])
    const valid = isUuid(id) && id === field.expected
    return {
      kind: field.kind,
      id,
      valid,
      snapshot: raw,
      reason: sourceReason(raw, id, field.expected),
      metadata: [
        ...sourceMetadata(snapshot, id),
        ...(field.expected && field.expected !== id
          ? [{ key: 'expected', label: '判断引用 ID', children: field.expected }]
          : []),
      ],
    }
  })
}

function sourceReason(raw: unknown, id: string | null, expected: string | null): string {
  if (!raw) return '未提供此类冻结证据；不从当前目录补造历史来源'
  if (!isUuid(id)) return '历史快照缺少有效来源 ID，无法定位；原始值保留在冻结证据中'
  if (id !== expected) return '快照来源 ID 与判断引用不一致，暂不提供跳转；请核对原始证据'
  return ''
}

function sourceMetadata(snapshot: Record<string, unknown>, id: string | null) {
  const fields = [
    ['status', '冻结状态'],
    ['decision', '兼容性结果'],
    ['provider_version', '提供方版本'],
    ['scenario_version', '场景版本'],
    ['scenario_id', '场景 ID'],
    ['algorithm_version', '算法版本'],
    ['evaluated_at', '评估时间'],
    ['checked_at', '契约检查时间'],
    ['completed_at', '完成时间'],
    ['created_at', '生成时间'],
    ['fingerprint', '冻结指纹'],
    ['source_fingerprint', '来源指纹'],
    ['quality_gate_id', '质量门禁 ID'],
    ['fencing_token', '隔离令牌编号'],
    ['attempts', '尝试次数'],
    ['completed_lease_count', '完成租约数'],
  ] as const
  return [
    { key: 'id', label: '来源 ID', children: id ?? '未提供' },
    ...fields.flatMap(([key, label]) => {
      const value = snapshot[key]
      return typeof value === 'string' || typeof value === 'number'
        ? [{ key, label, children: String(value) }]
        : []
    }),
  ]
}

function objectSnapshot(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {}
}
function stringValue(value: unknown): string | null {
  return typeof value === 'string' ? value : null
}
function isUuid(value: string | null): boolean {
  return (
    value !== null && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value)
  )
}

function RunnerSource({
  projectId,
  taskId,
  onClose,
}: {
  projectId: string
  taskId: string
  onClose: () => void
}) {
  const detail = useQuery({
    queryKey: ['release-runner-evidence', projectId, taskId],
    queryFn: () => getReleaseRunnerEvidence(projectId, taskId),
  })
  return (
    <Modal open title="Runner 原始任务证据" footer={null} onCancel={onClose} width={720}>
      <QueryFailureNotice queries={[detail]} />
      <Typography.Paragraph type="secondary">
        此处为项目授权范围内的当前原始任务摘要；决策时冻结的尝试、lease 和状态仍保留在判断快照。
      </Typography.Paragraph>
      {detail.isPending && <Typography.Text>正在读取原始任务</Typography.Text>}
      {detail.isSuccess && (
        <ResponseCodeReader value={detail.data} title="项目 Runner 任务原始摘要" />
      )}
    </Modal>
  )
}
