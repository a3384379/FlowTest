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
import { Alert, Button, Empty, Input, Modal, Select, Space, Table, Tag, Typography } from 'antd'
import { useEffect, useMemo, useState, type ReactNode } from 'react'

import type {
  ApiDefinition,
  Artifact,
  Credential,
  Workflow,
  WorkflowDefinition,
  WorkflowNode,
  WorkflowNodeExecution,
} from '../lib/api'
import type { EventSource, SchemaArtifact } from '../features/protocols/protocol-service'
import WorkflowNodeInspector from './WorkflowNodeInspector'
import WorkflowRunInspector from './WorkflowRunInspector'
import { getApiDetail } from '../features/api-console/api-service'
import { listApis } from '../features/workflows/workflow-service'
import {
  addApiNode,
  addEventProtocolNode,
  addProtocolNode,
  addTypedNode,
  autoLayoutWorkflow,
  connectNodes,
  pasteNode,
  type PaletteNodeType,
} from './workflow-graph'

type DesignerProps = {
  projectId?: string | null
  environmentId?: string | null
  definition: WorkflowDefinition
  apis: ApiDefinition[]
  artifacts: Artifact[]
  workflows?: Workflow[]
  credentials: Credential[]
  graphqlSchemas?: SchemaArtifact[]
  grpcDescriptors?: SchemaArtifact[]
  eventSources?: EventSource[]
  statuses: Record<string, string>
  editable: boolean
  mode?: 'edit' | 'proposal'
  proposalNodeStatuses?: Record<string, ProposalGraphStatus>
  proposalEdgeStatuses?: Record<string, ProposalGraphStatus>
  runtimeMode?: 'run' | 'history'
  runtimeNodes?: WorkflowNodeExecution[]
  runtimeContext?: Record<string, unknown>
  onChange: (definition: WorkflowDefinition) => void
}

export type ProposalGraphStatus = 'added' | 'modified' | 'removed' | 'rewired'

type NodeData = Record<string, unknown> & {
  label: string
  nodeType: WorkflowNode['type']
  status: string
  runtimeLabel: string
}

type CanvasNode = Node<NodeData, 'workflowNode'>

const nodeTypes = { workflowNode: WorkflowNodeCard }
const NODE_INITIAL_WIDTH = 190
const NODE_INITIAL_HEIGHT = 64

export default function WorkflowDesigner(props: DesignerProps) {
  return (
    <WorkflowDesignerReady
      {...props}
      workflows={props.workflows ?? []}
      graphqlSchemas={props.graphqlSchemas ?? []}
      grpcDescriptors={props.grpcDescriptors ?? []}
      eventSources={props.eventSources ?? []}
      runtimeNodes={props.runtimeNodes ?? []}
      runtimeContext={props.runtimeContext ?? {}}
    />
  )
}

type ReadyDesignerProps = DesignerProps & {
  workflows: Workflow[]
  graphqlSchemas: SchemaArtifact[]
  grpcDescriptors: SchemaArtifact[]
  eventSources: EventSource[]
  runtimeNodes: WorkflowNodeExecution[]
  runtimeContext: Record<string, unknown>
}

function WorkflowDesignerReady({
  projectId,
  environmentId,
  definition,
  apis,
  artifacts,
  workflows,
  credentials,
  graphqlSchemas,
  grpcDescriptors,
  eventSources,
  statuses,
  editable,
  mode = 'edit',
  proposalNodeStatuses = {},
  proposalEdgeStatuses = {},
  runtimeMode,
  runtimeNodes,
  runtimeContext,
  onChange,
}: ReadyDesignerProps) {
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [apiSelection, setApiSelection] = useState<string | undefined>(firstResourceId(apis))
  const [apiSelectionOverride, setApiSelectionOverride] = useState<ApiDefinition | undefined>()
  const [apiSelectionProjectId, setApiSelectionProjectId] = useState(projectId)
  const [graphqlSelection, setGraphqlSelection] = useState<string | undefined>(
    firstResourceId(graphqlSchemas),
  )
  const [grpcSelection, setGrpcSelection] = useState<string | undefined>(
    firstResourceId(grpcDescriptors),
  )
  const kafkaSources = eventSources.filter((source) => source.kind === 'kafka')
  const websocketSources = eventSources.filter((source) => source.kind === 'websocket')
  const [kafkaSelection, setKafkaSelection] = useState<string | undefined>(
    firstResourceId(kafkaSources),
  )
  const [websocketSelection, setWebsocketSelection] = useState<string | undefined>(
    firstResourceId(websocketSources),
  )
  const publishedWorkflows = workflows.filter((workflow) => workflow.current_version)
  const [subflowSelection, setSubflowSelection] = useState<string | undefined>(
    firstResourceId(publishedWorkflows),
  )
  const [clipboard, setClipboard] = useState<WorkflowNode | null>(null)
  const [history, setHistory] = useState<{
    past: WorkflowDefinition[]
    future: WorkflowDefinition[]
  }>({ past: [], future: [] })
  const runtimeByNode = useMemo(
    () => new Map(runtimeNodes.map((node) => [node.node_id, node])),
    [runtimeNodes],
  )
  const nodes = useMemo(
    () =>
      definition.nodes.map((node) =>
        toCanvasNode(
          node,
          displayNodeStatus(node.id, statuses, proposalNodeStatuses),
          runtimeByNode.get(node.id),
        ),
      ),
    [definition.nodes, proposalNodeStatuses, runtimeByNode, statuses],
  )
  const edges = useMemo(
    () => definition.edges.map((edge) => toCanvasEdge(edge, proposalEdgeStatuses[edge.id])),
    [definition.edges, proposalEdgeStatuses],
  )
  const selected = selectedNode(definition, selectedId)
  const canvasEditable = isCanvasEditable(editable, mode)
  const selectedApi = resolveSelectedApi(
    apiSelection,
    apiSelectionProjectId,
    projectId,
    apis,
    apiSelectionOverride,
  )
  const selectedApiId = selectedApi?.id
  const selectedGraphql = selectedSchema(graphqlSelection, graphqlSchemas)
  const selectedGrpc = selectedSchema(grpcSelection, grpcDescriptors)
  const selectedSubflow = selectedWorkflow(subflowSelection, publishedWorkflows)

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

  function addSelectedApi() {
    if (selectedApi) {
      applyChange(addApiNode(definition, selectedApi.id, selectedApi.current_version))
    }
  }

  function addSelectedProtocol(protocol: 'graphql' | 'grpc') {
    const asset = protocol === 'graphql' ? selectedGraphql : selectedGrpc
    if (asset) applyChange(addProtocolNode(definition, protocol, asset))
  }

  function addSelectedEvent(
    capabilityId: 'kafka.produce' | 'kafka.consume' | 'websocket.exchange',
  ) {
    applyChange(
      addSelectedEventNode(
        definition,
        eventSources,
        capabilityId,
        kafkaSelection,
        websocketSelection,
      ),
    )
  }

  function addPaletteNode(type: PaletteNodeType) {
    applyChange(
      addTypedNode(
        definition,
        type,
        firstArtifactId(artifacts),
        workflowReference(selectedSubflow),
        credentials,
      ),
    )
  }

  function copySelectedNode() {
    if (selected) setClipboard(structuredClone(selected))
  }

  function pasteCopiedNode() {
    if (clipboard) applyChange(pasteNode(definition, clipboard))
  }

  if (!definition.nodes.length) return <Empty description="请选择工作流" />
  return (
    <div className="workflow-designer">
      <DesignerModeToolbar mode={mode}>
        <DesignerToolbar
          projectId={projectId}
          runtimeMode={runtimeMode}
          apiSelection={selectedApiId}
          apiSelectionOverride={apiSelectionOverride}
          apis={apis}
          graphqlSchemas={graphqlSchemas}
          grpcDescriptors={grpcDescriptors}
          kafkaSources={kafkaSources}
          websocketSources={websocketSources}
          graphqlSelection={optionalResourceId(selectedGraphql)}
          grpcSelection={optionalResourceId(selectedGrpc)}
          kafkaSelection={kafkaSelection}
          websocketSelection={websocketSelection}
          subflowSelection={optionalResourceId(selectedSubflow)}
          subflows={publishedWorkflows}
          editable={editable}
          hasArtifacts={artifacts.length > 0}
          hasDataset={definition.nodes.some((node) => node.type === 'dataset')}
          hasSqlCredential={credentials.some((item) => ['postgresql', 'mysql'].includes(item.kind))}
          hasRedisCredential={credentials.some((item) => item.kind === 'redis')}
          onApiSelection={(value) => {
            setApiSelection(value)
            setApiSelectionProjectId(projectId)
            setApiSelectionOverride(undefined)
          }}
          onApiPicked={(api) => {
            setApiSelection(api.id)
            setApiSelectionProjectId(projectId)
            setApiSelectionOverride(api)
          }}
          onGraphqlSelection={setGraphqlSelection}
          onGrpcSelection={setGrpcSelection}
          onKafkaSelection={setKafkaSelection}
          onWebsocketSelection={setWebsocketSelection}
          onSubflowSelection={setSubflowSelection}
          onAddApi={addSelectedApi}
          onAddGraphql={() => addSelectedProtocol('graphql')}
          onAddGrpc={() => addSelectedProtocol('grpc')}
          onAddKafkaProduce={() => addSelectedEvent('kafka.produce')}
          onAddKafkaConsume={() => addSelectedEvent('kafka.consume')}
          onAddWebsocketExchange={() => addSelectedEvent('websocket.exchange')}
          onAddNode={addPaletteNode}
          canCopy={Boolean(selected)}
          canPaste={Boolean(clipboard)}
          canUndo={history.past.length > 0}
          canRedo={history.future.length > 0}
          onCopy={copySelectedNode}
          onPaste={pasteCopiedNode}
          onUndo={undo}
          onRedo={redo}
          onAutoLayout={() => applyChange(autoLayoutWorkflow(definition))}
        />
      </DesignerModeToolbar>
      <div className="workflow-designer-body">
        <div className="workflow-canvas" aria-label="工作流画布">
          <ReactFlow
            fitView
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            nodesDraggable={canvasEditable}
            nodesConnectable={canvasEditable}
            edgesReconnectable={canvasEditable}
            onNodeClick={(_event, node) => setSelectedId(node.id)}
            onPaneClick={() => setSelectedId(null)}
            onNodesChange={(changes) => {
              if (canvasEditable) applyChange(applyCanvasNodeChanges(definition, nodes, changes))
            }}
            onEdgesChange={(changes) => {
              if (canvasEditable) applyChange(applyCanvasEdgeChanges(definition, edges, changes))
            }}
            onConnect={(connection) => {
              if (canvasEditable) applyChange(connectNodes(definition, edges, connection))
            }}
          >
            <Background gap={20} size={1} />
            <MiniMap pannable zoomable />
            <Controls />
          </ReactFlow>
        </div>
        <DesignerInspector
          projectId={projectId}
          environmentId={environmentId}
          runtimeMode={runtimeMode}
          runtimeNodes={runtimeNodes}
          runtimeContext={runtimeContext}
          runtimeByNode={runtimeByNode}
          selected={selected}
          definition={definition}
          apis={apis}
          artifacts={artifacts}
          workflows={publishedWorkflows}
          credentials={credentials}
          graphqlSchemas={graphqlSchemas}
          grpcDescriptors={grpcDescriptors}
          eventSources={eventSources}
          editable={canvasEditable}
          onChange={applyChange}
          onClearSelection={() => setSelectedId(null)}
        />
      </div>
    </div>
  )
}

function DesignerModeToolbar({
  mode,
  children,
}: {
  mode: 'edit' | 'proposal'
  children: ReactNode
}) {
  if (mode === 'edit') return children
  return (
    <div className="workflow-toolbar workflow-proposal-toolbar">
      <Space wrap>
        <Tag color="purple">提案模式</Tag>
        <Typography.Text type="secondary">
          该画布只用于提案检查；应用后返回工作流草稿进行安全编辑。
        </Typography.Text>
      </Space>
    </div>
  )
}

function displayNodeStatus(
  nodeId: string,
  statuses: Record<string, string>,
  proposalStatuses: Record<string, ProposalGraphStatus>,
): string | undefined {
  return statuses[nodeId] ?? proposalStatuses[nodeId]
}

function isCanvasEditable(editable: boolean, mode: 'edit' | 'proposal'): boolean {
  return editable && mode === 'edit'
}

function DesignerInspector({
  projectId,
  environmentId,
  runtimeMode,
  runtimeNodes,
  runtimeContext,
  runtimeByNode,
  selected,
  definition,
  apis,
  artifacts,
  workflows,
  credentials,
  graphqlSchemas,
  grpcDescriptors,
  eventSources,
  editable,
  onChange,
  onClearSelection,
}: {
  projectId?: string | null
  environmentId?: string | null
  runtimeMode?: 'run' | 'history'
  runtimeNodes: WorkflowNodeExecution[]
  runtimeContext: Record<string, unknown>
  runtimeByNode: Map<string, WorkflowNodeExecution>
  selected: WorkflowNode | null
  definition: WorkflowDefinition
  apis: ApiDefinition[]
  artifacts: Artifact[]
  workflows: Workflow[]
  credentials: Credential[]
  graphqlSchemas: SchemaArtifact[]
  grpcDescriptors: SchemaArtifact[]
  eventSources: EventSource[]
  editable: boolean
  onChange: (definition: WorkflowDefinition) => void
  onClearSelection: () => void
}) {
  if (runtimeMode) {
    return (
      <WorkflowRunInspector
        mode={runtimeMode}
        node={selected}
        definition={definition}
        execution={selected ? runtimeByNode.get(selected.id) : undefined}
        nodes={runtimeNodes}
        context={runtimeContext}
      />
    )
  }
  return (
    <WorkflowNodeInspector
      projectId={projectId}
      environmentId={environmentId}
      node={selected}
      definition={definition}
      apis={apis}
      artifacts={artifacts}
      workflows={workflows}
      credentials={credentials}
      graphqlSchemas={graphqlSchemas}
      grpcDescriptors={grpcDescriptors}
      eventSources={eventSources}
      editable={editable}
      onChange={onChange}
      onDelete={() => {
        if (!selected) return
        onChange(removeNode(definition, selected.id))
        onClearSelection()
      }}
    />
  )
}

function addSelectedEventNode(
  definition: WorkflowDefinition,
  sources: EventSource[],
  capabilityId: 'kafka.produce' | 'kafka.consume' | 'websocket.exchange',
  kafkaSelection: string | undefined,
  websocketSelection: string | undefined,
): WorkflowDefinition {
  const sourceId = capabilityId.startsWith('kafka') ? kafkaSelection : websocketSelection
  const source = sources.find((item) => item.id === sourceId)
  if (!source) return definition
  return addEventProtocolNode(definition, capabilityId, source)
}

function firstResourceId(items: Array<{ id: string }>): string | undefined {
  return items.at(0)?.id
}

function resolveSelectedApi(
  selection: string | undefined,
  selectionProjectId: string | null | undefined,
  projectId: string | null | undefined,
  apis: ApiDefinition[],
  override?: ApiDefinition,
): ApiDefinition | undefined {
  if (selectionProjectId === projectId && selection) {
    if (override?.id === selection) return override
    const selected = apis.find((api) => api.id === selection)
    if (selected) return selected
  }
  return apis.at(0)
}

function optionalResourceId(item: { id: string } | undefined): string | undefined {
  return item?.id
}

function selectedNode(definition: WorkflowDefinition, selectedId: string | null) {
  if (!selectedId) return null
  return definition.nodes.find((node) => node.id === selectedId) ?? null
}

function selectedSchema(selection: string | undefined, schemas: SchemaArtifact[]) {
  if (selection) {
    const selected = schemas.find((schema) => schema.id === selection)
    if (selected) return selected
  }
  return schemas.at(0)
}

function selectedWorkflow(selection: string | undefined, workflows: Workflow[]) {
  if (selection) {
    const selected = workflows.find((workflow) => workflow.id === selection)
    if (selected) return selected
  }
  return workflows.at(0)
}

function firstArtifactId(artifacts: Artifact[]): string | null {
  return artifacts.at(0)?.id ?? null
}

function workflowReference(workflow: Workflow | undefined) {
  if (!workflow?.current_version) return null
  return { workflowId: workflow.id, workflowVersion: workflow.current_version }
}

function DesignerToolbar({
  projectId,
  runtimeMode,
  apiSelection,
  apiSelectionOverride,
  apis,
  graphqlSelection,
  graphqlSchemas,
  grpcSelection,
  grpcDescriptors,
  kafkaSelection,
  kafkaSources,
  websocketSelection,
  websocketSources,
  subflowSelection,
  subflows,
  editable,
  hasArtifacts,
  hasDataset,
  hasSqlCredential,
  hasRedisCredential,
  onApiSelection,
  onApiPicked,
  onGraphqlSelection,
  onGrpcSelection,
  onKafkaSelection,
  onWebsocketSelection,
  onSubflowSelection,
  onAddApi,
  onAddGraphql,
  onAddGrpc,
  onAddKafkaProduce,
  onAddKafkaConsume,
  onAddWebsocketExchange,
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
  projectId?: string | null
  runtimeMode?: 'run' | 'history'
  apiSelection?: string
  apiSelectionOverride?: ApiDefinition
  apis: ApiDefinition[]
  graphqlSelection?: string
  graphqlSchemas: SchemaArtifact[]
  grpcSelection?: string
  grpcDescriptors: SchemaArtifact[]
  kafkaSelection?: string
  kafkaSources: EventSource[]
  websocketSelection?: string
  websocketSources: EventSource[]
  subflowSelection?: string
  subflows: Workflow[]
  editable: boolean
  hasArtifacts: boolean
  hasDataset: boolean
  hasSqlCredential: boolean
  hasRedisCredential: boolean
  onApiSelection: (value: string) => void
  onApiPicked: (api: ApiDefinition) => void
  onGraphqlSelection: (value: string) => void
  onGrpcSelection: (value: string) => void
  onKafkaSelection: (value: string) => void
  onWebsocketSelection: (value: string) => void
  onSubflowSelection: (value: string) => void
  onAddApi: () => void
  onAddGraphql: () => void
  onAddGrpc: () => void
  onAddKafkaProduce: () => void
  onAddKafkaConsume: () => void
  onAddWebsocketExchange: () => void
  onAddNode: (type: PaletteNodeType) => void
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
  const [apiPickerOpen, setApiPickerOpen] = useState(false)
  if (runtimeMode) {
    return (
      <div className="workflow-toolbar workflow-runtime-toolbar">
        <Space wrap>
          <Tag color={runtimeMode === 'history' ? 'gold' : 'processing'}>
            {runtimeMode === 'history' ? '历史快照 · 只读' : '实时运行视图'}
          </Tag>
          <Typography.Text type="secondary">
            点击节点查看输入、映射后的真实请求、响应和每次重试。
          </Typography.Text>
        </Space>
      </div>
    )
  }
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
          options={apiOptions(apis, apiSelectionOverride).map((api) => ({
            label: api.name,
            value: api.id,
          }))}
          onChange={onApiSelection}
        />
        <Button disabled={!editable || !projectId} onClick={() => setApiPickerOpen(true)}>
          搜索接口
        </Button>
        <Button
          icon={<PlusOutlined />}
          disabled={isControlDisabled(editable, Boolean(apiSelection))}
          onClick={onAddApi}
        >
          添加接口节点
        </Button>
        <Select
          aria-label="待添加 GraphQL Schema"
          value={graphqlSelection}
          disabled={!editable}
          placeholder="选择 GraphQL Schema"
          className="workflow-api-select"
          options={graphqlSchemas.map((schema) => ({
            label: `${schema.name} · v${schema.version}`,
            value: schema.id,
          }))}
          onChange={onGraphqlSelection}
        />
        <Button
          icon={<ApiOutlined />}
          disabled={isControlDisabled(editable, Boolean(graphqlSelection))}
          onClick={onAddGraphql}
        >
          GraphQL
        </Button>
        <Select
          aria-label="待添加 gRPC Descriptor"
          value={grpcSelection}
          disabled={!editable}
          placeholder="选择 gRPC Descriptor"
          className="workflow-api-select"
          options={grpcDescriptors.map((descriptor) => ({
            label: `${descriptor.name} · v${descriptor.version}`,
            value: descriptor.id,
          }))}
          onChange={onGrpcSelection}
        />
        <Button
          icon={<ApiOutlined />}
          disabled={isControlDisabled(editable, Boolean(grpcSelection))}
          onClick={onAddGrpc}
        >
          gRPC
        </Button>
        <Select
          aria-label="待添加 Kafka 事件源"
          value={kafkaSelection}
          disabled={!editable}
          placeholder="选择 Kafka 事件源"
          className="workflow-api-select"
          options={kafkaSources.map((source) => ({
            label: `${source.name} · v${source.version}`,
            value: source.id,
          }))}
          onChange={onKafkaSelection}
        />
        <Button
          icon={<DatabaseOutlined />}
          disabled={isControlDisabled(editable, Boolean(kafkaSelection))}
          onClick={onAddKafkaProduce}
        >
          Kafka Produce
        </Button>
        <Button
          icon={<DatabaseOutlined />}
          disabled={isControlDisabled(editable, Boolean(kafkaSelection))}
          onClick={onAddKafkaConsume}
        >
          Kafka Consume
        </Button>
        <Select
          aria-label="待添加 WebSocket 事件源"
          value={websocketSelection}
          disabled={!editable}
          placeholder="选择 WebSocket 事件源"
          className="workflow-api-select"
          options={websocketSources.map((source) => ({
            label: `${source.name} · v${source.version}`,
            value: source.id,
          }))}
          onChange={onWebsocketSelection}
        />
        <Button
          icon={<ApiOutlined />}
          disabled={isControlDisabled(editable, Boolean(websocketSelection))}
          onClick={onAddWebsocketExchange}
        >
          WebSocket Exchange
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
          disabled={isDatasetDisabled(editable, hasDataset, hasArtifacts)}
          onClick={() => onAddNode('dataset')}
        >
          数据集
        </Button>
        <Button
          icon={<DatabaseOutlined />}
          disabled={isDataNodeDisabled(editable, hasSqlCredential)}
          onClick={() => onAddNode('sql')}
        >
          只读 SQL
        </Button>
        <Button
          icon={<DatabaseOutlined />}
          disabled={isDataNodeDisabled(editable, hasRedisCredential)}
          onClick={() => onAddNode('redis')}
        >
          Redis 读取
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
          disabled={isControlDisabled(editable, Boolean(subflowSelection))}
          onClick={() => onAddNode('subflow')}
        >
          子流程
        </Button>
        <Button
          icon={<RetweetOutlined />}
          disabled={isControlDisabled(editable, Boolean(subflowSelection))}
          onClick={() => onAddNode('for_each')}
        >
          ForEach
        </Button>
        <Button icon={<FlagOutlined />} disabled={!editable} onClick={() => onAddNode('end')}>
          添加结束节点
        </Button>
        <Button
          icon={<CopyOutlined />}
          disabled={isControlDisabled(editable, canCopy)}
          onClick={onCopy}
        >
          复制
        </Button>
        <Button
          icon={<SnippetsOutlined />}
          disabled={isControlDisabled(editable, canPaste)}
          onClick={onPaste}
        >
          粘贴
        </Button>
        <Button
          icon={<UndoOutlined />}
          disabled={isControlDisabled(editable, canUndo)}
          onClick={onUndo}
        >
          撤销
        </Button>
        <Button
          icon={<RedoOutlined />}
          disabled={isControlDisabled(editable, canRedo)}
          onClick={onRedo}
        >
          重做
        </Button>
        <Button icon={<ApartmentOutlined />} disabled={!editable} onClick={onAutoLayout}>
          自动布局
        </Button>
      </Space>
      <Typography.Text type="secondary">
        拖动节点调整位置，从节点右侧连接到下一节点。
      </Typography.Text>
      <ApiPicker
        open={apiPickerOpen}
        projectId={projectId}
        selectedId={apiSelection}
        onClose={() => setApiPickerOpen(false)}
        onSelect={(api) => {
          onApiPicked(api)
          setApiPickerOpen(false)
        }}
      />
    </div>
  )
}

function ApiPicker({
  open,
  projectId,
  selectedId,
  onClose,
  onSelect,
}: {
  open: boolean
  projectId?: string | null
  selectedId?: string
  onClose: () => void
  onSelect: (api: ApiDefinition) => void
}) {
  const [search, setSearch] = useState('')
  const [method, setMethod] = useState<ApiMethod>()
  const [page, setPage] = useState(1)
  const [result, setResult] = useState<ApiPage>({ items: [], total: 0, page: 1, page_size: 20 })
  const [loading, setLoading] = useState(false)
  const [queryError, setQueryError] = useState(false)
  const [selectedRecord, setSelectedRecord] = useState<ApiDefinition>()
  const [retryNonce, setRetryNonce] = useState(0)

  useEffect(() => {
    if (!open || !projectId) return
    let active = true
    const timer = window.setTimeout(() => {
      setLoading(true)
      setQueryError(false)
      void listApis(projectId, { page, pageSize: 20, search, method })
        .then(async (next) => {
          if (!active) return
          setResult(next)
          if (selectedId && !next.items.some((item) => item.id === selectedId)) {
            try {
              const detail = await getApiDetail(projectId, selectedId)
              if (active) setSelectedRecord(detail.definition)
            } catch {
              if (active) setSelectedRecord(undefined)
            }
          } else {
            setSelectedRecord(undefined)
          }
        })
        .catch(() => {
          if (active) setQueryError(true)
        })
        .finally(() => {
          if (active) setLoading(false)
        })
    }, 250)
    return () => {
      active = false
      window.clearTimeout(timer)
    }
  }, [method, open, page, projectId, retryNonce, search, selectedId])

  return (
    <Modal title="选择接口" open={open} onCancel={onClose} footer={null} width={760} destroyOnClose>
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        {queryError && (
          <Alert
            type="error"
            showIcon
            message="接口查询失败"
            description="请检查项目权限或网络后重试。"
            action={
              <Button type="link" onClick={() => setRetryNonce((value) => value + 1)}>
                重试
              </Button>
            }
          />
        )}
        {selectedRecord && (
          <Alert
            type="info"
            showIcon
            message={`当前已选：${selectedRecord.name} · v${selectedRecord.current_version}`}
            description="该接口不在当前搜索页，已按 ID 读取并保留选择。"
          />
        )}
        <Space.Compact block>
          <Input.Search
            aria-label="搜索接口名称路径说明"
            allowClear
            placeholder="搜索名称、路径或说明"
            value={search}
            onChange={(event) => {
              setPage(1)
              setSearch(event.target.value)
            }}
            onSearch={() => setPage(1)}
          />
          <Select<ApiMethod>
            aria-label="选择接口方法"
            allowClear
            placeholder="全部方法"
            value={method}
            options={apiMethods.map((item) => ({ value: item, label: item }))}
            onChange={(value) => {
              setPage(1)
              setMethod(value)
            }}
            style={{ width: 130 }}
          />
        </Space.Compact>
        <Table
          rowKey="id"
          size="small"
          loading={loading}
          dataSource={result.items}
          pagination={{
            current: result.page,
            pageSize: result.page_size,
            total: result.total,
            showSizeChanger: false,
            onChange: setPage,
          }}
          rowClassName={(record) => (record.id === selectedId ? 'selected-row' : '')}
          onRow={(record) => ({ onClick: () => onSelect(record) })}
          columns={[
            { title: '接口名称', dataIndex: 'name' },
            { title: '说明', dataIndex: 'description', ellipsis: true },
            { title: '版本', dataIndex: 'current_version', render: (value: number) => `v${value}` },
            {
              title: '选择',
              width: 80,
              render: (_: unknown, record: ApiDefinition) => (
                <Button type="link" onClick={() => onSelect(record)}>
                  选择
                </Button>
              ),
            },
          ]}
        />
      </Space>
    </Modal>
  )
}

type ApiMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
type ApiPage = { items: ApiDefinition[]; total: number; page: number; page_size: number }
const apiMethods: ApiMethod[] = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE']

function apiOptions(apis: ApiDefinition[], selected?: ApiDefinition): ApiDefinition[] {
  if (!selected || apis.some((api) => api.id === selected.id)) return apis
  return [selected, ...apis]
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
      <span className="flow-node-status">
        {statusLabel(data.status)}
        {data.runtimeLabel && <small>{data.runtimeLabel}</small>}
      </span>
      {!terminal && <Handle type="source" position={Position.Right} />}
    </div>
  )
}

function toCanvasNode(
  node: WorkflowNode,
  status = 'pending',
  runtime?: WorkflowNodeExecution,
): CanvasNode {
  return {
    id: node.id,
    type: 'workflowNode',
    position: node.position,
    initialWidth: NODE_INITIAL_WIDTH,
    initialHeight: NODE_INITIAL_HEIGHT,
    data: { label: node.name, nodeType: node.type, status, runtimeLabel: runtimeLabel(runtime) },
  }
}

function runtimeLabel(runtime: WorkflowNodeExecution | undefined): string {
  if (!runtime) return ''
  const observation = runtime.result?.observations?.at(-1)
  if (observation?.response) {
    return `${observation.response.status_code} · ${formatNodeDuration(observation.duration_ms)}`
  }
  if (observation) return formatNodeDuration(observation.duration_ms)
  if (runtime.attempts > 1) return `${runtime.attempts} 次尝试`
  return ''
}

function formatNodeDuration(value: number): string {
  return value < 1000 ? `${Math.round(value)}ms` : `${Math.round(value / 10) / 100}s`
}

function toCanvasEdge(
  edge: WorkflowDefinition['edges'][number],
  status?: ProposalGraphStatus,
): Edge {
  const color = proposalEdgeColor(status)
  return {
    id: edge.id,
    source: edge.source,
    target: edge.target,
    markerEnd: { type: MarkerType.ArrowClosed },
    label: edge.condition ? (edge.condition === 'true' ? '是' : '否') : undefined,
    animated: status === 'rewired',
    style: color ? { stroke: color, strokeWidth: 3 } : undefined,
  }
}

function proposalEdgeColor(status: ProposalGraphStatus | undefined): string | undefined {
  if (!status) return undefined
  const colors: Record<ProposalGraphStatus, string> = {
    added: '#16a34a',
    modified: '#d97706',
    removed: '#dc2626',
    rewired: '#7c3aed',
  }
  return colors[status]
}

function applyCanvasNodeChanges(
  definition: WorkflowDefinition,
  nodes: CanvasNode[],
  changes: NodeChange<CanvasNode>[],
): WorkflowDefinition {
  const knownNodeIds = new Set(definition.nodes.map((node) => node.id))
  const positionChanges = changes.filter(
    (change) => change.type === 'position' && knownNodeIds.has(change.id),
  )
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
    capability: 'Capability',
    extract: '提取',
    assert: '断言',
    condition: '条件',
    delay: '延时',
    dataset: '数据集',
    subflow: '子流程',
    for_each: 'ForEach',
    sql: 'SQL',
    redis: 'Redis',
    end: '结束',
  }
  return labels[type] ?? type
}

function nodeIcon(type: WorkflowNode['type']) {
  return nodeIcons[type] ?? <ApiOutlined />
}

const nodeIcons: Partial<Record<WorkflowNode['type'], ReactNode>> = {
  start: <PlayCircleOutlined />,
  end: <FlagOutlined />,
  extract: <ExportOutlined />,
  assert: <CheckCircleOutlined />,
  condition: <BranchesOutlined />,
  delay: <ClockCircleOutlined />,
  dataset: <DatabaseOutlined />,
  subflow: <ApartmentOutlined />,
  for_each: <RetweetOutlined />,
  sql: <DatabaseOutlined />,
  redis: <DatabaseOutlined />,
}

function isDataNodeDisabled(editable: boolean, hasCredential: boolean): boolean {
  return !editable || !hasCredential
}

function isControlDisabled(editable: boolean, available: boolean): boolean {
  return !editable || !available
}

function isDatasetDisabled(editable: boolean, hasDataset: boolean, hasArtifacts: boolean): boolean {
  return !editable || hasDataset || !hasArtifacts
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
      added: '新增',
      modified: '修改',
      removed: '移除',
      rewired: '重连',
    }[status] ?? status
  )
}
