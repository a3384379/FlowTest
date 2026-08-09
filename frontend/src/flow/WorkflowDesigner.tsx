import {
  ApiOutlined,
  DeleteOutlined,
  FlagOutlined,
  PlayCircleOutlined,
  PlusOutlined,
} from '@ant-design/icons'
import {
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
  Background,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  type Connection,
  type Edge,
  type EdgeChange,
  type Node,
  type NodeChange,
  type NodeProps,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { Button, Empty, Input, InputNumber, Select, Space, Tag, Typography } from 'antd'
import { useMemo, useState } from 'react'

import type { ApiDefinition, WorkflowDefinition, WorkflowNode } from '../lib/api'

type DesignerProps = {
  definition: WorkflowDefinition
  apis: ApiDefinition[]
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
        onApiSelection={setApiSelection}
        onAddApi={() => selectedApiId && onChange(addApiNode(definition, selectedApiId))}
        onAddEnd={() => onChange(addEndNode(definition))}
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
        <NodeInspector
          node={selected}
          apis={apis}
          editable={editable}
          onUpdate={(node) => onChange(replaceNode(definition, node))}
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
  onApiSelection,
  onAddApi,
  onAddEnd,
}: {
  apiSelection?: string
  apis: ApiDefinition[]
  editable: boolean
  onApiSelection: (value: string) => void
  onAddApi: () => void
  onAddEnd: () => void
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
        <Button icon={<FlagOutlined />} disabled={!editable} onClick={onAddEnd}>
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

function NodeInspector({
  node,
  apis,
  editable,
  onUpdate,
  onDelete,
}: {
  node: WorkflowNode | null
  apis: ApiDefinition[]
  editable: boolean
  onUpdate: (node: WorkflowNode) => void
  onDelete: () => void
}) {
  if (!node) {
    return (
      <aside className="workflow-inspector">
        <Typography.Title level={5}>节点配置</Typography.Title>
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="选择一个节点进行配置" />
      </aside>
    )
  }
  const apiId =
    typeof node.config.api_definition_id === 'string' ? node.config.api_definition_id : undefined
  return (
    <aside className="workflow-inspector">
      <Typography.Title level={5}>节点配置</Typography.Title>
      <label>
        <span>名称</span>
        <Input
          disabled={!editable}
          value={node.name}
          onChange={(event) => onUpdate({ ...node, name: event.target.value })}
        />
      </label>
      {node.type === 'api' && (
        <>
          <label>
            <span>接口</span>
            <Select
              disabled={!editable}
              value={apiId}
              options={apis.map((api) => ({ label: api.name, value: api.id }))}
              onChange={(value) => onUpdate(updateNodeConfig(node, 'api_definition_id', value))}
            />
          </label>
          <label>
            <span>超时（秒）</span>
            <InputNumber
              disabled={!editable}
              min={1}
              max={300}
              value={numberConfig(node, 'timeout_seconds', 30)}
              onChange={(value) => onUpdate(updateNodeConfig(node, 'timeout_seconds', value ?? 30))}
            />
          </label>
          <label>
            <span>最大重试次数</span>
            <InputNumber
              disabled={!editable}
              min={0}
              max={3}
              value={numberConfig(node, 'max_retries', 0)}
              onChange={(value) => onUpdate(updateNodeConfig(node, 'max_retries', value ?? 0))}
            />
          </label>
        </>
      )}
      <Button
        danger
        icon={<DeleteOutlined />}
        disabled={!editable || node.type === 'start'}
        onClick={onDelete}
      >
        删除节点
      </Button>
    </aside>
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

function connectNodes(
  definition: WorkflowDefinition,
  edges: Edge[],
  connection: Connection,
): WorkflowDefinition {
  if (!connection.source || !connection.target || connection.source === connection.target)
    return definition
  const id = `${connection.source}-${connection.target}-${Date.now()}`
  const changed = addEdge({ ...connection, id }, edges)
  if (!changed.some((edge) => edge.id === id)) return definition
  return {
    ...definition,
    edges: [
      ...definition.edges,
      { id, source: connection.source, target: connection.target, condition: null, mappings: [] },
    ],
  }
}

function addApiNode(definition: WorkflowDefinition, apiId: string): WorkflowDefinition {
  const id = uniqueNodeId(definition, 'api')
  return {
    ...definition,
    nodes: [
      ...definition.nodes,
      {
        id,
        type: 'api',
        name: `接口请求 ${definition.nodes.filter((node) => node.type === 'api').length + 1}`,
        position: nextPosition(definition),
        config: { api_definition_id: apiId, max_retries: 0, retry_on: ['network_error', '5xx'] },
      },
    ],
  }
}

function addEndNode(definition: WorkflowDefinition): WorkflowDefinition {
  const id = uniqueNodeId(definition, 'end')
  return {
    ...definition,
    nodes: [
      ...definition.nodes,
      { id, type: 'end', name: '结束', position: nextPosition(definition), config: {} },
    ],
  }
}

function removeNode(definition: WorkflowDefinition, nodeId: string): WorkflowDefinition {
  return {
    ...definition,
    nodes: definition.nodes.filter((node) => node.id !== nodeId),
    edges: definition.edges.filter((edge) => edge.source !== nodeId && edge.target !== nodeId),
  }
}

function replaceNode(
  definition: WorkflowDefinition,
  replacement: WorkflowNode,
): WorkflowDefinition {
  return {
    ...definition,
    nodes: definition.nodes.map((node) => (node.id === replacement.id ? replacement : node)),
  }
}

function updateNodeConfig(node: WorkflowNode, key: string, value: unknown): WorkflowNode {
  return { ...node, config: { ...node.config, [key]: value } }
}

function numberConfig(node: WorkflowNode, key: string, fallback: number): number {
  const value = node.config[key]
  return typeof value === 'number' ? value : fallback
}

function uniqueNodeId(definition: WorkflowDefinition, prefix: string): string {
  const existing = new Set(definition.nodes.map((node) => node.id))
  let index = existing.size + 1
  while (existing.has(`${prefix}-${index}`)) index += 1
  return `${prefix}-${index}`
}

function nextPosition(definition: WorkflowDefinition) {
  const maxX = Math.max(0, ...definition.nodes.map((node) => node.position.x))
  return { x: maxX + 220, y: 120 + (definition.nodes.length % 3) * 100 }
}

function nodeTypeLabel(type: WorkflowNode['type']): string {
  const labels: Partial<Record<WorkflowNode['type'], string>> = {
    start: '开始',
    api: '接口',
    end: '结束',
  }
  return labels[type] ?? type
}

function nodeIcon(type: WorkflowNode['type']) {
  if (type === 'start') return <PlayCircleOutlined />
  if (type === 'end') return <FlagOutlined />
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
