import { ArrowLeftOutlined, DownloadOutlined, NodeIndexOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Empty,
  Select,
  Space,
  Spin,
  Tabs,
  Tag,
  Typography,
} from 'antd'
import { useRouteScopedState } from '../../lib/use-route-scoped-state'
import { Link } from 'react-router-dom'
import { useEffect, useRef } from 'react'

import {
  apiErrorMessage,
  type ReportExecutionDetail,
  type ReportNode,
  type WorkflowNodeObservation,
} from '../../lib/api'
import AssertionEvidence from '../evidence/AssertionEvidence'
import { reportAssertionEvidence } from '../evidence/assertion-model'
import { workflowExecutionPath } from '../workflows/execution-navigation'
import { getWorkflowExecution } from '../workflows/workflow-service'
import type { ExecutionEvidenceLocation } from '../workflows/execution-navigation'
import ExecutionCheckpointLog from '../workflows/ExecutionCheckpointLog'
import { WorkflowControlEvidence, WorkflowEvidencePayload } from '../../flow/WorkflowRunInspector'

type WorkspaceProps = {
  projectId: string
  executionId: string
  detail: ReportExecutionDetail | undefined
  loading: boolean
  error: unknown
  nodeId: string | null
  attempt?: number
  evidence?: ExecutionEvidenceLocation
  onSelectEvidence?: (evidence: ExecutionEvidenceLocation) => void
  onSelectNode: (nodeId: string) => void
  onSelectAttempt: (nodeId: string, attempt: number) => void
  onBack: () => void
  onRetry: () => void
  onExport: () => void
}

export default function ReportExecutionWorkspace(props: WorkspaceProps) {
  const { detail, executionId, nodeId } = props
  const node = selectReportNode(detail?.nodes ?? [], nodeId)
  const snapshot = useQuery({
    queryKey: ['workflow-execution', props.projectId, executionId],
    queryFn: () => getWorkflowExecution(props.projectId, executionId, true),
    enabled: Boolean(detail),
  })
  const workflowPath = workflowExecutionPath(props.projectId, {
    executionId,
    workflowId: detail?.summary.workflow_id,
    nodeId: node?.node_id,
    attempt: props.attempt,
    ...props.evidence,
  })
  return (
    <section className="report-execution-workspace" aria-label="执行报告详情">
      <nav className="execution-object-tabs" aria-label="关联工作对象">
        <ReportWorkflowObjectLink workflowPath={workflowPath} detail={detail} />
        <span aria-current="page">执行 {executionId.slice(0, 8)}</span>
      </nav>
      <ReportExecutionHeading
        props={props}
        environment={snapshotEnvironment(snapshot.data?.execution.snapshot)}
      />
      {props.loading && (
        <Spin description="正在加载当次执行证据">
          <div className="report-loading-placeholder" />
        </Spin>
      )}
      {Boolean(props.error) && (
        <Alert
          type="error"
          showIcon
          title="执行报告加载失败"
          description={apiErrorMessage(props.error)}
          action={<Button onClick={props.onRetry}>重试</Button>}
        />
      )}
      {detail && (
        <ReportExecutionBody
          props={props}
          detail={detail}
          node={node}
          workflowPath={workflowPath}
          snapshotError={snapshot.isError}
          onRetrySnapshot={() => void snapshot.refetch()}
        />
      )}
    </section>
  )
}

function ReportWorkflowObjectLink({
  workflowPath,
  detail,
}: {
  workflowPath: string
  detail: ReportExecutionDetail | undefined
}) {
  return <Link to={workflowPath}>{detail?.summary.workflow_name ?? '流程快照'}</Link>
}

function ReportExecutionHeading({
  props,
  environment,
}: {
  props: WorkspaceProps
  environment: string
}) {
  const { detail, executionId } = props
  return (
    <header className="report-execution-heading">
      <div>
        <Typography.Text type="secondary">执行报告详情 · 历史只读</Typography.Text>
        <Typography.Title level={2}>{detail?.summary.workflow_name ?? '执行报告'}</Typography.Title>
        <Space wrap>
          <Tag>执行 {executionId.slice(0, 8)}</Tag>
          {detail && <Tag>执行版本 v{detail.summary.workflow_version}</Tag>}
          <Tag>环境：{environment}</Tag>
          {detail && <ReportStatus status={detail.summary.status} />}
        </Space>
      </div>
      <Space wrap>
        <Button aria-label="返回执行列表" icon={<ArrowLeftOutlined />} onClick={props.onBack}>
          返回执行列表
        </Button>
        <Button icon={<DownloadOutlined />} disabled={!detail} onClick={props.onExport}>
          导出 HTML
        </Button>
      </Space>
    </header>
  )
}

function ReportExecutionBody({
  props,
  detail,
  node,
  workflowPath,
  snapshotError,
  onRetrySnapshot,
}: {
  props: WorkspaceProps
  detail: ReportExecutionDetail
  node: ReportNode | undefined
  workflowPath: string
  snapshotError: boolean
  onRetrySnapshot: () => void
}) {
  const { executionId, nodeId } = props
  return (
    <div className="report-execution-grid">
      <ReportTrajectory
        nodes={detail.nodes}
        selectedId={node?.node_id}
        onSelect={props.onSelectNode}
      />
      <div className="report-execution-evidence">
        {nodeId && !detail.nodes.some((item) => item.node_id === nodeId) && (
          <Alert
            type="warning"
            showIcon
            title="指定节点不在本次报告中"
            description="已显示本次运行的首个失败节点或首个节点，请从执行轨迹重新选择。"
          />
        )}
        {node ? (
          <ReportNodeEvidence
            key={`${executionId}:${node.id}`}
            node={node}
            workflowPath={workflowPath}
            initialAttempt={props.attempt}
            onSelectAttempt={(attempt) => props.onSelectAttempt(node.node_id, attempt)}
            projectId={props.projectId}
            executionId={executionId}
            evidence={props.evidence}
            onSelectEvidence={props.onSelectEvidence}
          />
        ) : (
          <Card>
            <Empty description="本次执行尚无节点证据" />
          </Card>
        )}
        <Card title="冻结上下文" className="report-frozen-context">
          <Descriptions
            size="small"
            column={{ xs: 1, sm: 2 }}
            items={[
              { key: 'run', label: '执行记录', children: executionId },
              {
                key: 'version',
                label: '执行版本',
                children: `v${detail.summary.workflow_version}`,
              },
              {
                key: 'time',
                label: '开始时间',
                children: new Date(detail.summary.started_at).toLocaleString(),
              },
              {
                key: 'duration',
                label: '执行耗时',
                children:
                  detail.summary.duration_ms === null
                    ? '未提供'
                    : `${detail.summary.duration_ms} ms`,
              },
            ]}
          />
          <Typography.Paragraph type="secondary">
            这里展示当次执行保存的证据。定位画布会打开同一次执行的只读快照，当前草稿不会覆盖历史数据。
          </Typography.Paragraph>
          {snapshotError && (
            <Alert
              type="warning"
              title="执行环境暂不可用，已加载的报告证据仍可查看"
              action={
                <Button size="small" onClick={onRetrySnapshot}>
                  重试环境信息
                </Button>
              }
            />
          )}
        </Card>
        {detail.dataset_children.length > 0 && (
          <Card title="数据集子执行">
            <Space wrap>
              {detail.dataset_children.map((child) => (
                <Link key={child.id} to={`?execution=${encodeURIComponent(child.id)}`}>
                  {child.workflow_name} · {child.status}
                </Link>
              ))}
            </Space>
          </Card>
        )}
      </div>
    </div>
  )
}

function selectReportNode(nodes: ReportNode[], nodeId: string | null): ReportNode | undefined {
  return (
    nodes.find((node) => node.node_id === nodeId) ??
    nodes.find((node) => node.status === 'failed') ??
    nodes[0]
  )
}

function ReportTrajectory({
  nodes,
  selectedId,
  onSelect,
}: {
  nodes: ReportNode[]
  selectedId?: string
  onSelect: (nodeId: string) => void
}) {
  const navigation = useRef<HTMLElement>(null)
  useEffect(() => {
    const nav = navigation.current
    const selected = nav?.querySelector<HTMLElement>('[aria-pressed="true"]')
    if (!nav || !selected || nav.scrollWidth <= nav.clientWidth) return
    const bounds = nav.getBoundingClientRect()
    const target = selected.getBoundingClientRect()
    nav.scrollLeft += target.left - bounds.left - (nav.clientWidth - target.width) / 2
  }, [selectedId])
  return (
    <aside className="report-trajectory" aria-label="执行轨迹">
      <header>
        <Typography.Text strong>执行轨迹</Typography.Text>
        <Tag>{nodes.length}</Tag>
      </header>
      <nav ref={navigation}>
        {nodes.map((node) => (
          <button
            key={node.id}
            type="button"
            aria-pressed={node.node_id === selectedId}
            className={`report-trajectory-node is-${node.status}`}
            onClick={() => onSelect(node.node_id)}
          >
            <span>
              <ReportStatus status={node.status} />
              <strong>{node.name}</strong>
            </span>
            <small>
              {node.duration_ms === null ? '耗时未提供' : `${node.duration_ms} ms`} · 尝试{' '}
              {node.attempts}
            </small>
          </button>
        ))}
      </nav>
      <Typography.Text type="secondary">选择节点查看当次请求、响应与校验证据。</Typography.Text>
    </aside>
  )
}

function ReportNodeEvidence({
  node,
  workflowPath,
  initialAttempt,
  onSelectAttempt,
  projectId,
  executionId,
  evidence,
  onSelectEvidence,
}: {
  node: ReportNode
  workflowPath: string
  initialAttempt?: number
  onSelectAttempt: (attempt: number) => void
  projectId: string
  executionId: string
  evidence?: ExecutionEvidenceLocation
  onSelectEvidence?: (evidence: ExecutionEvidenceLocation) => void
}) {
  const observations = node.observations ?? []
  const [attempt, setAttempt] = useRouteScopedState<number | undefined>(
    null,
    String(initialAttempt),
    initialAttempt ?? observations.at(-1)?.attempt,
  )
  const observation = observations.find((item) => item.attempt === attempt) ?? observations.at(-1)
  const assertions = reportAssertionEvidence(node.assertion, node.name)
  return (
    <Card
      title={
        <Space wrap>
          <Typography.Text strong>{node.name}</Typography.Text>
          <ReportStatus status={node.status} />
        </Space>
      }
      extra={
        <Link aria-label="定位画布" className="report-locate-link" to={workflowPath}>
          <NodeIndexOutlined /> 定位画布
        </Link>
      }
    >
      {node.error_message && (
        <Alert
          type="error"
          showIcon
          title={node.error_message}
          description={node.error_code}
          className="report-node-error"
        />
      )}
      {assertions.length > 0 && (
        <AssertionEvidence items={assertions} source={`${node.name} (${node.node_id})`} />
      )}
      <MissingReportAttempt attempt={initialAttempt} observations={observations} />
      <Space wrap className="report-node-context">
        <Tag>{node.node_type}</Tag>
        <Tag>尝试次数 {node.attempts}</Tag>
        <Tag>节点耗时 {node.duration_ms === null ? '未提供' : `${node.duration_ms} ms`}</Tag>
        {observations.length > 0 && (
          <Select
            aria-label="报告请求尝试"
            value={observation?.attempt}
            onChange={(nextAttempt) => {
              setAttempt(nextAttempt)
              onSelectAttempt(nextAttempt)
            }}
            options={observations.map((item) => ({
              value: item.attempt,
              label: `第 ${item.attempt} 次请求${item.response ? ` · HTTP ${item.response.status_code}` : ' · 无响应'}`,
            }))}
          />
        )}
      </Space>
      <WorkflowControlEvidence
        output={node.output}
        projectId={projectId}
        executionId={executionId}
        nodeId={node.node_id}
        evidence={evidence}
        onSelectEvidence={onSelectEvidence}
      />
      <Tabs
        items={[
          ...reportEvidenceTabs(node, observation, projectId),
          {
            key: 'output',
            label: '输出',
            children: (
              <ReportPayload title="当次节点输出" value={node.output} projectId={projectId} />
            ),
          },
          {
            key: 'checkpoints',
            label: '检查点与日志',
            children: (
              <ExecutionCheckpointLog
                projectId={projectId}
                executionId={executionId}
                running={node.status === 'running'}
              />
            ),
          },
        ]}
      />
    </Card>
  )
}

function MissingReportAttempt({
  attempt,
  observations,
}: {
  attempt: number | undefined
  observations: WorkflowNodeObservation[]
}) {
  if (attempt === undefined || observations.some((item) => item.attempt === attempt)) return null
  return (
    <Alert
      type="warning"
      showIcon
      title="指定请求尝试不在本次证据中"
      description="已显示最近可用的请求记录；没有请求记录时展示节点汇总。请从请求尝试选择器重新选择。"
    />
  )
}

function reportEvidenceTabs(
  node: ReportNode,
  observation: WorkflowNodeObservation | undefined,
  projectId: string,
) {
  return [
    {
      key: 'response',
      label: '响应',
      children: (
        <ReportPayload
          title="本节点响应"
          value={observation ? observation.response : node.response}
          projectId={projectId}
        />
      ),
    },
    {
      key: 'request',
      label: '请求',
      children: (
        <ReportPayload
          title="本节点实际请求"
          value={observation ? observation.request : node.request}
          projectId={projectId}
        />
      ),
    },
    {
      key: 'extraction',
      label: '提取',
      children: <ReportPayload title="提取结果" value={node.extraction} />,
    },
    {
      key: 'assertion',
      label: '断言',
      children: <ReportPayload title="断言原始证据" value={node.assertion} />,
    },
    {
      key: 'mapping',
      label: '变量映射',
      children: (
        <ReportPayload
          title="当次变量映射"
          value={observation ? observation.mappings : node.input_mappings}
        />
      ),
    },
  ]
}

function ReportPayload({
  title,
  value,
  projectId,
}: {
  title: string
  value: unknown
  projectId?: string
}) {
  return (
    <section className="report-payload">
      <Typography.Text strong>{title}</Typography.Text>
      {value === null || value === undefined ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="本节点未提供此项证据" />
      ) : (
        <WorkflowEvidencePayload title="证据内容" value={value} projectId={projectId} />
      )}
    </section>
  )
}

function snapshotEnvironment(snapshot: Record<string, unknown> | undefined): string {
  const environment = snapshot?.environment
  if (
    environment &&
    typeof environment === 'object' &&
    'name' in environment &&
    typeof environment.name === 'string'
  )
    return environment.name
  return '未提供'
}

function ReportStatus({ status }: { status: string }) {
  const labels: Readonly<Record<string, string>> = {
    queued: '排队中',
    pending: '待执行',
    running: '执行中',
    passed: '通过',
    failed: '失败',
    skipped: '已跳过',
    cancelled: '已取消',
  }
  const colors: Readonly<Record<string, string>> = {
    passed: 'success',
    failed: 'error',
    running: 'processing',
    cancelled: 'warning',
  }
  return <Tag color={colors[status]}>{labels[status] ?? status}</Tag>
}
