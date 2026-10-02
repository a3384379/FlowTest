import { ClockCircleOutlined, LockOutlined } from '@ant-design/icons'
import {
  Alert,
  Button,
  Descriptions,
  Empty,
  Pagination,
  Select,
  Space,
  Tabs,
  Tag,
  Typography,
} from 'antd'
import { useEffect, useState } from 'react'
import { useRouteScopedState } from '../lib/use-route-scoped-state'
import AssertionEvidence from '../features/evidence/AssertionEvidence'
import WorkflowNodeRelations from './WorkflowNodeRelations'

import type {
  ExecutionCheckpoint,
  Page,
  WorkflowControlRecordDetail,
  WorkflowControlRecordSummary,
  WorkflowDefinition,
  WorkflowNode,
  WorkflowNodeExecution,
  WorkflowNodeObservation,
} from '../lib/api'
import { apiErrorMessage } from '../lib/api'
import {
  getWorkflowControlRecord,
  getWorkflowInstance,
  listWorkflowControlRecords,
  downloadWorkflowOutput,
} from '../features/workflows/workflow-service'

type RuntimeInspectorProps = {
  mode: 'run' | 'history'
  projectId?: string
  executionId?: string
  node: WorkflowNode | null
  definition: WorkflowDefinition
  execution: WorkflowNodeExecution | undefined
  nodes: WorkflowNodeExecution[]
  context: Record<string, unknown>
  onLocateNode?: (nodeId: string) => void
  initialAttempt?: number
  onSelectAttempt?: (attempt: number) => void
}

export default function WorkflowRunInspector({
  mode,
  projectId,
  executionId,
  node,
  definition,
  execution,
  nodes,
  context,
  onLocateNode,
  initialAttempt,
  onSelectAttempt,
}: RuntimeInspectorProps) {
  if (!node) return <EmptyRuntimeInspector mode={mode} />
  return (
    <RuntimeNodeDetail
      key={`${mode}:${executionId ?? ''}:${node.id}`}
      mode={mode}
      projectId={projectId}
      executionId={executionId}
      node={node}
      definition={definition}
      execution={execution}
      nodes={nodes}
      context={context}
      onLocateNode={onLocateNode}
      initialAttempt={initialAttempt}
      onSelectAttempt={onSelectAttempt}
    />
  )
}

function RuntimeNodeDetail({
  mode,
  projectId,
  executionId,
  node,
  definition,
  execution,
  nodes,
  context,
  onLocateNode,
  initialAttempt,
  onSelectAttempt,
}: RuntimeInspectorProps & { node: WorkflowNode }) {
  const observations = execution?.result?.observations ?? []
  const [attempt, setAttempt] = useRuntimeAttempt(
    projectId,
    executionId,
    node.id,
    initialAttempt,
    observations,
  )
  const observation = selectedObservation(observations, attempt)
  const input = upstreamOutputs(node.id, definition, nodes)
  return (
    <aside className="workflow-inspector workflow-run-inspector">
      <Space className="workflow-inspector-heading" wrap>
        <Typography.Title level={5}>{node.name}</Typography.Title>
        <SnapshotTag mode={mode} />
      </Space>
      <RuntimeSummary node={node} execution={execution} observation={observation} />
      {execution?.result?.assertions.length ? (
        <AssertionEvidence items={execution.result.assertions} />
      ) : null}
      <ExecutionError execution={execution} />
      <MissingAttempt initialAttempt={initialAttempt} observations={observations} />
      <WorkflowNodeRelations node={node} definition={definition} onLocateNode={onLocateNode} />
      <ControlIterations
        output={execution?.output}
        projectId={projectId}
        executionId={executionId}
        nodeId={node.id}
      />
      <ObservationPicker
        observations={observations}
        selected={observation}
        onChange={(nextAttempt) => {
          setAttempt(nextAttempt)
          onSelectAttempt?.(nextAttempt)
        }}
      />
      <RuntimeTabs
        projectId={projectId}
        input={input}
        context={context}
        execution={execution}
        observation={observation}
      />
      <Typography.Paragraph type="secondary" className="workflow-redaction-note">
        请求、响应和变量按本次执行策略展示；开启脱敏时，敏感值会显示为占位符。
      </Typography.Paragraph>
    </aside>
  )
}

function useRuntimeAttempt(
  projectId: string | undefined,
  executionId: string | undefined,
  nodeId: string,
  initialAttempt: number | undefined,
  observations: WorkflowNodeObservation[],
) {
  return useRouteScopedState<number | undefined>(
    projectId ?? null,
    `${executionId}:${nodeId}:${initialAttempt}`,
    initialAttempt ?? observations.at(-1)?.attempt,
  )
}

function MissingAttempt({
  initialAttempt,
  observations,
}: {
  initialAttempt?: number
  observations: WorkflowNodeObservation[]
}) {
  if (!initialAttempt || observations.some((item) => item.attempt === initialAttempt)) return null
  return (
    <Alert
      type="warning"
      showIcon
      title="指定请求尝试未保存证据"
      description="已保留本次执行的节点结果；有请求证据时显示最后一条可用记录。"
    />
  )
}

type ControlItem = {
  input_index?: number
  definition_index?: number
  status: string
  test_verdict: string
  nodes: Array<{
    node_id: string
    instance_id?: string
    status: string
    error_code?: string | null
    error_message?: string | null
  }>
}

type ControlReport = {
  kind: 'iteration' | 'branch'
  paged: boolean
  items: ControlItem[]
  summary: Record<string, unknown>
}

function controlReport(output: unknown): ControlReport | null {
  if (typeof output !== 'object' || output === null) return null
  const summary = output as Record<string, unknown>
  const paged = summary.report_paged === true
  const kind = controlReportKind(summary)
  const rawItems = kind === 'branch' ? summary.branches : summary.items
  if (!paged && !Array.isArray(rawItems)) return null
  if (paged && summary.report_kind !== kind) return null
  const items = controlReportItems(rawItems, kind)
  return { kind, paged, items, summary }
}

function controlReportKind(summary: Record<string, unknown>): ControlReport['kind'] {
  return summary.report_kind === 'branch' || Array.isArray(summary.branches)
    ? 'branch'
    : 'iteration'
}

function controlReportItems(rawItems: unknown, kind: ControlReport['kind']): ControlItem[] {
  if (!Array.isArray(rawItems)) return []
  return rawItems.filter((item): item is ControlItem => isControlItem(item, kind))
}

function isControlItem(item: unknown, kind: ControlReport['kind']): item is ControlItem {
  if (typeof item !== 'object' || item === null) return false
  const value = item as Record<string, unknown>
  return (
    typeof value.status === 'string' &&
    Array.isArray(value.nodes) &&
    typeof value[kind === 'branch' ? 'definition_index' : 'input_index'] === 'number'
  )
}

function ControlIterations({
  output,
  projectId,
  executionId,
  nodeId,
}: {
  output: unknown
  projectId?: string
  executionId?: string
  nodeId: string
}) {
  const report = controlReport(output)
  const [selected, setSelected] = useState<number | undefined>(undefined)
  const [page, setPage] = useState(1)
  const { listed, detail, error } = useControlReportData(
    report,
    projectId,
    executionId,
    nodeId,
    page,
    selected,
  )
  if (!report) return null
  const pageSize = 20
  const visibleItems = visibleControlItems(report, listed, page, pageSize)
  const selectedItem = selectedControlItem(report, detail, selected)
  const total = report.paged
    ? (listed?.total ?? Number(report.summary.record_count ?? 0))
    : report.items.length
  const summary = report.summary
  return (
    <section
      aria-label={report.kind === 'branch' ? '并行分支详情' : '循环执行详情'}
      className="workflow-control-iterations"
    >
      <ControlReportSummary summary={summary} total={total} />
      <ControlReportAlerts
        report={report}
        listed={listed}
        projectId={projectId}
        executionId={executionId}
        error={error}
      />
      <ControlRecordSelector
        report={report}
        selected={selected}
        items={visibleItems}
        onChange={setSelected}
      />
      <ControlRecordPagination
        kind={report.kind}
        total={total}
        page={page}
        pageSize={pageSize}
        onChange={(nextPage) => {
          setPage(nextPage)
          setSelected(undefined)
        }}
      />
      <ControlRecordNodes item={selectedItem} projectId={projectId} executionId={executionId} />
    </section>
  )
}

function ControlReportSummary({
  summary,
  total,
}: {
  summary: Record<string, unknown>
  total: number
}) {
  return (
    <Typography.Text strong>
      已完成 {String(summary.completed_count ?? summary.started_count ?? total)}/
      {String(summary.input_count ?? total)}， 失败 {String(summary.failed_count ?? 0)}
      ，退出原因：{String(summary.termination_reason ?? '未知')}
    </Typography.Text>
  )
}

function ControlReportAlerts({
  report,
  listed,
  projectId,
  executionId,
  error,
}: {
  report: ControlReport
  listed: Page<WorkflowControlRecordSummary> | null
  projectId?: string
  executionId?: string
  error: string | null
}) {
  return (
    <>
      {report.paged && (!projectId || !executionId) && (
        <Alert type="warning" title="缺少执行上下文，无法加载轮次记录" />
      )}
      {report.paged && Number(report.summary.record_count ?? 0) > 0 && listed?.total === 0 && (
        <Alert type="error" title="执行摘要与轮次记录不一致，请核查原始执行报告" />
      )}
      {error && <Alert type="error" title={error} />}
    </>
  )
}

function ControlRecordSelector({
  report,
  selected,
  items,
  onChange,
}: {
  report: ControlReport
  selected: number | undefined
  items: ControlItem[]
  onChange: (value: number) => void
}) {
  return (
    <Select
      aria-label={report.kind === 'branch' ? '选择并行分支' : '选择循环轮次'}
      placeholder={report.kind === 'branch' ? '选择分支查看节点结果' : '选择轮次查看节点结果'}
      value={selected}
      options={items.map((item) => ({
        value: controlOrdinal(report.kind, item),
        label: controlOptionLabel(report.kind, item),
      }))}
      onChange={onChange}
    />
  )
}

function ControlRecordPagination({
  kind,
  total,
  page,
  pageSize,
  onChange,
}: {
  kind: ControlReport['kind']
  total: number
  page: number
  pageSize: number
  onChange: (value: number) => void
}) {
  if (total <= pageSize) return null
  return (
    <Pagination
      aria-label={kind === 'branch' ? '并行分支分页' : '循环轮次分页'}
      current={page}
      pageSize={pageSize}
      total={total}
      showSizeChanger={false}
      onChange={onChange}
    />
  )
}

function ControlRecordNodes({
  item,
  projectId,
  executionId,
}: {
  item: ControlItem | undefined
  projectId?: string
  executionId?: string
}) {
  return item?.nodes.map((node) => (
    <ControlRecordNode
      key={`${node.node_id}:${node.instance_id ?? ''}`}
      item={node}
      projectId={projectId}
      executionId={executionId}
    />
  ))
}

function useControlReportData(
  report: ControlReport | null,
  projectId: string | undefined,
  executionId: string | undefined,
  nodeId: string,
  page: number,
  selected: number | undefined,
) {
  const kind = report?.kind
  const paged = report?.paged ?? false
  const pageData = useControlPage(paged, kind, projectId, executionId, nodeId, page)
  const detailData = useControlDetail(paged, kind, projectId, executionId, nodeId, selected)
  return {
    listed: pageData.value,
    detail: detailData.value,
    error: pageData.error ?? detailData.error ?? null,
  }
}

function useControlPage(
  paged: boolean,
  kind: ControlReport['kind'] | undefined,
  projectId: string | undefined,
  executionId: string | undefined,
  nodeId: string,
  page: number,
) {
  const [listedState, setListedState] = useState<{
    key: string
    value?: Page<WorkflowControlRecordSummary>
    error?: string
  } | null>(null)
  const pageKey = `${projectId}:${executionId}:${nodeId}:${kind}:${page}`
  useEffect(() => {
    if (!paged || !kind || !projectId || !executionId) return
    let active = true
    void listWorkflowControlRecords(projectId, executionId, nodeId, kind, page)
      .then((value) => {
        if (active) setListedState({ key: pageKey, value })
      })
      .catch((reason: unknown) => {
        if (active) setListedState({ key: pageKey, error: apiErrorMessage(reason) })
      })
    return () => {
      active = false
    }
  }, [paged, kind, projectId, executionId, nodeId, page, pageKey])
  return {
    value: listedState?.key === pageKey ? (listedState.value ?? null) : null,
    error: listedState?.key === pageKey ? listedState.error : undefined,
  }
}

function useControlDetail(
  paged: boolean,
  kind: ControlReport['kind'] | undefined,
  projectId: string | undefined,
  executionId: string | undefined,
  nodeId: string,
  selected: number | undefined,
) {
  const [detailState, setDetailState] = useState<{
    key: string
    value?: WorkflowControlRecordDetail
    error?: string
  } | null>(null)
  const detailKey = `${projectId}:${executionId}:${nodeId}:${kind}:${selected}`
  useEffect(() => {
    if (!paged || !kind || !projectId || !executionId || selected === undefined) return
    let active = true
    void getWorkflowControlRecord(projectId, executionId, nodeId, kind, selected)
      .then((value) => {
        if (active) setDetailState({ key: detailKey, value })
      })
      .catch((reason: unknown) => {
        if (active) setDetailState({ key: detailKey, error: apiErrorMessage(reason) })
      })
    return () => {
      active = false
    }
  }, [paged, kind, projectId, executionId, nodeId, selected, detailKey])
  return {
    value: detailState?.key === detailKey ? (detailState.value ?? null) : null,
    error: detailState?.key === detailKey ? detailState.error : undefined,
  }
}

function controlOrdinal(kind: ControlReport['kind'], item: ControlItem): number | undefined {
  return kind === 'branch' ? item.definition_index : item.input_index
}

function controlOptionLabel(kind: ControlReport['kind'], item: ControlItem): string {
  const index = (controlOrdinal(kind, item) ?? 0) + 1
  return kind === 'branch'
    ? `分支 ${index} · ${item.test_verdict ?? item.status}`
    : `第 ${index} 项 · ${item.test_verdict ?? item.status}`
}

function visibleControlItems(
  report: ControlReport,
  listed: Page<WorkflowControlRecordSummary> | null,
  page: number,
  pageSize: number,
): ControlItem[] {
  if (!report.paged) return report.items.slice((page - 1) * pageSize, page * pageSize)
  if (listed?.page !== page) return []
  return listed.items.map((item) => ({
    ...item,
    [report.kind === 'branch' ? 'definition_index' : 'input_index']: item.ordinal,
    nodes: [],
  }))
}

function selectedControlItem(
  report: ControlReport,
  detail: WorkflowControlRecordDetail | null,
  selected: number | undefined,
): ControlItem | undefined {
  if (!report.paged) {
    return report.items.find((item) => controlOrdinal(report.kind, item) === selected)
  }
  return selected !== undefined && detail?.ordinal === selected
    ? (detail.payload as ControlItem)
    : undefined
}

function ControlRecordNode({
  item,
  projectId,
  executionId,
}: {
  item: ControlItem['nodes'][number]
  projectId?: string
  executionId?: string
}) {
  return (
    <div>
      <Typography.Text>
        {item.node_id} · {item.status}
      </Typography.Text>
      {item.error_message && (
        <Alert type="error" title={item.error_message} description={item.error_code} />
      )}
      {item.instance_id && projectId && executionId && (
        <ControlInstanceDetail
          projectId={projectId}
          executionId={executionId}
          instanceId={item.instance_id}
        />
      )}
    </div>
  )
}

function ControlInstanceDetail({
  projectId,
  executionId,
  instanceId,
}: {
  projectId: string
  executionId: string
  instanceId: string
}) {
  const [open, setOpen] = useState(false)
  const [checkpoint, setCheckpoint] = useState<ExecutionCheckpoint | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    if (!open) return
    let active = true
    void getWorkflowInstance(projectId, executionId, instanceId)
      .then((value) => {
        if (active) setCheckpoint(value)
      })
      .catch((reason: unknown) => {
        if (active) setError(apiErrorMessage(reason))
      })
    return () => {
      active = false
    }
  }, [open, projectId, executionId, instanceId])
  return (
    <div>
      <Button type="link" onClick={() => setOpen((value) => !value)}>
        {open ? '收起实例详情' : '查看实例详情'}
      </Button>
      {open && error && <Alert type="error" title={error} />}
      {open && checkpoint && (
        <>
          <Typography.Text>
            {checkpoint.node_name} · {checkpoint.status}
          </Typography.Text>
          <Payload title="实例输出" value={checkpoint.output} projectId={projectId} />
          <Payload title="实例请求、响应与校验" value={checkpoint.result} projectId={projectId} />
        </>
      )}
    </div>
  )
}

function SnapshotTag({ mode }: { mode: RuntimeInspectorProps['mode'] }) {
  if (mode !== 'history') return null
  return (
    <Tag icon={<LockOutlined />} color="gold">
      历史快照
    </Tag>
  )
}

function RuntimeSummary({
  node,
  execution,
  observation,
}: {
  node: WorkflowNode
  execution: WorkflowNodeExecution | undefined
  observation: WorkflowNodeObservation | undefined
}) {
  return (
    <Descriptions
      size="small"
      column={1}
      items={[
        {
          key: 'status',
          label: '状态',
          children: <RuntimeStatus status={execution?.status ?? 'pending'} />,
        },
        { key: 'type', label: '节点类型', children: execution?.node_type ?? node.type },
        { key: 'attempts', label: '尝试次数', children: execution?.attempts ?? '未提供' },
        {
          key: 'duration',
          label: '耗时',
          children: (
            <Duration
              value={nodeDuration(execution, observation)}
              running={execution?.status === 'running'}
            />
          ),
        },
      ]}
    />
  )
}

function ObservationPicker({
  observations,
  selected,
  onChange,
}: {
  observations: WorkflowNodeObservation[]
  selected: WorkflowNodeObservation | undefined
  onChange: (attempt: number) => void
}) {
  if (observations.length <= 1) return null
  return (
    <Select
      aria-label="请求尝试"
      className="workflow-attempt-select"
      value={selected?.attempt}
      options={observations.map((item) => ({
        value: item.attempt,
        label: `第 ${item.attempt} 次 · ${attemptLabel(item)}`,
      }))}
      onChange={onChange}
    />
  )
}

function RuntimeTabs({
  projectId,
  input,
  context,
  execution,
  observation,
}: {
  projectId?: string
  input: Record<string, unknown>
  context: Record<string, unknown>
  execution: WorkflowNodeExecution | undefined
  observation: WorkflowNodeObservation | undefined
}) {
  return (
    <Tabs
      defaultActiveKey={execution?.status === 'failed' ? 'diagnostics' : 'input'}
      size="small"
      items={[
        {
          key: 'input',
          label: '输入',
          children: <InputDetail input={input} context={context} projectId={projectId} />,
        },
        { key: 'request', label: '请求', children: <RequestDetail observation={observation} /> },
        { key: 'response', label: '响应', children: <ResponseDetail observation={observation} /> },
        {
          key: 'output',
          label: '输出',
          children: <Payload title="节点输出" value={execution?.output} projectId={projectId} />,
        },
        {
          key: 'diagnostics',
          label: '校验/错误',
          children: <DiagnosticsDetail execution={execution} />,
        },
      ]}
    />
  )
}

function InputDetail({
  input,
  context,
  projectId,
}: {
  input: Record<string, unknown>
  context: Record<string, unknown>
  projectId?: string
}) {
  return (
    <>
      <Payload title="上游节点输出" value={input} projectId={projectId} />
      <Payload title="执行变量" value={resolvedVariables(context)} projectId={projectId} />
    </>
  )
}

function RequestDetail({ observation }: { observation: WorkflowNodeObservation | undefined }) {
  if (!observation) return <EmptyPayload text="该节点没有 HTTP 请求记录" />
  return (
    <>
      <HttpRequestSummary observation={observation} />
      <Payload title="变量映射" value={observation.mappings} />
    </>
  )
}

function ResponseDetail({ observation }: { observation: WorkflowNodeObservation | undefined }) {
  const response = observation?.response
  if (!observation || !response) {
    return <EmptyPayload text={observation?.error_message ?? '暂无响应数据'} />
  }
  return (
    <>
      <Space wrap className="workflow-response-summary">
        <Tag color={response.status_code < 400 ? 'green' : 'red'}>HTTP {response.status_code}</Tag>
        <Tag>{formatBytes(response.size_bytes)}</Tag>
        <Tag icon={<ClockCircleOutlined />}>{formatDuration(observation.duration_ms)}</Tag>
      </Space>
      <Payload title="响应头" value={response.headers} />
      <Payload title="响应体" value={response.body} />
    </>
  )
}

function DiagnosticsDetail({ execution }: { execution: WorkflowNodeExecution | undefined }) {
  return (
    <>
      <Typography.Text strong>断言</Typography.Text>
      <Typography.Paragraph type="secondary">
        {execution?.result?.assertions.length ? '期望值和实际值见上方断言证据。' : '未提供断言证据'}
      </Typography.Paragraph>
      <Payload title="指标" value={execution?.result?.metrics ?? []} />
    </>
  )
}

function ExecutionError({ execution }: { execution: WorkflowNodeExecution | undefined }) {
  if (!execution?.error_message) return null
  return (
    <Alert
      type="error"
      showIcon
      title={execution.error_message}
      description={execution.error_code}
    />
  )
}

function EmptyRuntimeInspector({ mode }: { mode: RuntimeInspectorProps['mode'] }) {
  return (
    <aside className="workflow-inspector workflow-run-inspector">
      <Typography.Title level={5}>
        {mode === 'history' ? '历史节点详情' : '运行节点详情'}
      </Typography.Title>
      <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="选择画布节点查看输入输出" />
    </aside>
  )
}

function HttpRequestSummary({ observation }: { observation: WorkflowNodeObservation }) {
  return (
    <>
      <Space wrap className="workflow-request-line">
        <Tag color="blue">{observation.request.method}</Tag>
        <Typography.Text copyable>{observation.request.url}</Typography.Text>
      </Space>
      <Payload title="请求头" value={observation.request.headers} />
      <Payload title="请求体" value={observation.request.body} />
    </>
  )
}

function Payload({
  title,
  value,
  projectId,
}: {
  title: string
  value: unknown
  projectId?: string
}) {
  const [downloadError, setDownloadError] = useState<string | null>(null)
  const references = workflowOutputReferences(value)
  return (
    <section className="workflow-runtime-payload">
      <Typography.Text strong>{title}</Typography.Text>
      {references.map((reference) => (
        <div key={reference.artifactId}>
          <Typography.Text type="secondary">
            大型响应已保存为对象引用（{formatBytes(reference.sizeBytes)}）
          </Typography.Text>
          {projectId && (
            <Button
              type="link"
              onClick={() => {
                setDownloadError(null)
                void downloadWorkflowOutput(projectId, reference.artifactId).catch(
                  (error: unknown) => {
                    setDownloadError(apiErrorMessage(error))
                  },
                )
              }}
            >
              下载响应体
            </Button>
          )}
        </div>
      ))}
      {downloadError && <Alert type="error" title={`响应体不可用：${downloadError}`} />}
      <pre>{serialize(value)}</pre>
    </section>
  )
}

function workflowOutputReferences(
  value: unknown,
): Array<{ artifactId: string; sizeBytes: number }> {
  const found = new Map<string, number>()
  const visit = (item: unknown): void => {
    if (Array.isArray(item)) {
      item.forEach(visit)
      return
    }
    if (!isRecord(item)) return
    if (isResponseOutput(item)) {
      const reference = responseReference(item.body)
      if (reference) found.set(reference.artifactId, reference.sizeBytes)
      return
    }
    Object.values(item).forEach(visit)
  }
  visit(value)
  return Array.from(found, ([artifactId, sizeBytes]) => ({ artifactId, sizeBytes }))
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function isResponseOutput(value: Record<string, unknown>): boolean {
  return (
    typeof value.status_code === 'number' &&
    typeof value.size_bytes === 'number' &&
    isRecord(value.headers) &&
    'body' in value
  )
}

function responseReference(body: unknown): { artifactId: string; sizeBytes: number } | null {
  if (!isRecord(body) || !isRecord(body.__flowtest_workflow_output_ref__)) return null
  const metadata = body.__flowtest_workflow_output_ref__
  if (typeof metadata.artifact_id !== 'string' || typeof metadata.size_bytes !== 'number') {
    return null
  }
  return { artifactId: metadata.artifact_id, sizeBytes: metadata.size_bytes }
}

function EmptyPayload({ text }: { text: string }) {
  return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={text} />
}

function RuntimeStatus({ status }: { status: WorkflowNodeExecution['status'] }) {
  const colors: Record<WorkflowNodeExecution['status'], string> = {
    pending: 'default',
    running: 'processing',
    passed: 'success',
    failed: 'error',
    skipped: 'default',
    cancelled: 'warning',
  }
  return <Tag color={colors[status]}>{status}</Tag>
}

function selectedObservation(
  observations: WorkflowNodeObservation[],
  attempt: number | undefined,
): WorkflowNodeObservation | undefined {
  return observations.find((item) => item.attempt === attempt) ?? observations.at(-1)
}

function upstreamOutputs(
  nodeId: string,
  definition: WorkflowDefinition,
  nodes: WorkflowNodeExecution[],
): Record<string, unknown> {
  const sources = new Set(
    definition.edges.filter((edge) => edge.target === nodeId).map((edge) => edge.source),
  )
  return Object.fromEntries(
    nodes.filter((item) => sources.has(item.node_id)).map((item) => [item.name, item.output]),
  )
}

function resolvedVariables(context: Record<string, unknown>): unknown {
  return context.resolved_variables ?? context
}

function attemptLabel(observation: WorkflowNodeObservation): string {
  if (observation.error_message) return observation.error_message
  if (observation.response) return `HTTP ${observation.response.status_code}`
  return '无响应'
}

function nodeDuration(
  execution: WorkflowNodeExecution | undefined,
  observation: WorkflowNodeObservation | undefined,
): number | null {
  if (observation) return observation.duration_ms
  if (!execution?.started_at || !execution.completed_at) return null
  return new Date(execution.completed_at).getTime() - new Date(execution.started_at).getTime()
}

function Duration({ value, running }: { value: number | null; running: boolean }) {
  return (
    <span className="workflow-volatile-value">
      {value === null ? (running ? '计时中' : '未提供') : formatDuration(value)}
    </span>
  )
}

function formatDuration(value: number): string {
  if (value < 1000) return `${Math.round(value * 100) / 100} ms`
  return `${Math.round(value / 10) / 100} s`
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${Math.round(value / 102.4) / 10} KB`
  return `${Math.round(value / 104857.6) / 10} MB`
}

function serialize(value: unknown): string {
  if (value === undefined || value === null) return '—'
  if (typeof value === 'string') return value
  return JSON.stringify(value, null, 2)
}
