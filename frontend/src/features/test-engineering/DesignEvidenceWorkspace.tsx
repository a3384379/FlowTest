import { confidenceLabel } from './design-confidence'
import { useQuery } from '@tanstack/react-query'
import {
  Alert,
  Button,
  Card,
  Collapse,
  Descriptions,
  Drawer,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd'
import { useState } from 'react'

import QueryFailureNotice from '../../components/QueryFailureNotice'
import { getApiDetail } from '../api-console/api-service'
import { CoverageTable, OracleTable } from './DesignReviewTables'
import { scenarioReason } from './design-review-rules'
import type {
  EvidenceDetail,
  EvidenceRef,
  ScenarioCandidate,
  TestDesignDocument,
} from './test-engineering-service'

export default function DesignEvidenceWorkspace({
  design,
  scenario,
  evidenceDetails = [],
  projectId,
  onOpen,
}: {
  design: TestDesignDocument
  scenario?: ScenarioCandidate
  evidenceDetails?: EvidenceDetail[]
  projectId: string
  onOpen: (path: string) => void
}) {
  const [reference, setReference] = useState<EvidenceRef | null>(null)
  const [unresolved, setUnresolved] = useState<string | null>(null)
  function inspectId(id: string) {
    const matches = design.evidence_refs.filter((value) => value.id === id)
    if (matches.length !== 1) {
      setUnresolved(id)
      setReference(null)
      return
    }
    inspectReference(matches[0])
  }
  function inspectReference(value: EvidenceRef) {
    setUnresolved(null)
    setReference(value)
  }
  return (
    <Space orientation="vertical" size={16} className="full-width">
      {unresolved && (
        <Alert
          showIcon
          type="warning"
          title={`引用 ${unresolved} 未提供唯一来源`}
          description="请从完整来源表选择具体记录；没有猜测来源、修订或字段路径。"
        />
      )}
      {scenario ? (
        <ScenarioDetails
          design={design}
          scenario={scenario}
          inspectId={inspectId}
          onInspect={inspectReference}
        />
      ) : (
        <Card title="场景详情">
          <Typography.Text type="secondary">选择场景查看预期、覆盖与来源。</Typography.Text>
        </Card>
      )}
      <Card title={`完整设计来源（${design.evidence_refs.length}条）`}>
        <EvidenceTable items={design.evidence_refs} onInspect={inspectReference} />
      </Card>
      {reference && (
        <SourceEvidenceDrawer
          key={JSON.stringify([
            reference.id,
            reference.source_type,
            reference.source_ref,
            reference.revision,
          ])}
          reference={reference}
          details={evidenceDetails}
          projectId={projectId}
          onClose={() => setReference(null)}
          onOpen={onOpen}
        />
      )}
    </Space>
  )
}

function scenarioCoverage(design: TestDesignDocument, scenario: ScenarioCandidate) {
  const scopes = new Set(
    scenario.mutations.map((value) => {
      const path = value.path.startsWith(`${value.location}.`)
        ? value.path
        : `${value.location}.${value.path}`
      return `${design.intent.key}.${path}`
    }),
  )
  if (scenario.kind === 'happy_path') scopes.add(design.intent.key)
  return (design.coverage?.entries ?? []).filter((value) => scopes.has(value.target_ref))
}

function EvidenceTable({
  items,
  onInspect,
}: {
  items: EvidenceRef[]
  onInspect: (value: EvidenceRef) => void
}) {
  return (
    <Table
      rowKey={(value) =>
        JSON.stringify([value.id, value.source_type, value.source_ref, value.revision])
      }
      size="small"
      pagination={{ pageSize: 8, showSizeChanger: false }}
      scroll={{ x: 760 }}
      dataSource={items}
      columns={[
        { title: '来源类型', dataIndex: 'source_type', render: sourceType },
        {
          title: '证据语义',
          dataIndex: 'semantic_role',
          render: (value: string | undefined) => <Tag>{semanticRole(value)}</Tag>,
        },
        { title: '来源标识', dataIndex: 'source_ref' },
        { title: '固定修订', dataIndex: 'revision' },
        {
          title: '操作',
          render: (_, item) => (
            <Button onClick={() => onInspect(item)} aria-label={`查看来源：${item.id}`}>
              查看来源
            </Button>
          ),
        },
      ]}
    />
  )
}

type SourceReference =
  { kind: 'api'; id: string; version: number } | { kind: 'workflow' | 'case'; id: string }
function sourceReference(raw: string): SourceReference | null {
  const uuid = '([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})'
  const api = new RegExp(`^api-definition://${uuid}/version/([1-9][0-9]*)$`, 'i').exec(raw)
  if (api && Number.isSafeInteger(Number(api[2])))
    return { kind: 'api', id: api[1], version: Number(api[2]) }
  const asset = new RegExp(`^(workflow|testcase)://${uuid}$`, 'i').exec(raw)
  return asset
    ? { kind: asset[1].toLowerCase() === 'workflow' ? 'workflow' : 'case', id: asset[2] }
    : null
}

function SourceEvidenceDrawer({
  reference,
  details,
  projectId,
  onClose,
  onOpen,
}: {
  reference: EvidenceRef
  details: EvidenceDetail[]
  projectId: string
  onClose: () => void
  onOpen: (path: string) => void
}) {
  const source = sourceReference(reference.source_ref)
  const detail = details.find(
    (value) =>
      value.id === reference.id &&
      value.source_type === reference.source_type &&
      value.source_ref === reference.source_ref &&
      value.revision === reference.revision,
  )
  return (
    <Drawer title="来源证据" open onClose={onClose} size="min(880px, 100vw)">
      <Space orientation="vertical" size={16} className="test-design-review full-width">
        <EvidenceMetadata reference={reference} detail={detail} />
        {source?.kind === 'api' && <FixedApiSource source={source} projectId={projectId} />}
        {source ? (
          <Button onClick={() => onOpen(sourcePath(projectId, source))}>
            打开来源资产（当前目录）
          </Button>
        ) : (
          <Typography.Text type="secondary">
            该来源没有可确认的产品对象入口，保留原始引用。
          </Typography.Text>
        )}
        <Collapse
          items={[
            {
              key: 'source',
              label: '来源原始技术信息',
              children: (
                <pre className="test-design-json">
                  {JSON.stringify({ reference, detail: detail ?? null }, null, 2)}
                </pre>
              ),
            },
          ]}
        />
      </Space>
    </Drawer>
  )
}

function ScenarioDetails({
  design,
  scenario,
  inspectId,
  onInspect,
}: {
  design: TestDesignDocument
  scenario: ScenarioCandidate
  inspectId: (id: string) => void
  onInspect: (reference: EvidenceRef) => void
}) {
  const oracles = design.oracles.filter((value) => value.applies_to.includes(scenario.id))
  const ids = new Set([
    ...scenario.evidence_refs,
    ...oracles.flatMap((value) => value.evidence_refs),
  ])
  const references = design.evidence_refs.filter((value) => ids.has(value.id))
  const reason = scenarioReason(scenario, design.oracles)
  return (
    <Card title={`场景详情：${scenario.title}`}>
      <Space orientation="vertical" className="full-width">
        {reason && (
          <Alert
            showIcon
            type="warning"
            title="仅保留为设计，尚不能生成可执行资产"
            description={reason}
          />
        )}
        <Descriptions
          column={{ xs: 1, sm: 2 }}
          items={[
            { label: '确定性', children: scenario.deterministic ? '确定性输入' : '存在不确定性' },
            { label: '置信度', children: confidenceLabel(scenario.confidence) },
            {
              label: '认证方式',
              children: scenario.request.auth_disabled ? '禁用认证' : '继承接口认证',
            },
            {
              label: '请求变更路径',
              children:
                scenario.mutations
                  .map((value) => `${value.location} · ${value.path} · ${value.operation}`)
                  .join('；') || '保持请求基线',
            },
          ]}
        />
        <Card size="small" title={`本场景的判断预期（${oracles.length}项）`}>
          <OracleTable items={oracles} onEvidence={inspectId} />
        </Card>
        <Card size="small" title="本场景的直接覆盖项">
          <CoverageTable items={scenarioCoverage(design, scenario)} />
        </Card>
        <Card size="small" title="本场景与预期的来源">
          <EvidenceTable items={references} onInspect={onInspect} />
        </Card>
        <Collapse
          items={[
            {
              key: 'scenario',
              label: '场景原始技术信息',
              children: <pre className="test-design-json">{JSON.stringify(scenario, null, 2)}</pre>,
            },
          ]}
        />
      </Space>
    </Card>
  )
}

function EvidenceMetadata({
  reference,
  detail,
}: {
  reference: EvidenceRef
  detail?: EvidenceDetail
}) {
  return (
    <Descriptions
      column={1}
      items={[
        { label: '引用标识', children: reference.id },
        { label: '来源', children: reference.source_ref },
        { label: '固定修订', children: reference.revision },
        { label: '字段路径', children: detail?.path ?? '未提供' },
        { label: '证据语义', children: semanticRole(reference.semantic_role) },
        { label: '置信度', children: confidenceLabel(detail?.confidence) },
        { label: '确定性', children: evidenceDeterminism(detail?.deterministic) },
      ]}
    />
  )
}

function evidenceDeterminism(value: boolean | undefined): string {
  if (value === undefined) return '未提供'
  return value ? '确定性证据' : '需要人工复核'
}

function FixedApiSource({
  source,
  projectId,
}: {
  source: Extract<SourceReference, { kind: 'api' }>
  projectId: string
}) {
  const version = useQuery({
    queryKey: ['test-design-source-version', projectId, source.id, source.version],
    queryFn: () => getApiDetail(projectId, source.id, source.version),
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  })
  return (
    <>
      <QueryFailureNotice queries={[version]} />
      {version.isPending && <Typography.Text>正在读取固定接口版本</Typography.Text>}
      {version.data && (
        <Descriptions
          column={1}
          items={[
            { label: '固定接口版本', children: `v${version.data.version.version}` },
            {
              label: '请求',
              children: `${version.data.version.method} ${version.data.version.path}`,
            },
          ]}
        />
      )}
    </>
  )
}

function sourcePath(projectId: string, source: SourceReference): string {
  const section =
    source.kind === 'api' ? 'apis' : source.kind === 'workflow' ? 'workflows' : 'assets'
  const params = new URLSearchParams({ focus: source.id })
  if (source.kind === 'case') params.set('type', 'case')
  return `/projects/${encodeURIComponent(projectId)}/${section}?${params}`
}

function semanticRole(value: string | undefined): string {
  const labels: Record<string, string> = {
    normative: '规范性证据',
    observed: '观察性证据',
    mixed: '混合证据',
    coverage: '覆盖证据',
    supporting: '辅助证据',
  }
  return labels[value ?? 'supporting'] ?? value ?? '辅助证据'
}

function sourceType(value: string): string {
  const labels: Record<string, string> = {
    contract: '接口契约',
    source: '源码',
    runtime: '运行记录',
    workflow: '工作流',
    existing_test: '已有测试',
    data_profile: '数据画像',
    service_topology: '服务拓扑',
    change: '变更',
    user_confirmed_rule: '人工确认规则',
  }
  return labels[value] ?? value
}
