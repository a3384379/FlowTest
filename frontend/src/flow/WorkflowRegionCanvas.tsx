import { Controls, MarkerType, Position, ReactFlow, type Edge, type Node } from '@xyflow/react'
import type { WorkflowRegion } from '../lib/api'

type Props = {
  region: WorkflowRegion
  editable: boolean
  selectedNodeId: string | null
  onSelectNode: (nodeId: string | null) => void
  onUpdate: (region: WorkflowRegion) => void
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
    markerEnd: { type: MarkerType.ArrowClosed },
    animated: false,
  }))
}

export default function WorkflowRegionCanvas({
  region,
  editable,
  selectedNodeId,
  onSelectNode,
  onUpdate,
}: Props) {
  return (
    <div className="workflow-region-canvas" aria-label={`${region.role} 区域画布`}>
      <ReactFlow
        defaultNodes={canvasNodes(region, selectedNodeId)}
        defaultEdges={canvasEdges(region)}
        nodesDraggable={editable}
        nodesConnectable={false}
        edgesReconnectable={false}
        deleteKeyCode={null}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        onNodeClick={(_, node) => onSelectNode(node.id)}
        onPaneClick={() => onSelectNode(null)}
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
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  )
}
