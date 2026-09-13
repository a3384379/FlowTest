import { updateCanvasDimensions, type CanvasDimensions } from './editor/canvas-dimensions'
import { workflowLayoutKey } from './editor/layout-preferences'
import WorkflowContextMenu from './WorkflowContextMenu'
import WorkflowDiagnostics from './WorkflowDiagnostics'
import WorkflowNodeLibrary, { type NodeLibraryItem } from './WorkflowNodeLibrary'
import WorkflowInspectorShell from './WorkflowInspectorShell'
import WorkflowNodeEditSession from './WorkflowNodeEditSession'
import { useAuthStore } from '../features/auth/auth-store'
import { useDraftSession } from '../features/drafts/draft-session'
import { nodeEditorScope } from './editor/editor-identity'
import { nodeRegistryItem, type NodeRegistryKey } from './editor/node-registry'
import './workflow-editor.css'
import WorkflowEdgeInspector from './WorkflowEdgeInspector'
import WorkflowShortcutHelp from './WorkflowShortcutHelp'
import { WorkflowEdgeActions, WorkflowNodeActions } from './WorkflowSelectionActions'
import { useWorkflowEditor } from './editor/use-workflow-editor'
import { useCanvasHotkeys } from './editor/use-canvas-hotkeys'
import {
  emptySelection,
  jsonEqual,
  type GraphConnectionInput,
  type WorkflowSelection,
} from './editor/editor-types'
import {
  connectGraphNodes,
  planDeletion,
  reconnectGraphEdge,
  swapBranches,
} from './editor/graph-commands'
import { analyzeGraph, resolveEffectiveNodeType } from './editor/graph-analysis'
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
  FullscreenExitOutlined,
  FullscreenOutlined,
  AimOutlined,
  MoreOutlined,
  PlusOutlined,
  PlayCircleOutlined,
  QuestionCircleOutlined,
  RedoOutlined,
  RetweetOutlined,
  SnippetsOutlined,
  UndoOutlined,
} from '@ant-design/icons'
import {
  applyNodeChanges,
  Background,
  BaseEdge,
  Controls,
  getBezierPath,
  Handle,
  MarkerType,
  MiniMap,
  Panel,
  Position,
  ReactFlow,
  type Edge,
  type EdgeProps,
  type Node,
  type NodeChange,
  type NodeProps,
  type ReactFlowInstance,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import {
  Alert,
  Button,
  Dropdown,
  Empty,
  Input,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd'
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'

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
  pasteNode,
  type PaletteNodeType,
} from './workflow-graph'

type DesignerProps = {
  surface?: 'embedded' | 'workspace'
  workflowId?: string
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
  focusActions?: ReactNode
  onChange: (definition: WorkflowDefinition) => void
}

export type ProposalGraphStatus = 'added' | 'modified' | 'removed' | 'rewired'

type NodeData = Record<string, unknown> & {
  label: string
  nodeType: WorkflowNode['type']
  status: string
  runtimeLabel: string
  canCopy?: boolean
  canDelete?: boolean
  onConfigure?: () => void
  onCopy?: () => void
  onDelete?: () => void
}

type CanvasNode = Node<NodeData, 'workflowNode'>
type CanvasEdgeData = Record<string, unknown> & {
  branch: 'true' | 'false' | null
  editable: boolean
  onConfigure: () => void
  onDelete: () => void
}
type CanvasEdge = Edge<CanvasEdgeData, 'workflowEdge'>

const nodeTypes = { workflowNode: WorkflowNodeCard }
const edgeTypes = { workflowEdge: WorkflowCanvasEdge }
const NODE_INITIAL_WIDTH = 210
const NODE_INITIAL_HEIGHT = 72

export default function WorkflowDesigner(props: DesignerProps) {
  return (
    <WorkflowDesignerReady
      {...props}
      mode={props.mode ?? 'edit'}
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
  mode: 'edit' | 'proposal'
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
  surface = 'embedded',
  workflowId = 'embedded',
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
  mode,
  proposalNodeStatuses = {},
  proposalEdgeStatuses = {},
  runtimeMode,
  runtimeNodes,
  runtimeContext,
  focusActions,
  onChange,
}: ReadyDesignerProps) {
  const canvasEditable = canMutateGraph(editable, mode, runtimeMode)
  const userId = useAuthStore(editorUserId)
  const scope = nodeEditorScope(userId, editorProjectId(projectId), workflowId)
  const draftSession = useDraftSession()
  const editor = useWorkflowEditor(
    definition,
    canvasEditable,
    onChange,
    recoverNodeSelection(draftSession, scope, definition),
  )
  const selectedId = primaryNodeId(editor.selection)
  const selectedEdge = primaryEdge(definition, editor.selection)
  const canvasRef = useRef<HTMLDivElement>(null)
  const flowRef = useRef<ReactFlowInstance<CanvasNode, CanvasEdge> | null>(null)
  useCanvasAutoFrame(canvasRef, flowRef, definition, editor.selection)
  const dropPosition = useRef<{ x: number; y: number } | null>(null)
  const [dimensions, setDimensions] = useState<CanvasDimensions>(() => new Map())
  const [focusMode, setFocusMode] = useState(false)
  const [shortcutHelp, setShortcutHelp] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [menuPoint, setMenuPoint] = useState<{ x: number; y: number } | null>(null)
  const [modal, modalHolder] = Modal.useModal()
  const [apiSelection, setApiSelection] = useState<string | undefined>(firstResourceId(apis))
  const [apiSelectionOverride, setApiSelectionOverride] = useState<ApiDefinition | undefined>()
  const [apiSelectionProjectId, setApiSelectionProjectId] = useState(projectId)
  const [graphqlSelection, setGraphqlSelection] = useState<string | undefined>(
    firstResourceId(graphqlSchemas),
  )
  const [grpcSelection, setGrpcSelection] = useState<string | undefined>(
    firstResourceId(grpcDescriptors),
  )
  const kafkaSources = eventSources.filter(isKafkaSource)
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
  const runtimeByNode = useMemo(
    () => new Map(runtimeNodes.map((node) => [node.node_id, node])),
    [runtimeNodes],
  )
  const diagnostics = useMemo(() => analyzeGraph(definition), [definition])
  const nodes = definition.nodes.map((node) => ({
    ...toCanvasNode(
      node,
      displayNodeStatus(node.id, statuses, proposalNodeStatuses),
      runtimeByNode.get(node.id),
    ),
    measured: dimensions.get(node.id),
    selected: editor.selection?.kind === 'node' && editor.selection.id === node.id,
    position: editor.positions.get(node.id) ?? node.position,
    data: {
      ...toCanvasNode(
        node,
        displayNodeStatus(node.id, statuses, proposalNodeStatuses),
        runtimeByNode.get(node.id),
      ).data,
      canCopy: canvasEditable && resolveEffectiveNodeType(node) !== 'start',
      canDelete: canvasEditable && canDeleteNode(definition, node),
      onConfigure: configureInspector,
      onCopy: copySelectedNode,
      onDelete: () => void requestDelete(),
    },
  }))
  const edges = definition.edges.map((edge) => ({
    ...toCanvasEdge(edge, proposalEdgeStatuses[edge.id]),
    selected: editor.selection?.kind === 'edge' && editor.selection.id === edge.id,
    sourceHandle: edge.condition ?? 'out',
    interactionWidth: 24,
    data: {
      branch: edge.condition,
      editable: canvasEditable,
      onConfigure: configureInspector,
      onDelete: () => void requestDelete(),
    },
    ariaLabel: `从 ${definition.nodes.find((node) => node.id === edge.source)?.name ?? edge.source} 到 ${definition.nodes.find((node) => node.id === edge.target)?.name ?? edge.target} 的连线`,
  }))
  const selected = selectedNode(definition, selectedId)
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

  const applyChange = editor.commit
  function undo() {
    if (readyForHistory()) editor.undo()
  }
  function redo() {
    if (readyForHistory()) editor.redo()
  }
  function readyForHistory() {
    if (!draftSession.dirtyNodeEditorKeys(scope).length) return true
    editor.notify('请先应用或丢弃节点配置，再撤销或重做流程修改')
    return false
  }
  const history = { past: editor.past, future: editor.future }
  function configureInspector() {
    setFocusMode(false)
    requestAnimationFrame(() => focusInspector(canvasRef.current))
  }
  async function finishSelectionChange(): Promise<boolean> {
    const keys = draftSession.dirtyNodeEditorKeys(scope)
    if (!keys.length) return true
    const approved = await modal.confirm({
      title: '节点配置尚未应用',
      content: '切换前应用当前配置，或返回继续编辑。',
      okText: '应用配置后继续',
      cancelText: '返回编辑',
    })
    if (!approved) return false
    for (const key of keys) {
      if (!(await draftSession.nodeEditorActions.get(key)?.())) return false
    }
    return true
  }
  async function selectObject(kind: 'node' | 'edge', id: string) {
    const selection = editor.latest.current.selection
    if (selection?.kind === kind && selection.id === id) return
    if (draftSession.dirtyNodeEditorKeys(scope).length && !(await finishSelectionChange())) return
    editor.click(kind, id)
  }
  async function openObjectMenu(kind: 'node' | 'edge', id: string, event: React.MouseEvent) {
    await selectObject(kind, id)
    if (editor.latest.current.selection?.id !== id) return
    setMenuPoint({ x: event.clientX, y: event.clientY })
    canvasRef.current?.focus()
  }
  async function clearSelection() {
    if (await finishSelectionChange()) editor.select(emptySelection())
  }
  async function requestDelete() {
    if (!canvasEditable || confirming) return
    if (!(await finishSelectionChange())) return
    const before = editor.latest.current.definition
    const selection = editor.latest.current.selection
    const plan = planDeletion(before, selection)
    if (plan.references.length) {
      editor.notify(plan.references.map((issue) => issue.message).join('；'))
      return
    }
    if (plan.requiresConfirmation) {
      setConfirming(true)
      const approved = await modal.confirm({
        title: '删除选中对象',
        content: `将删除 ${plan.deleteNodeIds.length} 个节点、${plan.deleteEdgeIds.length} 条连线及 ${plan.mappingCount} 条字段映射，流程可能暂时不完整。删除后可撤销。`,
        okText: '确认删除',
        cancelText: '取消',
      })
      setConfirming(false)
      if (
        !approved ||
        !jsonEqual(before, editor.latest.current.definition) ||
        !jsonEqual(selection, editor.latest.current.selection)
      )
        return
    }
    editor.deleteSelection()
  }
  async function reconnect(edgeId: string, input: GraphConnectionInput) {
    if (!canvasEditable || confirming) return
    const before = editor.latest.current.definition
    const edge = before.edges.find((item) => item.id === edgeId)
    const result = reconnectGraphEdge(before, edgeId, input)
    if (result.kind !== 'changed') {
      editor.accept(result)
      return
    }
    if (edge?.mappings.length) {
      setConfirming(true)
      const approved = await modal.confirm({
        title: '重新绑定映射端点',
        content: '保留映射路径并重新绑定端点。字段可能不兼容，请在重连后检查映射。',
        okText: '保留路径并重新绑定',
        cancelText: '取消',
      })
      setConfirming(false)
      if (!approved || !jsonEqual(before, editor.latest.current.definition)) return
    }
    editor.accept(reconnectGraphEdge(editor.latest.current.definition, edgeId, input))
  }
  const hotkeys = useDesignerHotkeys({
    editor,
    selected,
    canvasEditable,
    clipboard,
    copySelectedNode,
    pasteCopiedNode,
    requestDelete,
    canvasRef,
    surface,
    setFocusMode,
    setShortcutHelp,
    confirming,
    shortcutHelp,
    undo,
    redo,
    configureInspector,
    clearSelection,
    finishSelectionChange,
  })

  function addSelectedApi() {
    if (selectedApi) {
      addCreatedNode(
        addApiNode(editor.latest.current.definition, selectedApi.id, selectedApi.current_version),
      )
    }
  }

  function addSelectedProtocol(protocol: 'graphql' | 'grpc') {
    const asset = protocol === 'graphql' ? selectedGraphql : selectedGrpc
    if (asset) addCreatedNode(addProtocolNode(editor.latest.current.definition, protocol, asset))
  }

  function addSelectedEvent(
    capabilityId: 'kafka.produce' | 'kafka.consume' | 'websocket.exchange',
  ) {
    addCreatedNode(
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
    const issue = paletteIssue(type, definition, artifacts, selectedSubflow, credentials)
    if (issue) {
      editor.notify(issue)
      return
    }
    addCreatedNode(
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
    if (
      selected &&
      resolveEffectiveNodeType(selected) !== 'start' &&
      editor.selection?.kind === 'node'
    )
      setClipboard(structuredClone(selected))
  }

  function pasteCopiedNode() {
    if (!clipboard || !canvasEditable) return
    if (
      resolveEffectiveNodeType(clipboard) === 'dataset' &&
      definition.nodes.some((node) => resolveEffectiveNodeType(node) === 'dataset')
    ) {
      editor.notify('流程只能包含一个数据集节点')
      return
    }
    addCreatedNode(pasteNode(editor.latest.current.definition, clipboard))
  }
  function addCreatedNode(next: WorkflowDefinition) {
    if (!canvasEditable) return
    if (draftSession.dirtyNodeEditorKeys(scope).length) {
      editor.notify('请先应用或丢弃当前节点配置')
      return
    }
    const before = editor.latest.current.definition
    const added = next.nodes.find(
      (node) => !before.nodes.some((existing) => existing.id === node.id),
    )
    if (!added) return
    const point = dropPosition.current ?? canvasCenter(canvasRef.current, flowRef.current)
    dropPosition.current = null
    const placed = {
      ...next,
      nodes: next.nodes.map((node) =>
        node.id === added.id ? placeAddedNode(node, point, selected) : node,
      ),
    }
    editor.commit(placed, { kind: 'node', id: added.id })
  }
  function dropLibraryNode(event: React.DragEvent) {
    const type = event.dataTransfer.getData('application/x-flowtest-node')
    if (!canvasEditable || !type) return
    event.preventDefault()
    dropPosition.current =
      flowRef.current?.screenToFlowPosition({ x: event.clientX, y: event.clientY }) ?? null
    const actions: Record<string, () => void> = {
      api: addSelectedApi,
      graphql: () => addSelectedProtocol('graphql'),
      grpc: () => addSelectedProtocol('grpc'),
      'kafka.produce': () => addSelectedEvent('kafka.produce'),
      'kafka.consume': () => addSelectedEvent('kafka.consume'),
      'websocket.exchange': () => addSelectedEvent('websocket.exchange'),
    }
    if (actions[type]) actions[type]()
    else if (isPaletteType(type)) addPaletteNode(type)
    dropPosition.current = null
  }

  if (!definition.nodes.length) return <Empty description="暂无可展示的流程定义或执行快照" />
  return (
    <div className={`workflow-designer workflow-editor-${surface}${focusMode ? ' is-focus' : ''}`}>
      {modalHolder}
      <WorkflowContextMenu
        point={menuPoint}
        onClose={() => setMenuPoint(null)}
        actions={[
          { key: 'configure', label: '打开配置', run: configureInspector },
          {
            key: 'copy',
            label: '复制节点',
            disabled: !canCopyNode(selected),
            run: copySelectedNode,
          },
          {
            key: 'paste',
            label: '粘贴节点',
            disabled: !canPasteNode(canvasEditable, clipboard),
            run: pasteCopiedNode,
          },
          {
            key: 'delete',
            label: '删除选中对象',
            disabled: !canvasEditable,
            run: () => void requestDelete(),
          },
          {
            key: 'undo',
            label: '撤销',
            disabled: historyDisabled(canvasEditable, history.past.length),
            run: undo,
          },
          {
            key: 'redo',
            label: '重做',
            disabled: historyDisabled(canvasEditable, history.future.length),
            run: redo,
          },
        ]}
      />
      {editor.message && (
        <Alert closable onClose={() => editor.notify(null)} title={editor.message} type="info" />
      )}
      <WorkflowShortcutHelp open={shortcutHelp} onClose={() => setShortcutHelp(false)} />
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
          editable={canvasEditable}
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
          canCopy={canCopyNode(selected)}
          canPaste={Boolean(clipboard)}
          canUndo={history.past.length > 0}
          canRedo={history.future.length > 0}
          onCopy={copySelectedNode}
          onPaste={pasteCopiedNode}
          onUndo={undo}
          onRedo={redo}
          onAutoLayout={() => applyChange(autoLayoutWorkflow(definition))}
          focusActions={focusActions}
          focusMode={focusMode}
          allowFocus={surface === 'workspace'}
          onFocus={() => setFocusMode((value) => !value)}
          onHelp={() => setShortcutHelp(true)}
          onFitView={() =>
            void flowRef.current?.fitView({ duration: 200, padding: 0.18, maxZoom: 1 })
          }
        />
      </DesignerModeToolbar>
      <WorkflowInspectorShell
        key={workflowLayoutKey(userId, projectId)}
        visible={showInspector(editor.selection, focusMode)}
        preferenceKey={workflowLayoutKey(userId, projectId)}
        title={inspectorTitle(Boolean(selectedEdge), runtimeMode)}
        onClose={() => void clearSelection()}
        canvas={
          <div
            ref={canvasRef}
            className="workflow-canvas"
            data-testid="workflow-canvas-stage"
            aria-label="工作流画布"
            tabIndex={0}
            onDrop={dropLibraryNode}
            onDragOver={(event) => {
              if (canvasEditable) {
                event.preventDefault()
                event.dataTransfer.dropEffect = 'copy'
              }
            }}
            onKeyDown={hotkeys}
            onBlur={(event) => {
              if (!event.currentTarget.contains(event.relatedTarget)) editor.cancelDrag()
            }}
          >
            <ReactFlow<CanvasNode, CanvasEdge>
              fitView
              fitViewOptions={{ maxZoom: 1, padding: 0.18 }}
              onInit={(instance) => {
                flowRef.current = instance
              }}
              multiSelectionKeyCode={null}
              deleteKeyCode={null}
              nodes={nodes}
              edges={edges}
              nodeTypes={nodeTypes}
              edgeTypes={edgeTypes}
              nodesDraggable={canvasEditable}
              nodesConnectable={canvasEditable}
              edgesReconnectable={canvasEditable}
              onNodeClick={(_event, node) => {
                void selectObject('node', node.id)
                canvasRef.current?.focus()
              }}
              onEdgeClick={(_event, edge) => {
                void selectObject('edge', edge.id)
                canvasRef.current?.focus()
              }}
              onNodeContextMenu={(event, node) => {
                event.preventDefault()
                void openObjectMenu('node', node.id, event)
              }}
              onEdgeContextMenu={(event, edge) => {
                event.preventDefault()
                void openObjectMenu('edge', edge.id, event)
              }}
              onPaneClick={() => {
                void clearSelection()
                canvasRef.current?.focus()
              }}
              onNodeDragStart={editor.beginDrag}
              onNodeDragStop={(_event, _node, moved) =>
                editor.endDrag(moved.map((node) => ({ id: node.id, position: node.position })))
              }
              onNodesChange={(changes) => {
                setDimensions((current) =>
                  updateCanvasDimensions(
                    current,
                    changes,
                    new Set(definition.nodes.map((node) => node.id)),
                  ),
                )
                const updates = changes.flatMap((change) =>
                  change.type === 'position' && change.position
                    ? [{ id: change.id, position: change.position }]
                    : [],
                )
                const change = changes.find((item) => item.type === 'position')
                editor.positionsChanged(
                  updates,
                  change?.type === 'position' ? change.dragging : undefined,
                )
              }}
              onConnect={(connection) =>
                editor.accept(
                  connectGraphNodes(editor.latest.current.definition, {
                    sourceId: connection.source,
                    targetId: connection.target,
                    branch:
                      connection.sourceHandle === 'true' || connection.sourceHandle === 'false'
                        ? connection.sourceHandle
                        : null,
                    edgeId: `edge-${crypto.randomUUID()}`,
                  }),
                )
              }
              onReconnect={(edge, connection) =>
                void reconnect(edge.id, {
                  sourceId: connection.source,
                  targetId: connection.target,
                  branch:
                    connection.sourceHandle === 'true' || connection.sourceHandle === 'false'
                      ? connection.sourceHandle
                      : null,
                  edgeId: edge.id,
                })
              }
            >
              <Background gap={20} size={1} />
              <Panel position="top-left" className="workflow-canvas-diagnostics">
                <WorkflowDiagnostics
                  localDraft={canvasEditable}
                  issues={diagnostics}
                  onLocate={(issue) => {
                    if (issue.nodeId) void selectObject('node', issue.nodeId)
                    else if (issue.edgeId) void selectObject('edge', issue.edgeId)
                  }}
                />
              </Panel>
              <MiniMap pannable zoomable position="bottom-left" />
              <Controls position="bottom-right" showFitView={false} showInteractive={false} />
            </ReactFlow>
          </div>
        }
      >
        {selectedEdge ? (
          <WorkflowEdgeInspector
            edge={selectedEdge}
            definition={definition}
            editable={canvasEditable}
            onDelete={() => void requestDelete()}
            onSwap={() =>
              editor.accept(swapBranches(editor.latest.current.definition, selectedEdge.source))
            }
            onUpdate={(edge) =>
              applyChange({
                ...editor.latest.current.definition,
                edges: editor.latest.current.definition.edges.map((item) =>
                  item.id === edge.id ? edge : item,
                ),
              })
            }
          />
        ) : (
          <DesignerInspector
            scope={scope}
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
            onClearSelection={() => editor.select(emptySelection())}
            onDelete={() => void requestDelete()}
          />
        )}
      </WorkflowInspectorShell>
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

function inspectorTitle(hasEdge: boolean, runtimeMode?: 'run' | 'history'): string {
  if (hasEdge) return '连线配置'
  if (runtimeMode) return '运行详情'
  return '节点配置'
}

function displayNodeStatus(
  nodeId: string,
  statuses: Record<string, string>,
  proposalStatuses: Record<string, ProposalGraphStatus>,
): string | undefined {
  return statuses[nodeId] ?? proposalStatuses[nodeId]
}

function DesignerInspector({
  scope,
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
  onDelete,
}: {
  scope: string
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
  onDelete: () => void
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
  if (!selected) return null
  return (
    <WorkflowNodeEditSession
      key={`${scope}${selected.id}`}
      scope={scope}
      node={selected}
      definition={definition}
      editable={editable}
      onChange={onChange}
    >
      {(draftNode, update) => (
        <WorkflowNodeInspector
          projectId={projectId}
          environmentId={environmentId}
          node={draftNode}
          definition={definition}
          apis={apis}
          artifacts={artifacts}
          workflows={workflows}
          credentials={credentials}
          graphqlSchemas={graphqlSchemas}
          grpcDescriptors={grpcDescriptors}
          eventSources={eventSources}
          editable={editable}
          onChange={update}
          onDelete={onDelete}
        />
      )}
    </WorkflowNodeEditSession>
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
  focusActions,
  focusMode,
  allowFocus,
  onFocus,
  onHelp,
  onFitView,
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
  focusActions?: ReactNode
  focusMode: boolean
  allowFocus: boolean
  onFocus: () => void
  onHelp: () => void
  onFitView: () => void
}) {
  const [apiPickerOpen, setApiPickerOpen] = useState(false)
  const [libraryOpen, setLibraryOpen] = useState(false)
  if (runtimeMode) {
    return (
      <div
        className="workflow-toolbar workflow-runtime-toolbar"
        data-testid={focusMode ? 'workflow-focus-toolbar' : 'workflow-canvas-toolbar'}
      >
        <Space wrap>
          <Tag color={runtimeMode === 'history' ? 'gold' : 'processing'}>
            {runtimeMode === 'history' ? '历史快照 · 只读' : '实时运行视图'}
          </Tag>
          <Typography.Text type="secondary">
            点击节点查看输入、映射后的真实请求、响应和每次重试。
          </Typography.Text>
        </Space>
        <Space>
          <Button icon={<AimOutlined />} onClick={onFitView}>
            适应画布
          </Button>
          <Button icon={<QuestionCircleOutlined />} onClick={onHelp} aria-label="快捷键帮助" />
          <FocusModeButton enabled={allowFocus} active={focusMode} onClick={onFocus} />
        </Space>
      </div>
    )
  }
  return (
    <div
      className="workflow-toolbar"
      data-testid={focusMode ? 'workflow-focus-toolbar' : 'workflow-canvas-toolbar'}
    >
      <Space className="workflow-toolbar-primary" wrap>
        {focusMode && focusActions}
        <Button
          type="primary"
          icon={<PlusOutlined />}
          disabled={!editable}
          onClick={() => setLibraryOpen(true)}
          data-workflow-add
        >
          添加节点
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
        <Button icon={<AimOutlined />} onClick={onFitView}>
          适应画布
        </Button>
      </Space>
      <Space className="workflow-toolbar-secondary">
        <Dropdown
          trigger={['click']}
          menu={{
            items: [
              {
                key: 'copy',
                icon: <CopyOutlined />,
                label: '复制节点',
                disabled: isControlDisabled(editable, canCopy),
              },
              {
                key: 'paste',
                icon: <SnippetsOutlined />,
                label: '粘贴节点',
                disabled: isControlDisabled(editable, canPaste),
              },
            ],
            onClick: ({ key }) => {
              if (key === 'copy') onCopy()
              if (key === 'paste') onPaste()
            },
          }}
        >
          <Button icon={<MoreOutlined />} aria-label="画布编辑操作">
            编辑
          </Button>
        </Dropdown>
        <Button icon={<QuestionCircleOutlined />} onClick={onHelp} aria-label="快捷键帮助" />
        <FocusModeButton enabled={allowFocus} active={focusMode} onClick={onFocus} />
      </Space>
      <WorkflowNodeLibrary
        open={libraryOpen}
        onClose={() => setLibraryOpen(false)}
        items={createNodeLibraryItems({
          editable,
          projectId,
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
          hasArtifacts,
          hasDataset,
          hasSqlCredential,
          hasRedisCredential,
          onOpenApiPicker: () => setApiPickerOpen(true),
          onApiSelection,
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
        })}
      />
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

type NodeLibraryInput = {
  editable: boolean
  projectId?: string | null
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
  hasArtifacts: boolean
  hasDataset: boolean
  hasSqlCredential: boolean
  hasRedisCredential: boolean
  onOpenApiPicker: () => void
  onApiSelection: (value: string) => void
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
}

function createNodeLibraryItems(input: NodeLibraryInput): NodeLibraryItem[] {
  const reason = (available: boolean, message: string) =>
    input.editable ? (available ? undefined : message) : '当前模式只读'
  const item = (
    id: NodeRegistryKey,
    onAdd: () => void,
    unavailableReason?: string,
    resourceControl?: ReactNode,
  ): NodeLibraryItem => ({
    ...nodeRegistryItem(id),
    disabled: Boolean(unavailableReason),
    unavailableReason,
    resourceControl,
    onAdd,
    onDragStart: (event) => dragLibraryNode(event, id),
  })
  const select = (
    label: string,
    value: string | undefined,
    options: Array<{ label: string; value: string }>,
    onChange: (value: string) => void,
  ) => (
    <Select
      aria-label={label}
      value={value}
      disabled={!input.editable}
      placeholder="选择资源"
      options={options}
      onChange={onChange}
    />
  )
  const subflowControl = select(
    '待添加子流程',
    input.subflowSelection,
    input.subflows.map((workflow) => ({
      label: `${workflow.name} · v${workflow.current_version}`,
      value: workflow.id,
    })),
    input.onSubflowSelection,
  )
  return [
    item('delay', () => input.onAddNode('delay'), reason(true, '')),
    item('end', () => input.onAddNode('end'), reason(true, '')),
    item(
      'api',
      input.onAddApi,
      reason(
        Boolean(input.projectId && input.apiSelection),
        input.projectId ? '需要已发布接口' : '需要先选择项目',
      ),
      <Space.Compact block>
        {select(
          '待添加接口',
          input.apiSelection,
          apiOptions(input.apis, input.apiSelectionOverride).map((api) => ({
            label: api.name,
            value: api.id,
          })),
          input.onApiSelection,
        )}
        <Button
          aria-label="搜索接口"
          disabled={!input.editable || !input.projectId}
          onClick={input.onOpenApiPicker}
        >
          搜索
        </Button>
      </Space.Compact>,
    ),
    item(
      'graphql',
      input.onAddGraphql,
      reason(Boolean(input.graphqlSelection), '需要 GraphQL Schema'),
      select(
        '待添加 GraphQL Schema',
        input.graphqlSelection,
        input.graphqlSchemas.map((schema) => ({
          label: `${schema.name} · v${schema.version}`,
          value: schema.id,
        })),
        input.onGraphqlSelection,
      ),
    ),
    item(
      'grpc',
      input.onAddGrpc,
      reason(Boolean(input.grpcSelection), '需要 gRPC Descriptor'),
      select(
        '待添加 gRPC Descriptor',
        input.grpcSelection,
        input.grpcDescriptors.map((descriptor) => ({
          label: `${descriptor.name} · v${descriptor.version}`,
          value: descriptor.id,
        })),
        input.onGrpcSelection,
      ),
    ),
    item(
      'kafka.produce',
      input.onAddKafkaProduce,
      reason(Boolean(input.kafkaSelection), '需要 Kafka 事件源'),
      select(
        '待添加 Kafka Produce 事件源',
        input.kafkaSelection,
        input.kafkaSources.map((source) => ({
          label: `${source.name} · v${source.version}`,
          value: source.id,
        })),
        input.onKafkaSelection,
      ),
    ),
    item(
      'kafka.consume',
      input.onAddKafkaConsume,
      reason(Boolean(input.kafkaSelection), '需要 Kafka 事件源'),
      select(
        '待添加 Kafka Consume 事件源',
        input.kafkaSelection,
        input.kafkaSources.map((source) => ({
          label: `${source.name} · v${source.version}`,
          value: source.id,
        })),
        input.onKafkaSelection,
      ),
    ),
    item(
      'websocket.exchange',
      input.onAddWebsocketExchange,
      reason(Boolean(input.websocketSelection), '需要 WebSocket 事件源'),
      select(
        '待添加 WebSocket 事件源',
        input.websocketSelection,
        input.websocketSources.map((source) => ({
          label: `${source.name} · v${source.version}`,
          value: source.id,
        })),
        input.onWebsocketSelection,
      ),
    ),
    item('extract', () => input.onAddNode('extract'), reason(true, '')),
    item('assert', () => input.onAddNode('assert'), reason(true, '')),
    item('condition', () => input.onAddNode('condition'), reason(true, '')),
    item(
      'dataset',
      () => input.onAddNode('dataset'),
      reason(
        input.hasArtifacts && !input.hasDataset,
        input.hasDataset ? '流程已包含一个数据集节点' : '需要已上传数据集',
      ),
    ),
    item('sql', () => input.onAddNode('sql'), reason(input.hasSqlCredential, '需要数据库凭据')),
    item(
      'redis',
      () => input.onAddNode('redis'),
      reason(input.hasRedisCredential, '需要 Redis 凭据'),
    ),
    item(
      'subflow',
      () => input.onAddNode('subflow'),
      reason(Boolean(input.subflowSelection), '需要已发布子流程'),
      subflowControl,
    ),
    item(
      'for_each',
      () => input.onAddNode('for_each'),
      reason(Boolean(input.subflowSelection), '需要已发布子流程'),
      subflowControl,
    ),
  ]
}

function FocusModeButton({
  enabled,
  active,
  onClick,
}: {
  enabled: boolean
  active: boolean
  onClick: () => void
}) {
  if (!enabled) return null
  return (
    <Button
      aria-label={active ? '退出专注模式' : '专注模式'}
      icon={active ? <FullscreenExitOutlined /> : <FullscreenOutlined />}
      onClick={onClick}
    >
      {active ? '退出专注模式' : '专注模式'}
    </Button>
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
    <Modal
      title="选择接口"
      open={open}
      onCancel={onClose}
      footer={null}
      width={760}
      destroyOnHidden
    >
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
                <Button
                  type="link"
                  onClick={(event) => {
                    event.stopPropagation()
                    onSelect(record)
                  }}
                >
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

function WorkflowNodeCard({ data, selected }: NodeProps<CanvasNode>) {
  const terminal = data.nodeType === 'end'
  const start = data.nodeType === 'start'
  return (
    <>
      <WorkflowNodeActions
        visible={Boolean(selected)}
        editable={Boolean(data.canDelete)}
        canCopy={Boolean(data.canCopy)}
        onConfigure={data.onConfigure ?? (() => undefined)}
        onCopy={data.onCopy ?? (() => undefined)}
        onDelete={data.onDelete ?? (() => undefined)}
      />
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
        {!terminal &&
          (data.nodeType === 'condition' ? (
            <>
              <Handle type="source" id="true" position={Position.Right} style={{ top: '30%' }} />
              <Handle type="source" id="false" position={Position.Right} style={{ top: '75%' }} />
            </>
          ) : (
            <Handle type="source" id="out" position={Position.Right} />
          ))}
      </div>
    </>
  )
}

function WorkflowCanvasEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  markerEnd,
  style,
  label,
  selected,
  data,
}: EdgeProps<CanvasEdge>) {
  const [path, centerX, centerY] = getBezierPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
  })
  return (
    <>
      <BaseEdge id={id} path={path} markerEnd={markerEnd} style={style} label={label} />
      {data && (
        <WorkflowEdgeActions
          edgeId={id}
          x={centerX}
          y={centerY}
          visible={Boolean(selected)}
          branch={data.branch}
          editable={data.editable}
          onConfigure={data.onConfigure}
          onDelete={data.onDelete}
        />
      )}
    </>
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
    data: {
      label: node.name,
      nodeType: resolveEffectiveNodeType(node),
      status,
      runtimeLabel: runtimeLabel(runtime),
      canCopy: false,
      canDelete: false,
      onConfigure: () => undefined,
      onCopy: () => undefined,
      onDelete: () => undefined,
    },
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
): CanvasEdge {
  const color = proposalEdgeColor(status)
  return {
    id: edge.id,
    type: 'workflowEdge',
    source: edge.source,
    target: edge.target,
    markerEnd: { type: MarkerType.ArrowClosed },
    label: edge.condition ? (edge.condition === 'true' ? '是' : '否') : undefined,
    animated: status === 'rewired',
    style: color ? { stroke: color, strokeWidth: 3 } : undefined,
    data: {
      branch: edge.condition,
      editable: false,
      onConfigure: () => undefined,
      onDelete: () => undefined,
    },
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

// The helper is exported for focused canvas state regression coverage.
// eslint-disable-next-line react-refresh/only-export-components
export function applyCanvasNodeChanges(
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
  let positionsChanged = false
  const nextNodes = definition.nodes.map((node) => {
    const position = positions.get(node.id)
    if (
      position === undefined ||
      (position.x === node.position.x && position.y === node.position.y)
    ) {
      return node
    }
    positionsChanged = true
    return { ...node, position }
  })
  return positionsChanged ? { ...definition, nodes: nextNodes } : definition
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

function isControlDisabled(editable: boolean, available: boolean): boolean {
  return !editable || !available
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

function primaryNodeId(selection: WorkflowSelection): string | null {
  return selection?.kind === 'node' ? selection.id : null
}
function primaryEdge(definition: WorkflowDefinition, selection: WorkflowSelection) {
  return selection?.kind === 'edge'
    ? definition.edges.find((edge) => edge.id === selection.id)
    : undefined
}
type DesignerHotkeyInput = {
  editor: ReturnType<typeof useWorkflowEditor>
  selected: WorkflowNode | null
  canvasEditable: boolean
  clipboard: WorkflowNode | null
  copySelectedNode: () => void
  pasteCopiedNode: () => void
  requestDelete: () => Promise<void>
  canvasRef: React.RefObject<HTMLDivElement | null>
  surface: 'embedded' | 'workspace'
  setFocusMode: React.Dispatch<React.SetStateAction<boolean>>
  setShortcutHelp: React.Dispatch<React.SetStateAction<boolean>>
  confirming: boolean
  shortcutHelp: boolean
  undo: () => void
  redo: () => void
  configureInspector: () => void
  clearSelection: () => Promise<void>
  finishSelectionChange: () => Promise<boolean>
}
function writableHotkeys(input: DesignerHotkeyInput) {
  if (!input.canvasEditable) return {}
  return {
    delete: () => void input.requestDelete(),
    paste: input.clipboard ? input.pasteCopiedNode : undefined,
    undo: input.editor.past.length ? input.undo : undefined,
    redo: input.editor.future.length ? input.redo : undefined,
  }
}
function useDesignerHotkeys(input: DesignerHotkeyInput) {
  const { selected } = input
  return useCanvasHotkeys(
    {
      ...writableHotkeys(input),
      copy: canCopyNode(selected) ? input.copySelectedNode : undefined,
      add: input.canvasEditable
        ? () =>
            input.canvasRef.current
              ?.closest('.workflow-designer')
              ?.querySelector<HTMLButtonElement>('[data-workflow-add]')
              ?.click()
        : undefined,
      configure: input.configureInspector,
      focus:
        input.surface === 'workspace' ? () => input.setFocusMode((value) => !value) : undefined,
      help: () => input.setShortcutHelp(true),
      escape: () => escapeCanvas(input),
    },
    input.confirming || input.shortcutHelp,
  )
}
function canCopyNode(node: WorkflowNode | null): boolean {
  return Boolean(node && resolveEffectiveNodeType(node) !== 'start')
}
function escapeCanvas(input: DesignerHotkeyInput) {
  if (input.editor.dragging) input.editor.cancelDrag()
  else if (input.editor.selection) void input.clearSelection()
  else input.setFocusMode(false)
}

function canMutateGraph(editable: boolean, mode: string, runtimeMode?: string): boolean {
  return editable && mode === 'edit' && runtimeMode === undefined
}

function useCanvasAutoFrame(
  canvasRef: React.RefObject<HTMLDivElement | null>,
  flowRef: React.RefObject<ReactFlowInstance<CanvasNode, CanvasEdge> | null>,
  definition: WorkflowDefinition,
  selection: WorkflowSelection,
) {
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    let frame = 0
    const observer = new ResizeObserver(() => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => {
        frameCanvas(flowRef.current, definition, selection)
      })
    })
    observer.observe(canvas)
    return () => {
      cancelAnimationFrame(frame)
      observer.disconnect()
    }
  }, [canvasRef, definition, flowRef, selection])
}

function frameCanvas(
  instance: ReactFlowInstance<CanvasNode, CanvasEdge> | null,
  definition: WorkflowDefinition,
  selection: WorkflowSelection,
): void {
  if (!instance) return
  const center = selectionCenter(definition, selection)
  if (!center) {
    void instance.fitView({ duration: 0, padding: 0.18, maxZoom: 1 })
    return
  }
  const zoom = Math.min(1, Math.max(0.85, instance.getViewport().zoom))
  void instance.setCenter(center.x, center.y, { duration: 0, zoom })
}

function selectionCenter(
  definition: WorkflowDefinition,
  selection: WorkflowSelection,
): { x: number; y: number } | null {
  if (!selection) return null
  if (selection.kind === 'node') {
    const node = definition.nodes.find((candidate) => candidate.id === selection.id)
    return node
      ? {
          x: node.position.x + NODE_INITIAL_WIDTH / 2,
          y: node.position.y + NODE_INITIAL_HEIGHT / 2,
        }
      : null
  }
  const edge = definition.edges.find((candidate) => candidate.id === selection.id)
  const source = definition.nodes.find((candidate) => candidate.id === edge?.source)
  const target = definition.nodes.find((candidate) => candidate.id === edge?.target)
  if (!source || !target) return null
  return {
    x: (source.position.x + target.position.x + NODE_INITIAL_WIDTH) / 2,
    y: (source.position.y + target.position.y + NODE_INITIAL_HEIGHT) / 2,
  }
}
function editorUserId(store: { user: { id: string } | null }): string {
  return store.user?.id ?? 'anonymous'
}
function editorProjectId(projectId?: string | null): string {
  return projectId ?? 'embedded'
}

function hasSelection(selection: WorkflowSelection): boolean {
  return selection !== null
}
function isKafkaSource(source: { kind: string }): boolean {
  return source.kind === 'kafka'
}

function dragLibraryNode(event: React.DragEvent, type: string) {
  if (event.currentTarget.hasAttribute('disabled')) {
    event.preventDefault()
    return
  }
  event.dataTransfer.setData('application/x-flowtest-node', type)
  event.dataTransfer.effectAllowed = 'copy'
}

function canvasCenter(
  canvas: HTMLDivElement | null,
  flow: ReactFlowInstance<CanvasNode, CanvasEdge> | null,
): { x: number; y: number } {
  if (!canvas || !flow) return { x: 320, y: 160 }
  const rect = canvas.getBoundingClientRect()
  return flow.screenToFlowPosition({
    x: rect.left + rect.width / 2 - 95,
    y: rect.top + rect.height / 2 - 32,
  })
}
function isPaletteType(value: string): value is PaletteNodeType {
  return [
    'extract',
    'assert',
    'condition',
    'delay',
    'dataset',
    'sql',
    'redis',
    'subflow',
    'for_each',
    'end',
  ].includes(value)
}

function recoverNodeSelection(
  session: ReturnType<typeof useDraftSession>,
  scope: string,
  definition: WorkflowDefinition,
) {
  const key = session.dirtyNodeEditorKeys(scope)[0]
  const draft = session.nodeEditors.get(key)
  if (!draft || !definition.nodes.some((node) => node.id === draft.nodeId)) return emptySelection()
  return { kind: 'node' as const, id: draft.nodeId }
}

function canDeleteNode(definition: WorkflowDefinition, node: WorkflowNode): boolean {
  const type = resolveEffectiveNodeType(node)
  if (type === 'start') return false
  if (type !== 'end' || node.phase === 'cleanup') return true
  return (
    definition.nodes.filter(
      (candidate) => candidate.phase !== 'cleanup' && resolveEffectiveNodeType(candidate) === 'end',
    ).length > 1
  )
}

function placeAddedNode(
  node: WorkflowNode,
  position: { x: number; y: number },
  source: WorkflowNode | null,
): WorkflowNode {
  if (
    !source ||
    resolveEffectiveNodeType(source) === 'end' ||
    source.phase === 'cleanup' ||
    !('source_node_id' in node.config)
  )
    return { ...node, position }
  return { ...node, position, config: { ...node.config, source_node_id: source.id } }
}

function focusInspector(canvas: HTMLDivElement | null) {
  canvas
    ?.closest('.workflow-designer')
    ?.querySelector<HTMLElement>('.workflow-inspector input, .workflow-inspector button')
    ?.focus()
}
function canPasteNode(editable: boolean, node: WorkflowNode | null): boolean {
  return editable && node !== null
}
function historyDisabled(editable: boolean, length: number): boolean {
  return !editable || length === 0
}

function paletteIssue(
  type: PaletteNodeType,
  definition: WorkflowDefinition,
  artifacts: Artifact[],
  subflow: Workflow | undefined,
  credentials: Credential[],
): string | null {
  if (type === 'dataset') return datasetIssue(definition, artifacts)
  if (['subflow', 'for_each'].includes(type) && !subflow?.current_version)
    return '请先发布一个可引用的子流程'
  if (type === 'sql' && !credentials.some((item) => ['postgresql', 'mysql'].includes(item.kind)))
    return '请先配置 SQL 数据源凭据'
  if (type === 'redis' && !credentials.some((item) => item.kind === 'redis'))
    return '请先配置 Redis 凭据'
  return null
}
function datasetIssue(definition: WorkflowDefinition, artifacts: Artifact[]): string | null {
  if (definition.nodes.some((node) => resolveEffectiveNodeType(node) === 'dataset'))
    return '流程只能包含一个数据集节点'
  return artifacts.length ? null : '请先上传数据集文件'
}
function showInspector(selection: WorkflowSelection, focused: boolean): boolean {
  return hasSelection(selection) && !focused
}
