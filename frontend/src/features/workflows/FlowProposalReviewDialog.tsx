import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  App,
  Button,
  Card,
  Descriptions,
  Empty,
  Modal,
  Segmented,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd'
import { useMemo, useState } from 'react'

import WorkflowDesigner, { type ProposalGraphStatus } from '../../flow/WorkflowDesigner'
import {
  apiErrorMessage,
  type ApiDefinition,
  type Artifact,
  type Credential,
  type FlowSpecVisualProposal,
  type IntegrationPlan,
  type Workflow,
  type WorkflowDefinition,
} from '../../lib/api'
import type { EventSource, SchemaArtifact } from '../protocols/protocol-service'
import {
  applyFlowSpec,
  getVisualFlowProposal,
  listFlowSpecChangeSets,
  reviewFlowSpec,
} from './flow-spec-service'

type ProposalResources = {
  apis: ApiDefinition[]
  artifacts: Artifact[]
  workflows: Workflow[]
  credentials: Credential[]
  graphqlSchemas: SchemaArtifact[]
  grpcDescriptors: SchemaArtifact[]
  eventSources: EventSource[]
}

type FlowProposalReviewDialogProps = {
  open: boolean
  projectId: string
  resources: ProposalResources
  onClose: () => void
  onApplied: (workflowId: string) => void
  onOpenRawMapping: (proposal: FlowSpecVisualProposal) => void
}

export default function FlowProposalReviewDialog(props: FlowProposalReviewDialogProps) {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const [selectedId, setSelectedId] = useState<string>()
  const [graphView, setGraphView] = useState<'existing' | 'proposed'>('proposed')
  const [busy, setBusy] = useState(false)
  const [visualOverride, setVisualOverride] = useState<FlowSpecVisualProposal>()
  const proposals = useQuery({
    queryKey: ['flow-proposals', props.projectId],
    queryFn: () => listFlowSpecChangeSets(props.projectId),
    enabled: props.open,
  })
  const candidates = useMemo(
    () => (proposals.data?.items ?? []).filter((item) => item.source_ref?.startsWith('mcp://')),
    [proposals.data],
  )
  const proposalId = candidates.some((item) => item.id === selectedId)
    ? selectedId
    : candidates.at(0)?.id

  const visual = useQuery({
    queryKey: ['flow-proposal', props.projectId, proposalId],
    queryFn: () => getVisualFlowProposal(props.projectId, requiredId(proposalId)),
    enabled: props.open && Boolean(proposalId),
    placeholderData: (previous) => previous,
  })
  const displayedVisual = selectedVisual(visual.data, visualOverride)

  async function review(accept: boolean, currentVisual: FlowSpecVisualProposal): Promise<void> {
    if (!proposalId) return
    await act(
      async () => {
        const reviewed = await reviewFlowSpec(
          props.projectId,
          proposalId,
          accept,
          accept ? '可视化流程提案人工接受' : '可视化流程提案人工拒绝',
        )
        queryClient.setQueryData<FlowSpecVisualProposal>(
          ['flow-proposal', props.projectId, proposalId],
          (current) => (current ? { ...current, proposal: reviewed } : current),
        )
        setVisualOverride({ ...currentVisual, proposal: reviewed })
      },
      accept ? '流程提案已接受' : '流程提案已拒绝',
    )
  }

  async function apply(currentVisual: FlowSpecVisualProposal): Promise<void> {
    if (!proposalId) return
    await act(async () => {
      const result = await applyFlowSpec(props.projectId, proposalId)
      const appliedVisual = {
        ...currentVisual,
        proposal: { ...currentVisual.proposal, applied_at: result.applied_at },
      }
      queryClient.setQueryData<FlowSpecVisualProposal>(
        ['flow-proposal', props.projectId, proposalId],
        appliedVisual,
      )
      setVisualOverride(appliedVisual)
      await queryClient.invalidateQueries({ queryKey: ['workflows', props.projectId] })
      props.onApplied(result.workflow_id)
    }, '流程提案已应用到工作流草稿，可继续安全编辑')
  }

  async function act(operation: () => Promise<void>, success: string): Promise<void> {
    setBusy(true)
    try {
      await operation()
      void message.success(success)
    } catch (error) {
      void message.error(apiErrorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      title="外部 LLM / MCP 可视化流程提案"
      open={props.open}
      width="min(1560px, 96vw)"
      footer={null}
      destroyOnHidden
      onCancel={props.onClose}
    >
      <Space orientation="vertical" size={16} style={{ width: '100%' }}>
        <Alert
          showIcon
          type="info"
          title="流程提案只会进入 AIChangeSet 草稿；本视图没有发布、执行或自动应用操作。"
          description="先检查流程图、映射、断言、证据、置信度与未决项，再由人工接受；应用后进入现有工作流设计器草稿继续安全编辑。"
        />
        <Select
          aria-label="流程提案"
          style={{ width: '100%' }}
          loading={proposals.isLoading}
          placeholder="选择 MCP 流程提案"
          value={proposalId}
          options={candidates.map((item) => ({
            value: item.id,
            label: `${item.title} · ${changeSetStatusLabel(item.status)} · ${item.id.slice(0, 8)}`,
          }))}
          onChange={(value) => {
            setSelectedId(value)
            setVisualOverride(undefined)
          }}
        />
        {!candidates.length && !proposals.isLoading ? (
          <Empty description="暂无 MCP 流程提案" />
        ) : null}
        {displayedVisual ? (
          <ProposalWorkspace
            proposal={displayedVisual}
            graphView={graphView}
            resources={props.resources}
            busy={busy}
            onGraphView={setGraphView}
            onReview={(accept) => review(accept, displayedVisual)}
            onApply={() => apply(displayedVisual)}
            onOpenRawMapping={props.onOpenRawMapping}
          />
        ) : null}
      </Space>
    </Modal>
  )
}

function ProposalWorkspace({
  proposal,
  graphView,
  resources,
  busy,
  onGraphView,
  onReview,
  onApply,
  onOpenRawMapping,
}: {
  proposal: FlowSpecVisualProposal
  graphView: 'existing' | 'proposed'
  resources: ProposalResources
  busy: boolean
  onGraphView: (value: 'existing' | 'proposed') => void
  onReview: (accept: boolean) => Promise<void>
  onApply: () => Promise<void>
  onOpenRawMapping: (proposal: FlowSpecVisualProposal) => void
}) {
  const changes = graphChanges(proposal.existing_definition, proposal.proposed_definition)
  const definition =
    graphView === 'existing' ? proposal.existing_definition : proposal.proposed_definition
  const nodeStatuses = graphView === 'existing' ? changes.existingNodes : changes.proposedNodes
  const edgeStatuses = graphView === 'existing' ? changes.existingEdges : changes.proposedEdges
  return (
    <Space orientation="vertical" size={16} style={{ width: '100%' }}>
      <ReviewActions
        proposal={proposal}
        busy={busy}
        onReview={onReview}
        onApply={onApply}
        onOpenRawMapping={onOpenRawMapping}
      />
      <Segmented
        aria-label="流程提案图视图"
        value={graphView}
        options={[
          { label: '现有流程图', value: 'existing' },
          { label: '提案流程图', value: 'proposed' },
        ]}
        onChange={(value) => onGraphView(value as 'existing' | 'proposed')}
      />
      <GraphChangeLegend changes={changes} />
      {definition ? (
        <WorkflowDesigner
          mode="proposal"
          definition={definition}
          apis={resources.apis}
          artifacts={resources.artifacts}
          workflows={resources.workflows}
          credentials={resources.credentials}
          graphqlSchemas={resources.graphqlSchemas}
          grpcDescriptors={resources.grpcDescriptors}
          eventSources={resources.eventSources}
          statuses={{}}
          proposalNodeStatuses={nodeStatuses}
          proposalEdgeStatuses={edgeStatuses}
          editable={false}
          onChange={() => undefined}
        />
      ) : (
        <Empty description="该提案将新建工作流，没有现有流程图" />
      )}
      <ProposalEvidence proposal={proposal} />
    </Space>
  )
}

function ReviewActions({
  proposal,
  busy,
  onReview,
  onApply,
  onOpenRawMapping,
}: {
  proposal: FlowSpecVisualProposal
  busy: boolean
  onReview: (accept: boolean) => Promise<void>
  onApply: () => Promise<void>
  onOpenRawMapping: (proposal: FlowSpecVisualProposal) => void
}) {
  const item = proposal.proposal
  return (
    <Card title="审核操作" size="small">
      <Space wrap>
        <Tag color={item.review_status === 'accepted' ? 'green' : 'gold'}>
          审核状态：{reviewStatusLabel(item.review_status)}
        </Tag>
        <Tag>变更集状态：{changeSetStatusLabel(item.status)}</Tag>
        {item.review_status === 'pending' ? (
          <>
            <Button
              aria-label="接受"
              type="primary"
              loading={busy}
              onClick={() => void onReview(true)}
            >
              接受
            </Button>
            <Button aria-label="拒绝" danger loading={busy} onClick={() => void onReview(false)}>
              拒绝
            </Button>
          </>
        ) : null}
        <Button
          aria-label="应用到工作流草稿"
          type="primary"
          loading={busy}
          disabled={item.review_status !== 'accepted' || Boolean(item.applied_at)}
          onClick={() => void onApply()}
        >
          应用到工作流草稿
        </Button>
        <Button onClick={() => onOpenRawMapping(proposal)}>原始 JSON / 跨实例映射</Button>
      </Space>
    </Card>
  )
}

type GraphChangeSummary = {
  addedNodes: string[]
  modifiedNodes: string[]
  removedNodes: string[]
  addedEdges: string[]
  modifiedEdges: string[]
  removedEdges: string[]
  rewiredEdges: string[]
  existingNodes: Record<string, ProposalGraphStatus>
  proposedNodes: Record<string, ProposalGraphStatus>
  existingEdges: Record<string, ProposalGraphStatus>
  proposedEdges: Record<string, ProposalGraphStatus>
}

function GraphChangeLegend({ changes }: { changes: GraphChangeSummary }) {
  return (
    <Card title="流程图差异" size="small">
      <Space wrap>
        <ChangeTags title="新增节点" color="green" values={changes.addedNodes} />
        <ChangeTags title="修改节点" color="gold" values={changes.modifiedNodes} />
        <ChangeTags title="删除节点" color="red" values={changes.removedNodes} />
        <ChangeTags title="新增连线" color="green" values={changes.addedEdges} />
        <ChangeTags title="修改连线" color="gold" values={changes.modifiedEdges} />
        <ChangeTags title="删除连线" color="red" values={changes.removedEdges} />
        <ChangeTags title="重连连线" color="purple" values={changes.rewiredEdges} />
      </Space>
    </Card>
  )
}

function ChangeTags({ title, color, values }: { title: string; color: string; values: string[] }) {
  return (
    <Space size={4} wrap>
      <Typography.Text strong>{title}</Typography.Text>
      {values.length ? (
        values.map((value) => (
          <Tag color={color} key={value}>
            {value}
          </Tag>
        ))
      ) : (
        <Tag>0</Tag>
      )}
    </Space>
  )
}

function ProposalEvidence({ proposal }: { proposal: FlowSpecVisualProposal }) {
  return (
    <div className="flow-proposal-review-grid">
      <MappingDiffCard proposal={proposal} />
      <AssertDiffCard proposal={proposal} />
      <EvidenceConfidenceCard plan={proposal.integration_plan} />
      <UnresolvedCard plan={proposal.integration_plan} />
    </div>
  )
}

function MappingDiffCard({ proposal }: { proposal: FlowSpecVisualProposal }) {
  const rows = [
    ...Object.entries(proposal.service_mappings).map(([ref, target]) => ({
      kind: '服务',
      ref,
      target,
      version: '-',
    })),
    ...Object.entries(proposal.operation_mappings).map(([ref, target]) => ({
      kind: '操作',
      ref,
      target,
      version: proposal.operation_version_mappings[ref] ?? '-',
    })),
  ]
  return (
    <Card title="映射差异 / 人工检查" size="small">
      <Table
        rowKey={(item) => `${item.kind}:${item.ref}`}
        size="small"
        pagination={false}
        dataSource={rows}
        columns={[
          { title: '类型', dataIndex: 'kind' },
          { title: '可移植引用', dataIndex: 'ref' },
          { title: '目标资产', dataIndex: 'target' },
          { title: '版本', dataIndex: 'version' },
        ]}
      />
    </Card>
  )
}

function AssertDiffCard({ proposal }: { proposal: FlowSpecVisualProposal }) {
  const rows = proposal.proposal.diff.filter((item) => item.path.toLowerCase().includes('assert'))
  return (
    <Card title="断言差异" size="small">
      {rows.length ? (
        <Table
          rowKey="path"
          size="small"
          pagination={false}
          dataSource={rows}
          columns={[
            { title: '路径', dataIndex: 'path' },
            { title: '变更前', dataIndex: 'before', render: jsonText },
            { title: '变更后', dataIndex: 'after', render: jsonText },
          ]}
        />
      ) : (
        <Typography.Text type="secondary">没有断言变化</Typography.Text>
      )}
    </Card>
  )
}

function EvidenceConfidenceCard({ plan }: { plan: IntegrationPlan | null }) {
  const confidence = plan?.confidence
  const evidence = plan?.evidence_refs ?? []
  return (
    <Card title="证据 / 置信度" size="small">
      <Descriptions bordered size="small" column={2}>
        <Descriptions.Item label="整体置信度">{percent(confidence?.overall)}</Descriptions.Item>
        <Descriptions.Item label="证据覆盖率">
          {percent(confidence?.evidence_coverage)}
        </Descriptions.Item>
        <Descriptions.Item label="确定性">
          {confidence?.deterministic ? '是' : '否'}
        </Descriptions.Item>
        <Descriptions.Item label="证据引用">{evidence.length}</Descriptions.Item>
      </Descriptions>
      <div className="flow-proposal-evidence-list">
        {evidence.slice(0, 30).map((ref) => (
          <Typography.Text code key={ref}>
            {ref}
          </Typography.Text>
        ))}
      </div>
    </Card>
  )
}

function UnresolvedCard({ plan }: { plan: IntegrationPlan | null }) {
  const unresolved = plan?.unresolved_items ?? []
  const requirements = plan?.review_requirements ?? []
  return (
    <Card title="未决项 / 审核要求" size="small">
      {unresolved.length ? (
        unresolved.map((item) => (
          <Alert
            key={item.id}
            showIcon
            type={item.severity === 'blocker' ? 'error' : 'warning'}
            title={item.code}
            description={item.message}
          />
        ))
      ) : (
        <Tag color="green">未决项 0</Tag>
      )}
      {requirements.map((item) => (
        <Tag color="gold" key={item}>
          {item}
        </Tag>
      ))}
    </Card>
  )
}

function graphChanges(
  existing: WorkflowDefinition | null,
  proposed: WorkflowDefinition,
): GraphChangeSummary {
  const beforeNodes = new Map((existing?.nodes ?? []).map((node) => [node.id, node]))
  const afterNodes = new Map(proposed.nodes.map((node) => [node.id, node]))
  const addedNodes = proposed.nodes
    .filter((node) => !beforeNodes.has(node.id))
    .map((node) => node.id)
  const removedNodes = (existing?.nodes ?? [])
    .filter((node) => !afterNodes.has(node.id))
    .map((node) => node.id)
  const modifiedNodes = proposed.nodes
    .filter((node) => {
      const before = beforeNodes.get(node.id)
      return before !== undefined && JSON.stringify(before) !== JSON.stringify(node)
    })
    .map((node) => node.id)
  const beforeEdges = new Map((existing?.edges ?? []).map((edge) => [edge.id, edge]))
  const afterEdges = new Map(proposed.edges.map((edge) => [edge.id, edge]))
  const addedEdges = proposed.edges
    .filter((edge) => !beforeEdges.has(edge.id))
    .map((edge) => edge.id)
  const removedEdges = (existing?.edges ?? [])
    .filter((edge) => !afterEdges.has(edge.id))
    .map((edge) => edge.id)
  const rewiredEdges = proposed.edges
    .filter((edge) => {
      const before = beforeEdges.get(edge.id)
      return (
        before !== undefined && (before.source !== edge.source || before.target !== edge.target)
      )
    })
    .map((edge) => edge.id)
  const modifiedEdges = proposed.edges
    .filter((edge) => {
      const before = beforeEdges.get(edge.id)
      return (
        before !== undefined &&
        (before.condition !== edge.condition ||
          JSON.stringify(before.mappings) !== JSON.stringify(edge.mappings))
      )
    })
    .map((edge) => edge.id)
  return {
    addedNodes,
    modifiedNodes,
    removedNodes,
    addedEdges,
    modifiedEdges,
    removedEdges,
    rewiredEdges,
    existingNodes: statusMap([
      ...modifiedNodes.map((id) => [id, 'modified'] as const),
      ...removedNodes.map((id) => [id, 'removed'] as const),
    ]),
    proposedNodes: statusMap([
      ...addedNodes.map((id) => [id, 'added'] as const),
      ...modifiedNodes.map((id) => [id, 'modified'] as const),
    ]),
    existingEdges: statusMap([
      ...removedEdges.map((id) => [id, 'removed'] as const),
      ...modifiedEdges.map((id) => [id, 'modified'] as const),
      ...rewiredEdges.map((id) => [id, 'rewired'] as const),
    ]),
    proposedEdges: statusMap([
      ...addedEdges.map((id) => [id, 'added'] as const),
      ...modifiedEdges.map((id) => [id, 'modified'] as const),
      ...rewiredEdges.map((id) => [id, 'rewired'] as const),
    ]),
  }
}

function statusMap(
  values: ReadonlyArray<readonly [string, ProposalGraphStatus]>,
): Record<string, ProposalGraphStatus> {
  return Object.fromEntries(values)
}

function percent(value: number | undefined): string {
  return value === undefined ? '-' : `${Math.round(value * 100)}%`
}

function jsonText(value: unknown): string {
  return JSON.stringify(value)
}

function requiredId(value: string | undefined): string {
  if (!value) throw new Error('流程提案 ID 为必填项')
  return value
}

function reviewStatusLabel(value: FlowSpecVisualProposal['proposal']['review_status']): string {
  return { pending: '待审核', accepted: '已接受', rejected: '已拒绝' }[value]
}

function changeSetStatusLabel(value: string): string {
  return { draft: '草稿', accepted: '已接受', rejected: '已拒绝' }[value] ?? '未知'
}

function selectedVisual(
  queried: FlowSpecVisualProposal | undefined,
  override: FlowSpecVisualProposal | undefined,
): FlowSpecVisualProposal | undefined {
  return override ?? queried
}
