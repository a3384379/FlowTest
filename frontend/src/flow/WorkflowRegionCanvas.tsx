import {
  Background,
  Controls,
  MarkerType,
  Position,
  ReactFlow,
  type Edge,
  type Node,
} from '@xyflow/react'
import type { WorkflowRegion } from '../lib/api'
import { iceColors } from '../theme/ice-theme'
import { linearRegionPath } from './editor/control-blocks'

type Props = {
  region: WorkflowRegion
  editable: boolean
  selectedNodeId: string | null
  onSelectNode: (nodeId: string | null) => void
  onUpdate: (region: WorkflowRegion) => void
  onReorder: (sourceId: string, targetId: string) => void
}

function canvasNodes(region: WorkflowRegion, selectedNodeId: string | null): Node[] {
  return region.nodes.map((node) => ({
    id: node.id,
    type: 'default',
    position: node.position,
    data: {
      label: `${region.entry_node_id === node.id ? '入口 · ' : ''}${node.name}${region.exit_node_ids.includes(node.id) ? ' · 出口' : ''}`,
    },
    ariaLabel: node.name,
    selected: node.id === selectedNodeId,
    sourcePosition: Position.Right,
    targetPosition: Position.Left,
  }))
}

function canvasEdges(region: WorkflowRegion): Edge[] {
  return region.edges.map((edge) => ({
    id: edge.id,
    source: edge.source,
    target: edge.target,
    markerEnd: { type: MarkerType.ArrowClosed, color: iceColors.edge },
    style: { stroke: iceColors.edge, strokeWidth: 1.5 },
    animated: false,
  }))
}

export default function WorkflowRegionCanvas({
  region,
  editable,
  selectedNodeId,
  onSelectNode,
  onUpdate,
  onReorder,
}: Props) {
  const canConnect = editable && Boolean(linearRegionPath(region))
  return (
    <div className="workflow-region-canvas" aria-label={`${region.role} 区域画布`}>
      <ReactFlow
        colorMode="light"
        defaultNodes={canvasNodes(region, selectedNodeId)}
        defaultEdges={canvasEdges(region)}
        nodesDraggable={editable}
        nodesConnectable={canConnect}
        edgesReconnectable={canConnect}
        deleteKeyCode={null}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        onNodeClick={(_, node) => onSelectNode(node.id)}
        onPaneClick={() => onSelectNode(null)}
        onConnect={(connection) => onReorder(connection.source, connection.target)}
        onReconnect={(edge, connection) => {
          const sourceChanged = edge.source !== connection.source
          const targetChanged = edge.target !== connection.target
          if (sourceChanged !== targetChanged) onReorder(connection.source, connection.target)
        }}
        onNodeDragStop={(_, node) => {
          if (!editable) return
          onUpdate({
            ...region,
            nodes: region.nodes.map((item) =>
              item.id === node.id ? { ...item, position: node.position } : item,
            ),
          })
        }}
      >
        <Background color={iceColors.nodeBorder} gap={20} size={0.7} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  )
}
