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
          accept ? '可视化 Flow Proposal 人工接受' : '可视化 Flow Proposal 人工拒绝',
        )
        queryClient.setQueryData<FlowSpecVisualProposal>(
          ['flow-proposal', props.projectId, proposalId],
          (current) => (current ? { ...current, proposal: reviewed } : current),
        )
        setVisualOverride({ ...currentVisual, proposal: reviewed })
      },
      accept ? 'Flow Proposal 已接受' : 'Flow Proposal 已拒绝',
    )
  }

  async function apply(): Promise<void> {
    if (!proposalId) return
    await act(async () => {
      const result = await applyFlowSpec(props.projectId, proposalId)
      await queryClient.invalidateQueries({ queryKey: ['workflows', props.projectId] })
      props.onApplied(result.workflow_id)
    }, 'Flow Proposal 已应用到 Workflow Draft，可继续安全编辑')
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
      title="External LLM / MCP 可视化 Flow Proposal"
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
          title="Proposal 只会进入 AIChangeSet Draft；本视图没有 Publish、Execute 或自动 Apply。"
          description="先检查图、Mapping、Assert、Evidence、Confidence 与 Unresolved，再由人工接受；应用后进入现有 WorkflowDesigner 草稿继续安全编辑。"
        />
        <Select
          aria-label="Flow Proposal"
          style={{ width: '100%' }}
          loading={proposals.isLoading}
          placeholder="选择 MCP Flow Proposal"
          value={proposalId}
          options={candidates.map((item) => ({
            value: item.id,
            label: `${item.title} · ${item.status} · ${item.id.slice(0, 8)}`,
          }))}
          onChange={(value) => {
            setSelectedId(value)
            setVisualOverride(undefined)
          }}
        />
        {!candidates.length && !proposals.isLoading ? (
          <Empty description="暂无 MCP Flow Proposal" />
        ) : null}
        {displayedVisual ? (
          <ProposalWorkspace
            proposal={displayedVisual}
            graphView={graphView}
            resources={props.resources}
            busy={busy}
            onGraphView={setGraphView}
            onReview={(accept) => review(accept, displayedVisual)}
            onApply={apply}
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
        aria-label="Proposal Graph View"
        value={graphView}
        options={[
          { label: 'Existing Graph', value: 'existing' },
          { label: 'Proposed Graph', value: 'proposed' },
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
        <Empty description="该 Proposal 将新建 Workflow，没有 Existing Graph" />
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
    <Card title="Review Actions" size="small">
      <Space wrap>
        <Tag color={item.review_status === 'accepted' ? 'green' : 'gold'}>
          Review: {item.review_status}
        </Tag>
        <Tag>Status: {item.status}</Tag>
        {item.review_status === 'pending' ? (
          <>
            <Button type="primary" loading={busy} onClick={() => void onReview(true)}>
              Accept
            </Button>
            <Button danger loading={busy} onClick={() => void onReview(false)}>
              Reject
            </Button>
          </>
        ) : null}
        <Button
          aria-label="Apply to Workflow Draft"
          type="primary"
          loading={busy}
          disabled={item.review_status !== 'accepted' || Boolean(item.applied_at)}
          onClick={() => void onApply()}
        >
          Apply to Workflow Draft
        </Button>
        <Button onClick={() => onOpenRawMapping(proposal)}>
          Raw JSON / Cross-instance Mapping
        </Button>
      </Space>
    </Card>
  )
}

type GraphChangeSummary = {
  addedNodes: string[]
  modifiedNodes: string[]
  removedNodes: string[]
  rewiredEdges: string[]
  existingNodes: Record<string, ProposalGraphStatus>
  proposedNodes: Record<string, ProposalGraphStatus>
  existingEdges: Record<string, ProposalGraphStatus>
  proposedEdges: Record<string, ProposalGraphStatus>
}

function GraphChangeLegend({ changes }: { changes: GraphChangeSummary }) {
  return (
    <Card title="Graph Diff" size="small">
      <Space wrap>
        <ChangeTags title="Added Node" color="green" values={changes.addedNodes} />
        <ChangeTags title="Modified Node" color="gold" values={changes.modifiedNodes} />
        <ChangeTags title="Removed Node" color="red" values={changes.removedNodes} />
        <ChangeTags title="Rewired Edge" color="purple" values={changes.rewiredEdges} />
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
      kind: 'Service',
      ref,
      target,
      version: '-',
    })),
    ...Object.entries(proposal.operation_mappings).map(([ref, target]) => ({
      kind: 'Operation',
      ref,
      target,
      version: proposal.operation_version_mappings[ref] ?? '-',
    })),
  ]
  return (
    <Card title="Mapping Diff / Human Inspection" size="small">
      <Table
        rowKey={(item) => `${item.kind}:${item.ref}`}
        size="small"
        pagination={false}
        dataSource={rows}
        columns={[
          { title: 'Kind', dataIndex: 'kind' },
          { title: 'Portable Ref', dataIndex: 'ref' },
          { title: 'Target Asset', dataIndex: 'target' },
          { title: 'Version', dataIndex: 'version' },
        ]}
      />
    </Card>
  )
}

function AssertDiffCard({ proposal }: { proposal: FlowSpecVisualProposal }) {
  const rows = proposal.proposal.diff.filter((item) => item.path.toLowerCase().includes('assert'))
  return (
    <Card title="Assert Diff" size="small">
      {rows.length ? (
        <Table
          rowKey="path"
          size="small"
          pagination={false}
          dataSource={rows}
          columns={[
            { title: 'Path', dataIndex: 'path' },
            { title: 'Before', dataIndex: 'before', render: jsonText },
            { title: 'After', dataIndex: 'after', render: jsonText },
          ]}
        />
      ) : (
        <Typography.Text type="secondary">没有 Assert 变化</Typography.Text>
      )}
    </Card>
  )
}

function EvidenceConfidenceCard({ plan }: { plan: IntegrationPlan | null }) {
  const confidence = plan?.confidence
  const evidence = plan?.evidence_refs ?? []
  return (
    <Card title="Evidence / Confidence" size="small">
      <Descriptions bordered size="small" column={2}>
        <Descriptions.Item label="Overall">{percent(confidence?.overall)}</Descriptions.Item>
        <Descriptions.Item label="Evidence Coverage">
          {percent(confidence?.evidence_coverage)}
        </Descriptions.Item>
        <Descriptions.Item label="Deterministic">
          {confidence?.deterministic ? 'Yes' : 'No'}
        </Descriptions.Item>
        <Descriptions.Item label="Evidence Refs">{evidence.length}</Descriptions.Item>
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
    <Card title="Unresolved / Review Requirements" size="small">
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
        <Tag color="green">Unresolved 0</Tag>
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
  const rewiredEdges = proposed.edges
    .filter((edge) => {
      const before = beforeEdges.get(edge.id)
      return (
        before !== undefined && (before.source !== edge.source || before.target !== edge.target)
      )
    })
    .map((edge) => edge.id)
  return {
    addedNodes,
    modifiedNodes,
    removedNodes,
    rewiredEdges,
    existingNodes: statusMap([
      ...modifiedNodes.map((id) => [id, 'modified'] as const),
      ...removedNodes.map((id) => [id, 'removed'] as const),
    ]),
    proposedNodes: statusMap([
      ...addedNodes.map((id) => [id, 'added'] as const),
      ...modifiedNodes.map((id) => [id, 'modified'] as const),
    ]),
    existingEdges: edgeStatusMap(existing?.edges ?? [], afterEdges, rewiredEdges, 'removed'),
    proposedEdges: edgeStatusMap(proposed.edges, beforeEdges, rewiredEdges, 'added'),
  }
}

function edgeStatusMap(
  edges: WorkflowDefinition['edges'],
  other: Map<string, WorkflowDefinition['edges'][number]>,
  rewired: string[],
  missingStatus: 'added' | 'removed',
): Record<string, ProposalGraphStatus> {
  const statuses: Array<readonly [string, ProposalGraphStatus]> = []
  for (const edge of edges) {
    if (!other.has(edge.id)) statuses.push([edge.id, missingStatus])
    else if (rewired.includes(edge.id)) statuses.push([edge.id, 'rewired'])
  }
  return statusMap(statuses)
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
  if (!value) throw new Error('Flow Proposal ID is required')
  return value
}

function selectedVisual(
  queried: FlowSpecVisualProposal | undefined,
  override: FlowSpecVisualProposal | undefined,
): FlowSpecVisualProposal | undefined {
  return override ?? queried
}
