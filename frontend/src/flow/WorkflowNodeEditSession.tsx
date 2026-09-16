import { restoreEditedNode } from './editor/graph-analysis'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Alert, Button, Modal, Space, Typography } from 'antd'
import type { WorkflowDefinition, WorkflowNode } from '../lib/api'
import { useDraftSession } from '../features/drafts/draft-session'
import {
  NodeEditContext,
  type RawFieldDraft,
  type WorkflowNodeEditorDraft,
  type WorkflowRequestEditorDraft,
  type WorkflowRequestIdentity,
} from './editor/node-edit-session'
import { jsonEqual } from './editor/editor-types'
import {
  applyRequestEditorDraft,
  requestIdentityMatches,
  sameRequestTarget,
  canApplyRequestTarget,
} from './editor/request-overrides'

function nodeContent(node: WorkflowNode): Omit<WorkflowNode, 'position'> {
  const { position: _position, ...content } = node
  void _position
  return content
}
export default function WorkflowNodeEditSession({
  scope,
  projectId = '',
  node,
  definition,
  editable,
  onChange,
  children,
}: {
  scope: string
  projectId?: string | null
  node: WorkflowNode
  definition: WorkflowDefinition
  editable: boolean
  onChange: (definition: WorkflowDefinition) => void
  children: (node: WorkflowNode, update: (definition: WorkflowDefinition) => void) => ReactNode
}) {
  const session = useDraftSession()
  const key = `${scope}${encodeURIComponent(node.id)}`
  const [draft, setDraft] = useState<WorkflowNodeEditorDraft>(
    () =>
      session.nodeEditors.get(key) ?? {
        nodeId: node.id,
        baseNode: structuredClone(node),
        draftNode: structuredClone(node),
        generation: session.nextGeneration(),
        dirty: false,
        rawFields: {},
        activeTab: 'params',
        requestDraft: null,
        requestDirty: false,
      },
  )
  const latest = useRef(draft)
  const requestApply = useRef<(() => Promise<boolean>) | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [modal, holder] = Modal.useModal()
  useEffect(() => {
    if (latest.current.dirty || jsonEqual(latest.current.baseNode, node)) return
    const clean = {
      ...latest.current,
      baseNode: structuredClone(node),
      draftNode: structuredClone(node),
      rawFields: {},
      requestDraft: null,
      requestDirty: false,
      generation: session.nextGeneration(),
    }
    latest.current = clean
    session.clearNodeEditor(key)
    queueMicrotask(() => {
      if (latest.current !== clean) return
      setDraft(clean)
      setError(null)
    })
  }, [node, session, key])
  function update(next: WorkflowNodeEditorDraft) {
    latest.current = next
    session.updateNodeEditor(key, next)
    setDraft(next)
  }
  function setRaw(field: string, value: RawFieldDraft) {
    update({
      ...latest.current,
      dirty: true,
      rawFields: { ...latest.current.rawFields, [field]: value },
    })
  }
  function setRequest(value: WorkflowRequestEditorDraft, dirty = true) {
    if (!isRequestCurrent(value.identity)) return
    update({
      ...latest.current,
      dirty: latest.current.dirty || dirty,
      requestDraft: value,
      requestDirty: latest.current.requestDirty || dirty,
    })
  }
  function isRequestCurrent(identity: WorkflowRequestIdentity): boolean {
    return requestIdentityMatches(latest.current.draftNode, identity, projectId ?? '')
  }
  function apply(replacement = latest.current.draftNode): boolean {
    if (!editable) return false
    if (!canApplyRequestTarget(latest.current.draftNode, replacement)) {
      setError('请求目标已变更，请重新载入请求配置。')
      return false
    }
    const current = definition.nodes.find((item) => item.id === node.id)
    if (!current || !jsonEqual(nodeContent(current), nodeContent(latest.current.baseNode))) {
      setError('节点内容已从外部更新，请保留输入并重新载入后处理冲突。')
      return false
    }
    if (
      !replacement.name.trim() ||
      replacement.name.length > 200 ||
      Object.values(latest.current.rawFields).some((field) => field.error)
    ) {
      setError('请检查节点名称与 JSON 字段，修正错误后再应用。')
      return false
    }
    const next = { ...restoreEditedNode(current, replacement), position: current.position }
    onChange({
      ...definition,
      nodes: definition.nodes.map((item) => (item.id === node.id ? next : item)),
    })
    session.clearNodeEditor(key)
    const clean = {
      ...latest.current,
      baseNode: structuredClone(next),
      draftNode: structuredClone(next),
      dirty: false,
      rawFields: {},
      requestDraft: null,
      requestDirty: false,
    }
    latest.current = clean
    setDraft(clean)
    setError(null)
    return true
  }
  const applyRef = useRef<() => Promise<boolean>>(async () => false)
  useEffect(() => {
    applyRef.current = async () => {
      if (requestApply.current) return requestApply.current()
      if (!latest.current.requestDraft) return apply()
      try {
        return apply(applyRequestEditorDraft(latest.current.draftNode, latest.current.requestDraft))
      } catch {
        setError('请修正请求字段和 JSON 格式后再应用。')
        return false
      }
    }
  })
  useEffect(() => {
    session.nodeEditorActions.set(key, () => applyRef.current())
    return () => {
      session.nodeEditorActions.delete(key)
    }
  }, [session, key])
  async function discard() {
    if (
      !(await modal.confirm({
        title: '丢弃本次节点修改？',
        content: '未应用的字段和原始输入将被丢弃。',
        okText: '丢弃修改',
        cancelText: '继续编辑',
      }))
    )
      return
    session.clearNodeEditor(key)
    update({
      ...latest.current,
      baseNode: structuredClone(node),
      draftNode: structuredClone(node),
      dirty: false,
      rawFields: {},
      requestDraft: null,
      requestDirty: false,
      generation: session.nextGeneration(),
    })
    setError(null)
  }
  const switching = useRef(false)
  async function updateNode(updated: WorkflowNode) {
    if (switching.current || !editable) return
    const previous = latest.current
    const targetChanged = !sameRequestTarget(previous.draftNode, updated)
    if (targetChanged && previous.requestDirty) {
      switching.current = true
      const confirmed = await modal.confirm({
        title: '切换请求目标？',
        content: '接口或版本将发生变化。未应用的请求输入将被丢弃，已应用的配置按新目标重新载入。',
        okText: '丢弃请求草稿并切换',
        cancelText: '取消切换',
      })
      switching.current = false
      if (!confirmed || latest.current !== previous) return
    }
    if (targetChanged) requestApply.current = null
    update({
      ...latest.current,
      draftNode: updated,
      dirty: true,
      ...(targetChanged
        ? { requestDraft: null, requestDirty: false, generation: session.nextGeneration() }
        : {}),
    })
    setError(null)
  }
  function updateDefinition(next: WorkflowDefinition) {
    const updated = next.nodes.find((item) => item.id === node.id)
    const current = definition.nodes.find((item) => item.id === node.id)
    if (updated && !jsonEqual(updated, current)) void updateNode(updated)
    if (!jsonEqual(next.edges, definition.edges)) onChange({ ...definition, edges: next.edges })
  }
  return (
    <NodeEditContext.Provider
      value={{
        draft,
        setRaw,
        setRequest,
        isRequestCurrent,
        apply,
        registerRequestApply: (value) => {
          requestApply.current = value
        },
      }}
    >
      {holder}
      {error && <Alert type="error" title={error} />}
      <div key={draft.generation}>
        <SessionContent
          render={children}
          node={editable ? draft.draftNode : node}
          onChange={updateDefinition}
        />
      </div>
      {editable && (
        <Space className="workflow-session-actions" wrap>
          <Button type="primary" onClick={() => void applyRef.current()}>
            应用节点配置
          </Button>
          <Button disabled={!draft.dirty} onClick={() => void discard()}>
            丢弃修改
          </Button>
          <Typography.Text type="secondary">
            {draft.dirty ? '配置尚未应用' : '配置已应用到本地流程'}
          </Typography.Text>
        </Space>
      )}
    </NodeEditContext.Provider>
  )
}

function SessionContent({
  render,
  node,
  onChange,
}: {
  render: (node: WorkflowNode, update: (definition: WorkflowDefinition) => void) => ReactNode
  node: WorkflowNode
  onChange: (definition: WorkflowDefinition) => void
}) {
  return render(node, onChange)
}
