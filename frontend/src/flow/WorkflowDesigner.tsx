import {
  ApiOutlined,
  BranchesOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  DatabaseOutlined,
  ExportOutlined,
  FlagOutlined,
  PlayCircleOutlined,
  PlusOutlined,
} from '@ant-design/icons'
import {
  applyEdgeChanges,
  applyNodeChanges,
  Background,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  type Edge,
  type EdgeChange,
  type Node,
  type NodeChange,
  type NodeProps,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { Button, Empty, Select, Space, Tag, Typography } from 'antd'
import { useMemo, useState } from 'react'

import type { ApiDefinition, Artifact, WorkflowDefinition, WorkflowNode } from '../lib/api'
import WorkflowNodeInspector from './WorkflowNodeInspector'
import { addApiNode, addTypedNode, connectNodes } from './workflow-graph'

type DesignerProps = {
  definition: WorkflowDefinition
  apis: ApiDefinition[]
  artifacts: Artifact[]
  statuses: Record<string, string>
  editable: boolean
  onChange: (definition: WorkflowDefinition) => void
}

type NodeData = Record<string, unknown> & {
  label: string
  nodeType: WorkflowNode['type']
  status: string
}

type CanvasNode = Node<NodeData, 'workflowNode'>

const nodeTypes = { workflowNode: WorkflowNodeCard }
const NODE_INITIAL_WIDTH = 190
const NODE_INITIAL_HEIGHT = 64

export default function WorkflowDesigner({
  definition,
  apis,
  artifacts,
  statuses,
  editable,
  onChange,
}: DesignerProps) {
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [apiSelection, setApiSelection] = useState<string | undefined>(apis.at(0)?.id)
  const nodes = useMemo(
    () => definition.nodes.map((node) => toCanvasNode(node, statuses[node.id])),
    [definition.nodes, statuses],
  )
  const edges = useMemo(() => definition.edges.map(toCanvasEdge), [definition.edges])
  const selected = definition.nodes.find((node) => node.id === selectedId) ?? null
  const selectedApiId = apiSelection ?? apis.at(0)?.id

  if (!definition.nodes.length) return <Empty description="请选择工作流" />
  return (
    <div className="workflow-designer">
      <DesignerToolbar
        apiSelection={selectedApiId}
        apis={apis}
        editable={editable}
        hasArtifacts={artifacts.length > 0}
        hasDataset={definition.nodes.some((node) => node.type === 'dataset')}
        onApiSelection={setApiSelection}
        onAddApi={() => selectedApiId && onChange(addApiNode(definition, selectedApiId))}
        onAddNode={(type) => onChange(addTypedNode(definition, type, artifacts.at(0)?.id ?? null))}
      />
      <div className="workflow-designer-body">
        <div className="workflow-canvas" aria-label="工作流画布">
          <ReactFlow
            fitView
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            nodesDraggable={editable}
            nodesConnectable={editable}
            edgesReconnectable={editable}
            onNodeClick={(_event, node) => setSelectedId(node.id)}
            onPaneClick={() => setSelectedId(null)}
            onNodesChange={(changes) => {
              if (editable) onChange(applyCanvasNodeChanges(definition, nodes, changes))
            }}
            onEdgesChange={(changes) => {
              if (editable) onChange(applyCanvasEdgeChanges(definition, edges, changes))
            }}
            onConnect={(connection) => {
              if (editable) onChange(connectNodes(definition, edges, connection))
            }}
          >
            <Background gap={20} size={1} />
            <MiniMap pannable zoomable />
            <Controls />
          </ReactFlow>
        </div>
        <WorkflowNodeInspector
          node={selected}
          definition={definition}
          apis={apis}
          artifacts={artifacts}
          editable={editable}
          onChange={onChange}
          onDelete={() => {
            if (!selected) return
            onChange(removeNode(definition, selected.id))
            setSelectedId(null)
          }}
        />
      </div>
    </div>
  )
}

function DesignerToolbar({
  apiSelection,
  apis,
  editable,
  hasArtifacts,
  hasDataset,
  onApiSelection,
  onAddApi,
  onAddNode,
}: {
  apiSelection?: string
  apis: ApiDefinition[]
  editable: boolean
  hasArtifacts: boolean
  hasDataset: boolean
  onApiSelection: (value: string) => void
  onAddApi: () => void
  onAddNode: (type: Exclude<WorkflowNode['type'], 'start' | 'api'>) => void
}) {
  return (
    <div className="workflow-toolbar">
      <Space wrap>
        <Tag icon={<PlayCircleOutlined />} color="green">
          开始节点
        </Tag>
        <Select
          aria-label="待添加接口"
          value={apiSelection}
          disabled={!editable}
          placeholder="选择接口"
          className="workflow-api-select"
          options={apis.map((api) => ({ label: api.name, value: api.id }))}
          onChange={onApiSelection}
        />
        <Button icon={<PlusOutlined />} disabled={!editable || !apiSelection} onClick={onAddApi}>
          添加接口节点
        </Button>
        <Button icon={<ExportOutlined />} disabled={!editable} onClick={() => onAddNode('extract')}>
          提取
        </Button>
        <Button
          icon={<CheckCircleOutlined />}
          disabled={!editable}
          onClick={() => onAddNode('assert')}
        >
          断言
        </Button>
        <Button
          icon={<BranchesOutlined />}
          disabled={!editable}
          onClick={() => onAddNode('condition')}
        >
          条件
        </Button>
        <Button
          icon={<ClockCircleOutlined />}
          disabled={!editable}
          onClick={() => onAddNode('delay')}
        >
          延时
        </Button>
        <Button
          icon={<DatabaseOutlined />}
          disabled={!editable || hasDataset || !hasArtifacts}
          onClick={() => onAddNode('dataset')}
        >
          数据集
        </Button>
        <Button icon={<FlagOutlined />} disabled={!editable} onClick={() => onAddNode('end')}>
          添加结束节点
        </Button>
      </Space>
      <Typography.Text type="secondary">
        拖动节点调整位置，从节点右侧连接到下一节点。
      </Typography.Text>
    </div>
  )
}

function WorkflowNodeCard({ data }: NodeProps<CanvasNode>) {
  const terminal = data.nodeType === 'end'
  const start = data.nodeType === 'start'
  return (
    <div className={`flow-node flow-node-${data.nodeType} is-${data.status}`}>
      {!start && <Handle type="target" position={Position.Left} />}
      <span className="flow-node-icon">{nodeIcon(data.nodeType)}</span>
      <span>
        <strong>{data.label}</strong>
        <small>{nodeTypeLabel(data.nodeType)}</small>
      </span>
      <span className="flow-node-status">{statusLabel(data.status)}</span>
      {!terminal && <Handle type="source" position={Position.Right} />}
    </div>
  )
}

function toCanvasNode(node: WorkflowNode, status = 'pending'): CanvasNode {
  return {
    id: node.id,
    type: 'workflowNode',
    position: node.position,
    initialWidth: NODE_INITIAL_WIDTH,
    initialHeight: NODE_INITIAL_HEIGHT,
    data: { label: node.name, nodeType: node.type, status },
  }
}

function toCanvasEdge(edge: WorkflowDefinition['edges'][number]): Edge {
  return {
    id: edge.id,
    source: edge.source,
    target: edge.target,
    markerEnd: { type: MarkerType.ArrowClosed },
    label: edge.condition ? (edge.condition === 'true' ? '是' : '否') : undefined,
  }
}

function applyCanvasNodeChanges(
  definition: WorkflowDefinition,
  nodes: CanvasNode[],
  changes: NodeChange<CanvasNode>[],
): WorkflowDefinition {
  const changed = applyNodeChanges(changes, nodes)
  const positions = new Map(changed.map((node) => [node.id, node.position]))
  return {
    ...definition,
    nodes: definition.nodes.map((node) => ({
      ...node,
      position: positions.get(node.id) ?? node.position,
    })),
  }
}

function applyCanvasEdgeChanges(
  definition: WorkflowDefinition,
  edges: Edge[],
  changes: EdgeChange<Edge>[],
): WorkflowDefinition {
  const changed = applyEdgeChanges(changes, edges)
  const remaining = new Set(changed.map((edge) => edge.id))
  return { ...definition, edges: definition.edges.filter((edge) => remaining.has(edge.id)) }
}

function removeNode(definition: WorkflowDefinition, nodeId: string): WorkflowDefinition {
  return {
    ...definition,
    nodes: definition.nodes.filter((node) => node.id !== nodeId),
    edges: definition.edges.filter((edge) => edge.source !== nodeId && edge.target !== nodeId),
  }
}

function nodeTypeLabel(type: WorkflowNode['type']): string {
  const labels: Partial<Record<WorkflowNode['type'], string>> = {
    start: '开始',
    api: '接口',
    extract: '提取',
    assert: '断言',
    condition: '条件',
    delay: '延时',
    dataset: '数据集',
    end: '结束',
  }
  return labels[type] ?? type
}

function nodeIcon(type: WorkflowNode['type']) {
  if (type === 'start') return <PlayCircleOutlined />
  if (type === 'end') return <FlagOutlined />
  if (type === 'extract') return <ExportOutlined />
  if (type === 'assert') return <CheckCircleOutlined />
  if (type === 'condition') return <BranchesOutlined />
  if (type === 'delay') return <ClockCircleOutlined />
  if (type === 'dataset') return <DatabaseOutlined />
  return <ApiOutlined />
}

function statusLabel(status: string): string {
  return (
    {
      pending: '等待',
      running: '运行中',
      passed: '通过',
      failed: '失败',
      skipped: '已跳过',
      cancelled: '已取消',
    }[status] ?? status
  )
}
