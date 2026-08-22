import { ClockCircleOutlined, LockOutlined } from '@ant-design/icons'
import { Alert, Descriptions, Empty, Select, Space, Tabs, Tag, Typography } from 'antd'
import { useState } from 'react'

import type {
  WorkflowDefinition,
  WorkflowNode,
  WorkflowNodeExecution,
  WorkflowNodeObservation,
} from '../lib/api'

type RuntimeInspectorProps = {
  mode: 'run' | 'history'
  node: WorkflowNode | null
  definition: WorkflowDefinition
  execution: WorkflowNodeExecution | undefined
  nodes: WorkflowNodeExecution[]
  context: Record<string, unknown>
}

export default function WorkflowRunInspector({
  mode,
  node,
  definition,
  execution,
  nodes,
  context,
}: RuntimeInspectorProps) {
  if (!node) return <EmptyRuntimeInspector mode={mode} />
  return (
    <RuntimeNodeDetail
      key={`${mode}:${node.id}`}
      mode={mode}
      node={node}
      definition={definition}
      execution={execution}
      nodes={nodes}
      context={context}
    />
  )
}

function RuntimeNodeDetail({
  mode,
  node,
  definition,
  execution,
  nodes,
  context,
}: RuntimeInspectorProps & { node: WorkflowNode }) {
  const observations = execution?.result?.observations ?? []
  const [attempt, setAttempt] = useState(observations.at(-1)?.attempt)
  const observation = selectedObservation(observations, attempt)
  const input = upstreamOutputs(node.id, definition, nodes)
  return (
    <aside className="workflow-inspector workflow-run-inspector">
      <Space className="workflow-inspector-heading" wrap>
        <Typography.Title level={5}>{node.name}</Typography.Title>
        <SnapshotTag mode={mode} />
      </Space>
      <RuntimeSummary node={node} execution={execution} observation={observation} />
      <ObservationPicker observations={observations} selected={observation} onChange={setAttempt} />
      <RuntimeTabs
        input={input}
        context={context}
        execution={execution}
        observation={observation}
      />
      <Typography.Paragraph type="secondary" className="workflow-redaction-note">
        请求、响应和变量均为执行时脱敏快照，不展示 Authorization、Cookie、Token 等敏感值。
      </Typography.Paragraph>
    </aside>
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
        { key: 'attempts', label: '尝试次数', children: execution?.attempts ?? 0 },
        {
          key: 'duration',
          label: '耗时',
          children: <Duration value={nodeDuration(execution, observation)} />,
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
  input,
  context,
  execution,
  observation,
}: {
  input: Record<string, unknown>
  context: Record<string, unknown>
  execution: WorkflowNodeExecution | undefined
  observation: WorkflowNodeObservation | undefined
}) {
  return (
    <Tabs
      size="small"
      items={[
        { key: 'input', label: '输入', children: <InputDetail input={input} context={context} /> },
        { key: 'request', label: '请求', children: <RequestDetail observation={observation} /> },
        { key: 'response', label: '响应', children: <ResponseDetail observation={observation} /> },
        {
          key: 'output',
          label: '输出',
          children: <Payload title="节点输出" value={execution?.output} />,
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
}: {
  input: Record<string, unknown>
  context: Record<string, unknown>
}) {
  return (
    <>
      <Payload title="上游节点输出" value={input} />
      <Payload title="执行变量" value={resolvedVariables(context)} />
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
      <ExecutionError execution={execution} />
      <Payload title="断言" value={execution?.result?.assertions ?? []} />
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

function Payload({ title, value }: { title: string; value: unknown }) {
  return (
    <section className="workflow-runtime-payload">
      <Typography.Text strong>{title}</Typography.Text>
      <pre>{serialize(value)}</pre>
    </section>
  )
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

function Duration({ value }: { value: number | null }) {
  return <span>{value === null ? '计时中' : formatDuration(value)}</span>
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
