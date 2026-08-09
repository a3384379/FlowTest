import {
  ApiOutlined,
  ApartmentOutlined,
  BranchesOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  CopyOutlined,
  DatabaseOutlined,
  ExportOutlined,
  FlagOutlined,
  PlayCircleOutlined,
  PlusOutlined,
  RedoOutlined,
  RetweetOutlined,
  SnippetsOutlined,
  UndoOutlined,
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

import type {
  ApiDefinition,
  Artifact,
  Workflow,
  WorkflowDefinition,
  WorkflowNode,
} from '../lib/api'
import WorkflowNodeInspector from './WorkflowNodeInspector'
import {
  addApiNode,
  addTypedNode,
  autoLayoutWorkflow,
  connectNodes,
  pasteNode,
} from './workflow-graph'

type DesignerProps = {
  definition: WorkflowDefinition
  apis: ApiDefinition[]
  artifacts: Artifact[]
  workflows?: Workflow[]
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
  workflows = [],
  statuses,
  editable,
  onChange,
}: DesignerProps) {
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [apiSelection, setApiSelection] = useState<string | undefined>(apis.at(0)?.id)
  const publishedWorkflows = workflows.filter((workflow) => workflow.current_version)
  const [subflowSelection, setSubflowSelection] = useState<string | undefined>(
    publishedWorkflows.at(0)?.id,
  )
  const [clipboard, setClipboard] = useState<WorkflowNode | null>(null)
  const [history, setHistory] = useState<{
    past: WorkflowDefinition[]
    future: WorkflowDefinition[]
  }>({ past: [], future: [] })
  const nodes = useMemo(
    () => definition.nodes.map((node) => toCanvasNode(node, statuses[node.id])),
    [definition.nodes, statuses],
  )
  const edges = useMemo(() => definition.edges.map(toCanvasEdge), [definition.edges])
  const selected = definition.nodes.find((node) => node.id === selectedId) ?? null
  const selectedApiId = apiSelection ?? apis.at(0)?.id
  const selectedSubflow =
    publishedWorkflows.find((workflow) => workflow.id === subflowSelection) ??
    publishedWorkflows.at(0)

  function applyChange(next: WorkflowDefinition) {
    if (next === definition) return
    setHistory((current) => ({
      past: [...current.past.slice(-49), structuredClone(definition)],
      future: [],
    }))
    onChange(next)
  }

  function undo() {
    const previous = history.past.at(-1)
    if (!previous) return
    setHistory({
      past: history.past.slice(0, -1),
      future: [...history.future, structuredClone(definition)],
    })
    onChange(previous)
  }

  function redo() {
    const next = history.future.at(-1)
    if (!next) return
    setHistory({
      past: [...history.past, structuredClone(definition)],
      future: history.future.slice(0, -1),
    })
    onChange(next)
  }

  if (!definition.nodes.length) return <Empty description="请选择工作流" />
  return (
    <div className="workflow-designer">
      <DesignerToolbar
        apiSelection={selectedApiId}
        apis={apis}
        subflowSelection={selectedSubflow?.id}
        subflows={publishedWorkflows}
        editable={editable}
        hasArtifacts={artifacts.length > 0}
        hasDataset={definition.nodes.some((node) => node.type === 'dataset')}
        onApiSelection={setApiSelection}
        onSubflowSelection={setSubflowSelection}
        onAddApi={() => selectedApiId && applyChange(addApiNode(definition, selectedApiId))}
        onAddNode={(type) =>
          applyChange(
            addTypedNode(
              definition,
              type,
              artifacts.at(0)?.id ?? null,
              selectedSubflow?.current_version
                ? {
                    workflowId: selectedSubflow.id,
                    workflowVersion: selectedSubflow.current_version,
                  }
                : null,
            ),
          )
        }
        canCopy={Boolean(selected)}
        canPaste={Boolean(clipboard)}
        canUndo={history.past.length > 0}
        canRedo={history.future.length > 0}
        onCopy={() => selected && setClipboard(structuredClone(selected))}
        onPaste={() => clipboard && applyChange(pasteNode(definition, clipboard))}
        onUndo={undo}
        onRedo={redo}
        onAutoLayout={() => applyChange(autoLayoutWorkflow(definition))}
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
              if (editable) applyChange(applyCanvasNodeChanges(definition, nodes, changes))
            }}
            onEdgesChange={(changes) => {
              if (editable) applyChange(applyCanvasEdgeChanges(definition, edges, changes))
            }}
            onConnect={(connection) => {
              if (editable) applyChange(connectNodes(definition, edges, connection))
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
          workflows={publishedWorkflows}
          editable={editable}
          onChange={applyChange}
          onDelete={() => {
            if (!selected) return
            applyChange(removeNode(definition, selected.id))
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
  subflowSelection,
  subflows,
  editable,
  hasArtifacts,
  hasDataset,
  onApiSelection,
  onSubflowSelection,
  onAddApi,
  onAddNode,
  canCopy,
  canPaste,
  canUndo,
  canRedo,
  onCopy,
  onPaste,
  onUndo,
  onRedo,
  onAutoLayout,
}: {
  apiSelection?: string
  apis: ApiDefinition[]
  subflowSelection?: string
  subflows: Workflow[]
  editable: boolean
  hasArtifacts: boolean
  hasDataset: boolean
  onApiSelection: (value: string) => void
  onSubflowSelection: (value: string) => void
  onAddApi: () => void
  onAddNode: (type: Exclude<WorkflowNode['type'], 'start' | 'api'>) => void
  canCopy: boolean
  canPaste: boolean
  canUndo: boolean
  canRedo: boolean
  onCopy: () => void
  onPaste: () => void
  onUndo: () => void
  onRedo: () => void
  onAutoLayout: () => void
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
        <Select
          aria-label="待添加子流程"
          value={subflowSelection}
          disabled={!editable}
          placeholder="选择已发布流程"
          className="workflow-api-select"
          options={subflows.map((workflow) => ({
            label: `${workflow.name} · v${workflow.current_version}`,
            value: workflow.id,
          }))}
          onChange={onSubflowSelection}
        />
        <Button
          icon={<ApartmentOutlined />}
          disabled={!editable || !subflowSelection}
          onClick={() => onAddNode('subflow')}
        >
          子流程
        </Button>
        <Button
          icon={<RetweetOutlined />}
          disabled={!editable || !subflowSelection}
          onClick={() => onAddNode('for_each')}
        >
          ForEach
        </Button>
        <Button icon={<FlagOutlined />} disabled={!editable} onClick={() => onAddNode('end')}>
          添加结束节点
        </Button>
        <Button icon={<CopyOutlined />} disabled={!editable || !canCopy} onClick={onCopy}>
          复制
        </Button>
        <Button icon={<SnippetsOutlined />} disabled={!editable || !canPaste} onClick={onPaste}>
          粘贴
        </Button>
        <Button icon={<UndoOutlined />} disabled={!editable || !canUndo} onClick={onUndo}>
          撤销
        </Button>
        <Button icon={<RedoOutlined />} disabled={!editable || !canRedo} onClick={onRedo}>
          重做
        </Button>
        <Button icon={<ApartmentOutlined />} disabled={!editable} onClick={onAutoLayout}>
          自动布局
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
  const positionChanges = changes.filter((change) => change.type === 'position')
  if (!positionChanges.length) return definition
  const changed = applyNodeChanges(positionChanges, nodes)
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
  const removalChanges = changes.filter((change) => change.type === 'remove')
  if (!removalChanges.length) return definition
  const changed = applyEdgeChanges(removalChanges, edges)
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
    subflow: '子流程',
    for_each: 'ForEach',
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
  if (type === 'subflow') return <ApartmentOutlined />
  if (type === 'for_each') return <RetweetOutlined />
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
