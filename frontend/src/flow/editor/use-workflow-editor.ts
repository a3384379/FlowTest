import { useEffect, useRef, useState } from 'react'
import type { NodeChange, EdgeChange } from '@xyflow/react'
import type { WorkflowDefinition } from '../../lib/api'
import { applyDeletion, applyNodePositions, planDeletion } from './graph-commands'
import {
  emptySelection,
  jsonEqual,
  type EditorSelection,
  type GraphEditResult,
  type NodePositionUpdate,
} from './editor-types'

type HistoryEntry = {
  before: WorkflowDefinition
  after: WorkflowDefinition
  selectionBefore: EditorSelection
  selectionAfter: EditorSelection
}
type EditorState = {
  definition: WorkflowDefinition
  selection: EditorSelection
  past: HistoryEntry[]
  future: HistoryEntry[]
  positions: Map<string, NodePositionUpdate['position']>
  dragging: boolean
  message: string | null
}
function initialState(definition: WorkflowDefinition): EditorState {
  return {
    definition,
    selection: emptySelection(),
    past: [],
    future: [],
    positions: new Map(),
    dragging: false,
    message: null,
  }
}
function pruneSelection(
  selection: EditorSelection,
  definition: WorkflowDefinition,
): EditorSelection {
  const nodeIds = selection.nodeIds.filter((id) => definition.nodes.some((node) => node.id === id))
  const edgeIds = selection.edgeIds.filter((id) => definition.edges.some((edge) => edge.id === id))
  const primary = selection.primary
  return {
    nodeIds,
    edgeIds,
    primary:
      primary && (primary.kind === 'node' ? nodeIds : edgeIds).includes(primary.id)
        ? primary
        : null,
  }
}
export function useWorkflowEditor(
  definition: WorkflowDefinition,
  canEdit: boolean,
  onChange: (next: WorkflowDefinition) => void,
  initialSelection: EditorSelection = emptySelection(),
) {
  const latest = useRef({ ...initialState(definition), selection: initialSelection })
  const [state, setState] = useState(latest.current)
  const mode = useRef(canEdit)
  const callback = useRef(onChange)
  const cancelledDrag = useRef(false)
  useEffect(() => {
    mode.current = canEdit
    callback.current = onChange
  }, [canEdit, onChange])
  useEffect(() => {
    if (jsonEqual(definition, latest.current.definition)) return
    cancelledDrag.current = true
    const next = {
      ...initialState(definition),
      selection: pruneSelection(latest.current.selection, definition),
      message: '流程已从外部更新，撤销历史已重置',
    }
    latest.current = next
    queueMicrotask(() => {
      if (latest.current === next) setState(next)
    })
  }, [definition])
  useEffect(() => {
    if (canEdit) return
    const next = { ...latest.current, positions: new Map(), dragging: false }
    latest.current = next
    queueMicrotask(() => {
      if (latest.current === next) setState(next)
    })
  }, [canEdit])
  useEffect(() => {
    const blur = () => {
      cancelledDrag.current = true
      const next = { ...latest.current, positions: new Map(), dragging: false }
      latest.current = next
      setState(next)
    }
    window.addEventListener('blur', blur)
    return () => window.removeEventListener('blur', blur)
  }, [])
  function publish(next: EditorState) {
    latest.current = next
    setState(next)
  }
  function commit(next: WorkflowDefinition, selection = latest.current.selection): boolean {
    const current = latest.current
    if (!mode.current || jsonEqual(current.definition, next)) return false
    const nextSelection = pruneSelection(selection, next)
    const entry = {
      before: structuredClone(current.definition),
      after: structuredClone(next),
      selectionBefore: current.selection,
      selectionAfter: nextSelection,
    }
    publish({
      ...current,
      definition: next,
      selection: nextSelection,
      past: [...current.past.slice(-49), entry],
      future: [],
      positions: new Map(),
      dragging: false,
      message: null,
    })
    callback.current(next)
    return true
  }
  function accept(result: GraphEditResult): boolean {
    if (result.kind === 'blocked') {
      notify(result.diagnostics.map((issue) => issue.message).join('；'))
      return false
    }
    return result.kind === 'changed' && commit(result.definition)
  }
  function notify(message: string | null) {
    publish({ ...latest.current, message })
  }
  function select(selection: EditorSelection) {
    if (jsonEqual(selection, latest.current.selection)) return
    publish({ ...latest.current, selection })
  }
  function click(kind: 'node' | 'edge', id: string, multiple = false) {
    const current = latest.current.selection
    const ids = kind === 'node' ? current.nodeIds : current.edgeIds
    if (multiple || ids.includes(id)) {
      select({
        ...current,
        [kind === 'node' ? 'nodeIds' : 'edgeIds']: [...new Set([...ids, id])],
        primary: { kind, id },
      })
      return
    }
    select({
      nodeIds: kind === 'node' ? [id] : [],
      edgeIds: kind === 'edge' ? [id] : [],
      primary: { kind, id },
    })
  }
  function selectionChanges(kind: 'node' | 'edge', changes: Array<NodeChange | EdgeChange>) {
    const current = latest.current.selection
    const ids = new Set(kind === 'node' ? current.nodeIds : current.edgeIds)
    for (const change of changes) {
      if (change.type !== 'select') continue
      if (change.selected) ids.add(change.id)
      else ids.delete(change.id)
    }
    select(
      pruneSelection(
        { ...current, [kind === 'node' ? 'nodeIds' : 'edgeIds']: [...ids] },
        latest.current.definition,
      ),
    )
  }
  function positionsChanged(updates: NodePositionUpdate[], dragging?: boolean) {
    if (!canApplyPositions(mode.current, updates.length, cancelledDrag.current, dragging)) return
    if (!latest.current.dragging && dragging === undefined) {
      accept(applyNodePositions(latest.current.definition, updates))
      return
    }
    const positions = new Map(latest.current.positions)
    updates.forEach((update) => positions.set(update.id, update.position))
    publish({ ...latest.current, positions })
    if (dragging === false) endDrag(updates)
  }
  function beginDrag() {
    cancelledDrag.current = false
    if (mode.current) publish({ ...latest.current, dragging: true, positions: new Map() })
  }
  function endDrag(updates: NodePositionUpdate[]) {
    if (cancelledDrag.current) return
    if (!latest.current.dragging && !latest.current.positions.size) return
    const positions = new Map(latest.current.positions)
    updates.forEach((update) => positions.set(update.id, update.position))
    accept(
      applyNodePositions(
        latest.current.definition,
        [...positions].map(([id, position]) => ({ id, position })),
      ),
    )
    cancelDrag()
  }
  function cancelDrag() {
    cancelledDrag.current = true
    publish({ ...latest.current, positions: new Map(), dragging: false })
  }
  function travel(direction: 'undo' | 'redo') {
    if (!mode.current) return
    const current = latest.current
    const entries = direction === 'undo' ? current.past : current.future
    const entry = entries.at(-1)
    if (!entry) return
    const undo = direction === 'undo'
    const next = structuredClone(undo ? entry.before : entry.after)
    publish({
      ...current,
      definition: next,
      selection: undo ? entry.selectionBefore : entry.selectionAfter,
      past: undo ? current.past.slice(0, -1) : [...current.past, entry],
      future: undo ? [...current.future, entry] : current.future.slice(0, -1),
      positions: new Map(),
      dragging: false,
    })
    callback.current(next)
  }
  function deleteSelection() {
    const plan = planDeletion(latest.current.definition, latest.current.selection)
    const result = accept(applyDeletion(latest.current.definition, plan))
    if (plan.protectedNodeIds.length) notify('已跳过开始节点和唯一结束节点')
    else if (result) notify('已删除选中对象，可撤销恢复；流程可能暂时不完整')
    return result
  }
  return {
    ...state,
    latest,
    commit,
    accept,
    notify,
    select,
    click,
    selectionChanges,
    positionsChanged,
    beginDrag,
    endDrag,
    cancelDrag,
    deleteSelection,
    undo: () => travel('undo'),
    redo: () => travel('redo'),
  }
}

function canApplyPositions(
  editable: boolean,
  count: number,
  cancelled: boolean,
  dragging: boolean | undefined,
): boolean {
  return editable && count > 0 && !(cancelled && dragging !== undefined)
}
