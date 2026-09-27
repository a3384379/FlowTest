import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Modal, Segmented, Space, Tag, Typography } from 'antd'
import { useState } from 'react'

import WorkflowDesigner, { type ProposalGraphStatus } from '../../flow/WorkflowDesigner'
import { apiErrorMessage, type WorkflowDefinition } from '../../lib/api'
import { getMCPControlBlockPreview, type MCPControlBlockPreview } from './mcp-change-set-service'

type GraphView = 'existing' | 'proposed'

export default function ControlBlockGraphPreview({
  changeSetId,
  projectId,
  workflowId,
}: {
  changeSetId: string
  projectId: string
  workflowId: string
}) {
  const [open, setOpen] = useState(false)
  const [view, setView] = useState<GraphView>('proposed')
  const preview = useQuery({
    queryKey: ['mcp-control-block-preview', changeSetId],
    queryFn: () => getMCPControlBlockPreview(changeSetId),
    enabled: open,
  })
  return (
    <>
      <Button onClick={() => setOpen(true)}>查看图形差异</Button>
      <Modal
        title="控制块图形差异"
        open={open}
        onCancel={() => setOpen(false)}
        footer={null}
        width="90vw"
        destroyOnHidden
      >
        <Space orientation="vertical" size={12} style={{ width: '100%' }}>
          {preview.isError ? (
            <Alert
              showIcon
              type="error"
              title="无法生成当前草稿的图形预览"
              description={apiErrorMessage(preview.error)}
            />
          ) : null}
          {preview.data ? (
            <GraphPreviewContent
              data={preview.data}
              changeSetId={changeSetId}
              projectId={projectId}
              workflowId={workflowId}
              view={view}
              onView={setView}
            />
          ) : null}
        </Space>
      </Modal>
    </>
  )
}

function GraphPreviewContent({
  data,
  changeSetId,
  projectId,
  workflowId,
  view,
  onView,
}: {
  data: MCPControlBlockPreview
  changeSetId: string
  projectId: string
  workflowId: string
  view: GraphView
  onView: (view: GraphView) => void
}) {
  const changes = controlGraphChanges(data.existing_definition, data.proposed_definition)
  const definition = view === 'existing' ? data.existing_definition : data.proposed_definition
  return (
    <>
      <Typography.Text type="secondary">
        基线修订号 {data.base_revision}；接受前请核对连线和内联区域。
      </Typography.Text>
      <Segmented
        aria-label="控制块图视图"
        value={view}
        options={[
          { label: '原草稿', value: 'existing' },
          { label: '提案结果', value: 'proposed' },
        ]}
        onChange={(value) => onView(value as GraphView)}
      />
      <Space wrap>
        <Tag color="green">新增节点 {changes.addedNodes.length}</Tag>
        <Tag color="blue">新增连线 {changes.addedEdges.length}</Tag>
        <Tag color="orange">重接连线 {changes.rewiredEdges.length}</Tag>
        <Tag>新增区域 {changes.addedRegions.length}</Tag>
      </Space>
      <WorkflowDesigner
        key={`${changeSetId}:${view}`}
        mode="proposal"
        projectId={projectId}
        workflowId={workflowId}
        definition={definition}
        apis={[]}
        artifacts={[]}
        credentials={[]}
        statuses={{}}
        proposalNodeStatuses={view === 'existing' ? {} : changes.proposedNodeStatuses}
        proposalEdgeStatuses={
          view === 'existing' ? changes.existingEdgeStatuses : changes.proposedEdgeStatuses
        }
        editable={false}
        onChange={() => undefined}
      />
    </>
  )
}

type GraphChanges = {
  addedNodes: string[]
  addedEdges: string[]
  rewiredEdges: string[]
  addedRegions: string[]
  proposedNodeStatuses: Record<string, ProposalGraphStatus>
  existingEdgeStatuses: Record<string, ProposalGraphStatus>
  proposedEdgeStatuses: Record<string, ProposalGraphStatus>
}

function controlGraphChanges(
  existing: WorkflowDefinition,
  proposed: WorkflowDefinition,
): GraphChanges {
  const nodeIds = new Set(existing.nodes.map((node) => node.id))
  const edgeById = new Map(existing.edges.map((edge) => [edge.id, edge]))
  const regionIds = new Set((existing.regions ?? []).map((region) => region.id))
  const addedNodes = proposed.nodes.filter((node) => !nodeIds.has(node.id)).map((node) => node.id)
  const addedEdges = proposed.edges.filter((edge) => !edgeById.has(edge.id)).map((edge) => edge.id)
  const rewiredEdges = proposed.edges
    .filter((edge) => {
      const before = edgeById.get(edge.id)
      return before && (before.source !== edge.source || before.target !== edge.target)
    })
    .map((edge) => edge.id)
  const addedRegions = (proposed.regions ?? [])
    .filter((region) => !regionIds.has(region.id))
    .map((region) => region.id)
  return {
    addedNodes,
    addedEdges,
    rewiredEdges,
    addedRegions,
    proposedNodeStatuses: statusMap(addedNodes, 'added'),
    existingEdgeStatuses: statusMap(rewiredEdges, 'rewired'),
    proposedEdgeStatuses: {
      ...statusMap(addedEdges, 'added'),
      ...statusMap(rewiredEdges, 'rewired'),
    },
  }
}

function statusMap(
  ids: string[],
  status: ProposalGraphStatus,
): Record<string, ProposalGraphStatus> {
  return Object.fromEntries(ids.map((id) => [id, status]))
}
