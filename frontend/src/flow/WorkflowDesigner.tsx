import { updateCanvasDimensions, type CanvasDimensions } from './editor/canvas-dimensions'
import { workflowLayoutKey } from './editor/layout-preferences'
import WorkflowContextMenu from './WorkflowContextMenu'
import WorkflowDiagnostics from './WorkflowDiagnostics'
import WorkflowNodeLibrary from './WorkflowNodeLibrary'
import WorkflowInspectorShell from './WorkflowInspectorShell'
import WorkflowNodeEditSession from './WorkflowNodeEditSession'
import { useAuthStore } from '../features/auth/auth-store'
import { useDraftSession } from '../features/drafts/draft-session'
import { nodeEditorScope } from './editor/editor-identity'
import './workflow-editor.css'
import WorkflowEdgeInspector from './WorkflowEdgeInspector'
import WorkflowShortcutHelp from './WorkflowShortcutHelp'
import { useWorkflowEditor } from './editor/use-workflow-editor'
import { useCanvasHotkeys } from './editor/use-canvas-hotkeys'
import { emptySelection, jsonEqual, type GraphConnectionInput } from './editor/editor-types'
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
  PlusOutlined,
  PlayCircleOutlined,
  RedoOutlined,
  RetweetOutlined,
  SnippetsOutlined,
  UndoOutlined,
} from '@ant-design/icons'
import {
  applyNodeChanges,
  Background,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeChange,
  type NodeProps,
  type ReactFlowInstance,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { Alert, Button, Empty, Input, Modal, Select, Space, Table, Tag, Typography } from 'antd'
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
  const flowRef = useRef<ReactFlowInstance<CanvasNode, Edge> | null>(null)
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
  const nodes = useMemo(
    () =>
      definition.nodes.map((node) => ({
        ...toCanvasNode(
          node,
          displayNodeStatus(node.id, statuses, proposalNodeStatuses),
          runtimeByNode.get(node.id),
        ),
        measured: dimensions.get(node.id),
        selected: editor.selection.nodeIds.includes(node.id),
        position: editor.positions.get(node.id) ?? node.position,
      })),
    [
      definition.nodes,
      dimensions,
      proposalNodeStatuses,
      runtimeByNode,
      statuses,
      editor.selection.nodeIds,
      editor.positions,
    ],
  )
  const edges = useMemo(
    () =>
      definition.edges.map((edge) => ({
        ...toCanvasEdge(edge, proposalEdgeStatuses[edge.id]),
        selected: editor.selection.edgeIds.includes(edge.id),
        sourceHandle: edge.condition ?? 'out',
        interactionWidth: 24,
        ariaLabel: `从 ${definition.nodes.find((node) => node.id === edge.source)?.name ?? edge.source} 到 ${definition.nodes.find((node) => node.id === edge.target)?.name ?? edge.target} 的连线`,
      })),
    [definition.edges, definition.nodes, proposalEdgeStatuses, editor.selection.edgeIds],
  )
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
  async function selectObject(kind: 'node' | 'edge', id: string, multiple = false) {
    const primary = editor.latest.current.selection.primary
    if (primary?.kind === kind && primary.id === id) return
    if (draftSession.dirtyNodeEditorKeys(scope).length && !(await finishSelectionChange())) return
    editor.click(kind, id, multiple)
  }
  async function openObjectMenu(kind: 'node' | 'edge', id: string, event: React.MouseEvent) {
    await selectObject(kind, id)
    if (editor.latest.current.selection.primary?.id !== id) return
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
      editor.selection.nodeIds.length === 1
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
    editor.commit(placed, {
      nodeIds: [added.id],
      edgeIds: [],
      primary: { kind: 'node', id: added.id },
    })
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
            disabled: !canCopyNode(selected, editor.selection.nodeIds.length),
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
      <WorkflowDiagnostics
        localDraft={canvasEditable}
        issues={analyzeGraph(definition)}
        onLocate={(issue) => {
          if (issue.nodeId) void selectObject('node', issue.nodeId)
          else if (issue.edgeId) void selectObject('edge', issue.edgeId)
        }}
      />
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
          canCopy={canCopyNode(selected, editor.selection.nodeIds.length)}
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
      <ViewActions
        surface={surface}
        focusMode={focusMode}
        onFocus={() => setFocusMode((value) => !value)}
        onHelp={() => setShortcutHelp(true)}
      />
      <WorkflowInspectorShell
        key={workflowLayoutKey(userId, projectId)}
        visible={showInspector(editor.selection, focusMode)}
        preferenceKey={workflowLayoutKey(userId, projectId)}
        onClose={() => void clearSelection()}
        canvas={
          <div
            ref={canvasRef}
            className="workflow-canvas"
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
            <ReactFlow<CanvasNode, Edge>
              fitView
              onInit={(instance) => {
                flowRef.current = instance
              }}
              multiSelectionKeyCode={['Shift', 'Meta', 'Control']}
              deleteKeyCode={null}
              nodes={nodes}
              edges={edges}
              nodeTypes={nodeTypes}
              nodesDraggable={canvasEditable}
              nodesConnectable={canvasEditable}
              edgesReconnectable={canvasEditable}
              onNodeClick={(event, node) => {
                void selectObject('node', node.id, event.shiftKey || event.metaKey || event.ctrlKey)
                canvasRef.current?.focus()
              }}
              onEdgeClick={(event, edge) => {
                void selectObject('edge', edge.id, event.shiftKey || event.metaKey || event.ctrlKey)
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
              onSelectionDragStart={editor.beginDrag}
              onNodeDragStop={(_event, _node, moved) =>
                editor.endDrag(moved.map((node) => ({ id: node.id, position: node.position })))
              }
              onSelectionDragStop={(_event, moved) =>
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
                if (!draftSession.dirtyNodeEditorKeys(scope).length)
                  editor.selectionChanges('node', changes)
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
              onEdgesChange={(changes) => {
                if (!draftSession.dirtyNodeEditorKeys(scope).length)
                  editor.selectionChanges('edge', changes)
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
              <MiniMap pannable zoomable />
              <Controls />
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
  const [libraryOpen, setLibraryOpen] = useState(false)
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
        <Button
          icon={<PlusOutlined />}
          disabled={!editable}
          onClick={() => setLibraryOpen(true)}
          data-workflow-add
        >
          添加节点
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
      <WorkflowNodeLibrary
        open={libraryOpen}
        onClose={() => setLibraryOpen(false)}
        unavailable={libraryUnavailableReasons({
          hasArtifacts,
          hasDataset,
          hasSqlCredential,
          hasRedisCredential,
          graphqlCount: graphqlSchemas.length,
          grpcCount: grpcDescriptors.length,
          kafkaCount: kafkaSources.length,
          websocketCount: websocketSources.length,
          subflowCount: subflows.length,
        })}
        groups={[
          {
            name: '接口请求',
            keywords: 'HTTP API 接口 请求',
            content: (
              <>
                {' '}
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
                  draggable={editable}
                  onDragStart={(event) => dragLibraryNode(event, 'api')}
                  onClick={onAddApi}
                >
                  添加接口节点
                </Button>
              </>
            ),
          },
          {
            name: '协议与事件',
            keywords: 'GraphQL gRPC Kafka WebSocket 协议 消息',
            content: (
              <>
                {' '}
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
                  draggable={editable}
                  onDragStart={(event) => dragLibraryNode(event, 'graphql')}
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
                  draggable={editable}
                  onDragStart={(event) => dragLibraryNode(event, 'grpc')}
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
                  draggable={editable}
                  onDragStart={(event) => dragLibraryNode(event, 'kafka.produce')}
                  onClick={onAddKafkaProduce}
                >
                  Kafka Produce
                </Button>
                <Button
                  icon={<DatabaseOutlined />}
                  disabled={isControlDisabled(editable, Boolean(kafkaSelection))}
                  draggable={editable}
                  onDragStart={(event) => dragLibraryNode(event, 'kafka.consume')}
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
                  draggable={editable}
                  onDragStart={(event) => dragLibraryNode(event, 'websocket.exchange')}
                  onClick={onAddWebsocketExchange}
                >
                  WebSocket Exchange
                </Button>
              </>
            ),
          },
          {
            name: '控制与校验',
            keywords: '提取 断言 条件 延时 extract assert condition delay',
            content: (
              <>
                {' '}
                <Button
                  icon={<ExportOutlined />}
                  disabled={!editable}
                  draggable={editable}
                  onDragStart={(event) => dragLibraryNode(event, 'extract')}
                  onClick={() => onAddNode('extract')}
                >
                  提取
                </Button>
                <Button
                  icon={<CheckCircleOutlined />}
                  disabled={!editable}
                  draggable={editable}
                  onDragStart={(event) => dragLibraryNode(event, 'assert')}
                  onClick={() => onAddNode('assert')}
                >
                  断言
                </Button>
                <Button
                  icon={<BranchesOutlined />}
                  disabled={!editable}
                  draggable={editable}
                  onDragStart={(event) => dragLibraryNode(event, 'condition')}
                  onClick={() => onAddNode('condition')}
                >
                  条件
                </Button>
                <Button
                  icon={<ClockCircleOutlined />}
                  disabled={!editable}
                  draggable={editable}
                  onDragStart={(event) => dragLibraryNode(event, 'delay')}
                  onClick={() => onAddNode('delay')}
                >
                  延时
                </Button>
              </>
            ),
          },
          {
            name: '数据与存储',
            keywords: '数据集 SQL Redis dataset',
            content: (
              <>
                {' '}
                <Button
                  icon={<DatabaseOutlined />}
                  disabled={isDatasetDisabled(editable, hasDataset, hasArtifacts)}
                  draggable={editable}
                  onDragStart={(event) => dragLibraryNode(event, 'dataset')}
                  onClick={() => onAddNode('dataset')}
                >
                  数据集
                </Button>
                <Button
                  icon={<DatabaseOutlined />}
                  disabled={isDataNodeDisabled(editable, hasSqlCredential)}
                  draggable={editable}
                  onDragStart={(event) => dragLibraryNode(event, 'sql')}
                  onClick={() => onAddNode('sql')}
                >
                  只读 SQL
                </Button>
                <Button
                  icon={<DatabaseOutlined />}
                  disabled={isDataNodeDisabled(editable, hasRedisCredential)}
                  draggable={editable}
                  onDragStart={(event) => dragLibraryNode(event, 'redis')}
                  onClick={() => onAddNode('redis')}
                >
                  Redis 读取
                </Button>
              </>
            ),
          },
          {
            name: '流程复用',
            keywords: '子流程 ForEach subflow for_each',
            content: (
              <>
                {' '}
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
                  draggable={editable}
                  onDragStart={(event) => dragLibraryNode(event, 'subflow')}
                  onClick={() => onAddNode('subflow')}
                >
                  子流程
                </Button>
                <Button
                  icon={<RetweetOutlined />}
                  disabled={isControlDisabled(editable, Boolean(subflowSelection))}
                  draggable={editable}
                  onDragStart={(event) => dragLibraryNode(event, 'for_each')}
                  onClick={() => onAddNode('for_each')}
                >
                  ForEach
                </Button>
              </>
            ),
          },
          {
            name: '结束',
            keywords: '结束 end',
            content: (
              <>
                {' '}
                <Button
                  icon={<FlagOutlined />}
                  disabled={!editable}
                  draggable={editable}
                  onDragStart={(event) => dragLibraryNode(event, 'end')}
                  onClick={() => onAddNode('end')}
                >
                  添加结束节点
                </Button>
              </>
            ),
          },
        ]}
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

function primaryNodeId(selection: import('./editor/editor-types').EditorSelection): string | null {
  return selection.primary?.kind === 'node' ? selection.primary.id : null
}
function primaryEdge(
  definition: WorkflowDefinition,
  selection: import('./editor/editor-types').EditorSelection,
) {
  return selection.primary?.kind === 'edge'
    ? definition.edges.find((edge) => edge.id === selection.primary?.id)
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
  const { editor, selected } = input
  return useCanvasHotkeys(
    {
      ...writableHotkeys(input),
      copy: canCopyNode(selected, editor.selection.nodeIds.length)
        ? input.copySelectedNode
        : undefined,
      add: input.canvasEditable
        ? () =>
            input.canvasRef.current
              ?.closest('.workflow-designer')
              ?.querySelector<HTMLButtonElement>('[data-workflow-add]')
              ?.click()
        : undefined,
      selectAll: async () => {
        if (!(await input.finishSelectionChange())) return
        editor.select({
          nodeIds: editor.definition.nodes.map((node) => node.id),
          edgeIds: editor.definition.edges.map((edge) => edge.id),
          primary: null,
        })
      },
      configure: input.configureInspector,
      focus:
        input.surface === 'workspace' ? () => input.setFocusMode((value) => !value) : undefined,
      help: () => input.setShortcutHelp(true),
      escape: () => escapeCanvas(input),
    },
    input.confirming || input.shortcutHelp,
  )
}
function canCopyNode(node: WorkflowNode | null, count: number): boolean {
  return Boolean(node && resolveEffectiveNodeType(node) !== 'start' && count === 1)
}
function escapeCanvas(input: DesignerHotkeyInput) {
  if (input.editor.dragging) input.editor.cancelDrag()
  else if (input.editor.selection.nodeIds.length || input.editor.selection.edgeIds.length)
    void input.clearSelection()
  else input.setFocusMode(false)
}

function canMutateGraph(editable: boolean, mode: string, runtimeMode?: string): boolean {
  return editable && mode === 'edit' && runtimeMode === undefined
}
function ViewActions({
  surface,
  focusMode,
  onFocus,
  onHelp,
}: {
  surface: string
  focusMode: boolean
  onFocus: () => void
  onHelp: () => void
}) {
  return (
    <Space className="workflow-view-actions">
      <Button onClick={onHelp}>快捷键帮助</Button>
      {surface === 'workspace' && (
        <Button onClick={onFocus}>{focusMode ? '退出专注模式' : '专注模式'}</Button>
      )}
    </Space>
  )
}

function editorUserId(store: { user: { id: string } | null }): string {
  return store.user?.id ?? 'anonymous'
}
function editorProjectId(projectId?: string | null): string {
  return projectId ?? 'embedded'
}

function hasSelection(selection: {
  nodeIds: readonly string[]
  edgeIds: readonly string[]
}): boolean {
  return selection.nodeIds.length + selection.edgeIds.length > 0
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
  flow: ReactFlowInstance<CanvasNode, Edge> | null,
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
  return {
    nodeIds: [draft.nodeId],
    edgeIds: [],
    primary: { kind: 'node' as const, id: draft.nodeId },
  }
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
function libraryUnavailableReasons(input: {
  hasArtifacts: boolean
  hasDataset: boolean
  hasSqlCredential: boolean
  hasRedisCredential: boolean
  graphqlCount: number
  grpcCount: number
  kafkaCount: number
  websocketCount: number
  subflowCount: number
}): string[] {
  return [
    [input.hasArtifacts, '数据集需要先上传文件'],
    [!input.hasDataset, '流程已包含数据集'],
    [input.hasSqlCredential, 'SQL 需要数据库凭据'],
    [input.hasRedisCredential, 'Redis 需要对应凭据'],
    [input.graphqlCount, 'GraphQL 需要 Schema'],
    [input.grpcCount, 'gRPC 需要 Descriptor'],
    [input.kafkaCount, 'Kafka 需要事件源'],
    [input.websocketCount, 'WebSocket 需要事件源'],
    [input.subflowCount, '流程复用需要已发布子流程'],
  ]
    .filter(([available]) => !available)
    .map(([, reason]) => String(reason))
}

function showInspector(
  selection: import('./editor/editor-types').EditorSelection,
  focused: boolean,
): boolean {
  return hasSelection(selection) && !focused
}
