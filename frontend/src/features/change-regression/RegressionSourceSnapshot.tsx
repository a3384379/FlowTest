import { useQuery } from '@tanstack/react-query'
import { Button, Card, Descriptions, Space, Table, Typography } from 'antd'
import { Link, useSearchParams } from 'react-router-dom'
import { useRouteScopedState } from '../../lib/use-route-scoped-state'
import QueryFailureNotice from '../../components/QueryFailureNotice'
import ResponseCodeReader from '../api-console/ResponseCodeReader'
import ContractEvidenceViewer, {
  type ContractEvidenceSelection,
} from '../contracts/ContractEvidenceDrawer'
import { getImpactRun } from '../impact/impact-service'
import { projectPath } from '../projects/project-routing'
import type { ChangeRegressionRun } from './change-regression-service'

type SourceReference = {
  kind: 'openapi' | 'graphql' | 'grpc' | 'unknown'
  baseline: string
  current: string
  name: string
}
type OpenApiReference = { baseline_run_id: string; current_run_id: string; source_name?: string }
type SchemaReference = {
  baseline_artifact_id: string
  current_artifact_id: string
  protocol: string
  name?: string
}

export default function RegressionSourceSnapshot({
  run,
  enabled,
}: {
  run: ChangeRegressionRun
  enabled: boolean
}) {
  const [params, setParams] = useSearchParams()
  const expanded = params.get('sources') === '1'
  const [selection, setSelection] = useRouteScopedState<ContractEvidenceSelection | null>(
    run.project_id,
    expanded ? run.id : null,
    null,
  )
  const snapshot = useQuery({
    queryKey: ['impact-run', run.project_id, run.impact_run_id],
    queryFn: () => getImpactRun(run.project_id, run.impact_run_id),
    enabled: enabled && expanded,
  })
  function toggle() {
    setParams((current) => {
      const next = new URLSearchParams(current)
      next.set('run', run.id)
      if (expanded) next.delete('sources')
      else next.set('sources', '1')
      return next
    })
  }
  const summary = snapshot.isSuccess ? snapshot.data.source_summary : undefined
  const refs = snapshotReferences(summary)
  return (
    <>
      <Button disabled={!enabled} onClick={toggle} aria-expanded={expanded}>
        {expanded ? '收起冻结来源版本' : '查看冻结来源版本'}
      </Button>
      {expanded && (
        <Card title="冻结来源版本" size="small">
          {!enabled ? (
            <Typography.Paragraph type="secondary">
              影响分析能力未提供，暂不能读取来源版本；链路保存的来源指纹继续保留。
            </Typography.Paragraph>
          ) : (
            <>
              <QueryFailureNotice queries={[snapshot]} />
              {snapshot.isPending && (
                <Typography.Text>正在读取本链路的冻结影响来源</Typography.Text>
              )}
              {snapshot.isSuccess && (
                <>
                  <Descriptions
                    column={1}
                    items={[
                      { label: '影响分析 ID', children: run.impact_run_id },
                      {
                        label: '影响来源指纹',
                        children: (
                          <Typography.Text copyable>
                            {snapshot.data.source_fingerprint}
                          </Typography.Text>
                        ),
                      },
                    ]}
                  />
                  <Typography.Paragraph type="secondary">
                    以下版本 ID 来自原影响快照，独立于当前目录；原始 Git diff
                    未保存在此摘要时，只能核对内容指纹。
                  </Typography.Paragraph>
                  <Table
                    rowKey="key"
                    size="small"
                    dataSource={refs}
                    pagination={{ pageSize: 10, showSizeChanger: false }}
                    scroll={{ x: 650 }}
                    locale={{ emptyText: '该快照未提供版本对比引用，请核对下面保留的来源摘要' }}
                    columns={[
                      { title: '来源', dataIndex: 'name' },
                      {
                        title: '基线版本',
                        key: 'baseline',
                        render: (_, ref) => (
                          <SourceVersion
                            run={run}
                            reference={ref}
                            id={ref.baseline}
                            baseline
                            onOpen={() => setSelection({ kind: 'run', id: ref.baseline })}
                          />
                        ),
                      },
                      {
                        title: '当前版本',
                        key: 'current',
                        render: (_, ref) => (
                          <SourceVersion
                            run={run}
                            reference={ref}
                            id={ref.current}
                            baseline={false}
                            onOpen={() => setSelection({ kind: 'run', id: ref.current })}
                          />
                        ),
                      },
                    ]}
                  />
                  <ResponseCodeReader value={summary} title="冻结来源摘要" />
                </>
              )}
            </>
          )}
        </Card>
      )}
      <ContractEvidenceViewer
        projectId={run.project_id}
        selection={selection}
        onClose={() => setSelection(null)}
      />
    </>
  )
}

function snapshotReferences(summary: { openapi?: unknown; schemas?: unknown } | undefined) {
  return sourceReferences(summary?.openapi, summary?.schemas).map((reference, index) => ({
    ...reference,
    key: index,
  }))
}

function SourceVersion({
  run,
  reference,
  id,
  baseline,
  onOpen,
}: {
  run: ChangeRegressionRun
  reference: SourceReference
  id: string
  baseline: boolean
  onOpen: () => void
}) {
  const label = baseline ? '基线' : '当前版本'
  if (!isUuid(id))
    return (
      <Typography.Text type="secondary">历史版本引用无效，原始值保留在来源摘要中</Typography.Text>
    )
  return (
    <Space orientation="vertical">
      <Typography.Text copyable>{id}</Typography.Text>
      {reference.kind === 'openapi' ? (
        <Button onClick={onOpen}>查看 OpenAPI {label}</Button>
      ) : (
        <SchemaReferenceLink
          projectId={run.project_id}
          reference={reference}
          id={id}
          label={label}
        />
      )}
    </Space>
  )
}

function SchemaReferenceLink({
  projectId,
  reference,
  id,
  label,
}: {
  projectId: string
  reference: SourceReference
  id: string
  label: string
}) {
  if (reference.kind !== 'graphql' && reference.kind !== 'grpc')
    return (
      <Typography.Text type="secondary">该历史来源不支持直接定位，保留原始摘要</Typography.Text>
    )
  const params = new URLSearchParams({
    mode: reference.kind,
    [reference.kind === 'graphql' ? 'graphqlSchema' : 'grpcDescriptor']: id,
  })
  return (
    <Link to={`${projectPath(projectId, 'protocols')}?${params}`}>
      打开 {reference.kind === 'graphql' ? 'GraphQL' : 'Proto / gRPC'} {label} {id}
    </Link>
  )
}

function sourceReferences(openapi: unknown, schemas: unknown): SourceReference[] {
  const before = Array.isArray(openapi) ? openapi.map(openapiReference) : []
  const after = Array.isArray(schemas) ? schemas.map(schemaReference) : []
  return [...before, ...after]
}

function openapiReference(value: unknown): SourceReference {
  if (!isOpenApiReference(value)) return unknownReference()
  return {
    kind: 'openapi',
    baseline: value.baseline_run_id,
    current: value.current_run_id,
    name: sourceName(value.source_name, 'OpenAPI 对比'),
  }
}

function schemaReference(value: unknown): SourceReference {
  if (!isSchemaReference(value)) return unknownReference()
  const kind =
    value.protocol === 'graphql' || value.protocol === 'grpc' ? value.protocol : 'unknown'
  return {
    kind,
    baseline: value.baseline_artifact_id,
    current: value.current_artifact_id,
    name: sourceName(value.name, value.protocol),
  }
}

function sourceName(value: unknown, fallback: string): string {
  return typeof value === 'string' && value.trim() ? value : fallback
}

function unknownReference(): SourceReference {
  return {
    kind: 'unknown',
    baseline: '',
    current: '',
    name: '无法识别的历史来源，原文保留在摘要中',
  }
}
function isUuid(value: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value)
}

function isOpenApiReference(value: unknown): value is OpenApiReference {
  if (!value || typeof value !== 'object') return false
  return (
    'baseline_run_id' in value &&
    typeof value.baseline_run_id === 'string' &&
    'current_run_id' in value &&
    typeof value.current_run_id === 'string'
  )
}

function isSchemaReference(value: unknown): value is SchemaReference {
  if (!value || typeof value !== 'object') return false
  return (
    'baseline_artifact_id' in value &&
    typeof value.baseline_artifact_id === 'string' &&
    'current_artifact_id' in value &&
    typeof value.current_artifact_id === 'string' &&
    'protocol' in value &&
    typeof value.protocol === 'string'
  )
}
