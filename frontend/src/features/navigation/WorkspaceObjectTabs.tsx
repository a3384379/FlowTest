import { useQueryClient, type QueryClient } from '@tanstack/react-query'
import { Alert, Button, Dropdown, Modal, Space, Tabs, Typography } from 'antd'
import { useEffect, useState, useSyncExternalStore } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

import {
  DRAFT_NAVIGATION_CANCELLED,
  useDraftSession,
  type DraftSession,
} from '../drafts/draft-session'
import { nodeEditorScope } from '../../flow/editor/editor-identity'
import type { ApiDetail, ReportExecutionDetail, Workflow } from '../../lib/api'
import { projectPath } from '../projects/project-routing'
import {
  readWorkflowDraft,
  workflowDraftKey,
  WORKFLOW_DRAFT_EVENT,
} from '../workflows/workflow-draft-store'
import {
  readWorkspaceTabs,
  routeWorkspaceTab,
  writeWorkspaceTabs,
  type WorkspaceTab,
} from './workspace-tab-store'

type Props = { userId: string; projectId: string }
type PendingClose = { keys: string[]; targetHref: string }

export default function WorkspaceObjectTabs({ userId, projectId }: Props) {
  const location = useLocation()
  const navigate = useNavigate()
  const session = useDraftSession()
  useSyncExternalStore(session.subscribe, session.snapshot)
  const queryClient = useQueryClient()
  const [initial] = useState(() => readWorkspaceTabs(userId, projectId))
  const [tabs, setTabs] = useState(initial.tabs)
  const [storageError, setStorageError] = useState(initial.error)
  const [confirmation, setConfirmation] = useState<string[] | null>(null)
  const [pending, setPending] = useState<PendingClose | null>(null)
  const [, refreshDrafts] = useState(0)
  const href = `${location.pathname}${location.search}${location.hash}`
  const active = routeWorkspaceTab(projectId, href)

  useEffect(() => {
    const cancel = () => setPending(null)
    const changed = () => refreshDrafts((value) => value + 1)
    window.addEventListener(DRAFT_NAVIGATION_CANCELLED, cancel)
    window.addEventListener(WORKFLOW_DRAFT_EVENT, changed)
    window.addEventListener('storage', changed)
    return () => {
      window.removeEventListener(DRAFT_NAVIGATION_CANCELLED, cancel)
      window.removeEventListener(WORKFLOW_DRAFT_EVENT, changed)
      window.removeEventListener('storage', changed)
    }
  }, [])

  useEffect(() => {
    const error = writeWorkspaceTabs(userId, projectId, tabs)
    queueMicrotask(() => setStorageError(error))
  }, [tabs, projectId, userId])

  useEffect(() => {
    const route = routeWorkspaceTab(projectId, href)
    if (!route) return
    queueMicrotask(() => {
      setTabs((previous) => {
        const retained =
          pending?.targetHref === href
            ? previous.filter((tab) => !pending.keys.includes(tab.key))
            : previous
        const existing = retained.find((tab) => tab.key === route.key)
        return existing
          ? retained.map((tab) => (tab.key === route.key ? { ...tab, href } : tab))
          : [...retained, route]
      })
      if (pending?.targetHref === href) setPending(null)
    })
  }, [href, pending, projectId])

  function commitClose(keys: string[]) {
    setConfirmation(null)
    const retained = tabs.filter((tab) => !keys.includes(tab.key))
    if (active && keys.includes(active.key)) {
      const targetHref = retained.at(-1)?.href ?? projectPath(projectId, 'dashboard')
      setPending({ keys, targetHref })
      void navigate(targetHref)
      return
    }
    setTabs(retained)
  }

  function requestClose(keys: string[]) {
    const closing = tabs.filter((tab) => keys.includes(tab.key) && tab.section !== 'dashboard')
    const activeUnsafe =
      active && closing.some((tab) => tab.key === active.key) && session.unsafe.size > 0
    if (!activeUnsafe && closing.some((tab) => hasDraft(tab, session, userId, projectId))) {
      setConfirmation(closing.map((tab) => tab.key))
      return
    }
    commitClose(closing.map((tab) => tab.key))
  }

  function updateLabel(key: string, label: string) {
    setTabs((previous) => {
      if (previous.find((tab) => tab.key === key)?.label === label) return previous
      return previous.map((tab) => (tab.key === key ? { ...tab, label } : tab))
    })
  }

  return (
    <>
      {storageError && <Alert type="warning" title={storageError} />}
      <div aria-label="全局对象工作区">
        <Tabs
          className="workspace-navigation-tabs"
          type="editable-card"
          hideAdd
          activeKey={active?.key}
          items={tabs.map((tab) => ({
            key: tab.key,
            closable: tab.section !== 'dashboard',
            label: (
              <ObjectTabLabel
                tab={tab}
                projectId={projectId}
                queryClient={queryClient}
                dirty={hasDraft(tab, session, userId, projectId)}
                onLabelChange={updateLabel}
                onClose={requestClose}
                allKeys={tabs
                  .filter((item) => item.section !== 'dashboard')
                  .map((item) => item.key)}
              />
            ),
          }))}
          onChange={(key) => {
            const tab = tabs.find((item) => item.key === key)
            if (tab) void navigate(tab.href)
          }}
          onEdit={(key, action) => {
            if (action === 'remove') requestClose([String(key)])
          }}
        />
      </div>
      <Modal
        title="关闭有本地修改的工作区标签"
        open={Boolean(confirmation)}
        onCancel={() => setConfirmation(null)}
        footer={
          <Space>
            <Button onClick={() => setConfirmation(null)}>继续编辑</Button>
            <Button type="primary" onClick={() => commitClose(confirmation ?? [])}>
              保留草稿并关闭标签
            </Button>
          </Space>
        }
      >
        这些标签有本地草稿。关闭后草稿仍保留，可从目录重新打开继续编辑；此操作不会保存为服务器版本。尚未持久化的输入只保留在当前会话，刷新或退出前请返回编辑页保存。
      </Modal>
    </>
  )
}

function hasDraft(
  tab: WorkspaceTab,
  session: DraftSession,
  userId: string,
  projectId: string,
): boolean {
  if (!tab.objectId) return false
  if (tab.section === 'workflows') {
    const dirtyNode =
      session.dirtyNodeEditorKeys(nodeEditorScope(userId, projectId, tab.objectId)).length > 0
    const memory = session.workflows.get(`${userId}:${projectId}`)?.drafts.has(tab.objectId)
    return Boolean(
      dirtyNode || memory || readWorkflowDraft(workflowDraftKey(userId, projectId, tab.objectId)),
    )
  }
  if (tab.section !== 'apis') return false
  return hasApiDraft(tab.objectId, session, userId, projectId)
}

function hasApiDraft(
  apiId: string,
  session: DraftSession,
  userId: string,
  projectId: string,
): boolean {
  const scope = `${userId}:${projectId}`
  if (session.apis.has(JSON.stringify([scope, apiId]))) return true
  try {
    return (
      localStorage.getItem(
        `flowtest:api-draft:v1:${encodeURIComponent(scope)}:${encodeURIComponent(apiId)}`,
      ) !== null
    )
  } catch {
    return false
  }
}

function ObjectTabLabel({
  tab,
  projectId,
  queryClient,
  dirty,
  onLabelChange,
  onClose,
  allKeys,
}: {
  tab: WorkspaceTab
  projectId: string
  queryClient: QueryClient
  dirty: boolean
  onLabelChange: (key: string, label: string) => void
  onClose: (keys: string[]) => void
  allKeys: string[]
}) {
  const cached = useSyncExternalStore(
    (notify) => queryClient.getQueryCache().subscribe(notify),
    () => cachedLabel(queryClient, projectId, tab),
  )
  useEffect(() => {
    if (cached && cached !== tab.label) onLabelChange(tab.key, cached)
  }, [cached, onLabelChange, tab.key, tab.label])
  const label = cached ?? tab.label
  return (
    <Dropdown
      trigger={['contextMenu']}
      menu={{
        items: [
          { key: 'current', label: '关闭当前标签', disabled: tab.section === 'dashboard' },
          { key: 'others', label: '关闭其他标签' },
          { key: 'all', label: '关闭全部对象标签' },
        ],
        onClick: ({ key }) =>
          onClose(
            key === 'current'
              ? [tab.key]
              : key === 'others'
                ? allKeys.filter((item) => item !== tab.key)
                : allKeys,
          ),
      }}
    >
      <Typography.Text title={tab.href}>
        {label}
        {dirty ? ' ·' : ''}
      </Typography.Text>
    </Dropdown>
  )
}

function cachedLabel(client: QueryClient, projectId: string, tab: WorkspaceTab): string | null {
  if (!tab.objectId) return null
  if (tab.section === 'workflows') {
    const workflow = client.getQueryData<Workflow>(['workflow', projectId, tab.objectId])
    return workflow ? `流程 · ${workflow.name}` : null
  }
  if (tab.section === 'apis') {
    const detail = client.getQueryData<ApiDetail>(['api-detail', projectId, tab.objectId])
    return detail ? `接口 · ${detail.definition.name}` : null
  }
  const detail = client.getQueryData<ReportExecutionDetail>([
    'report-detail',
    projectId,
    tab.objectId,
  ])
  return detail ? `报告 · ${detail.summary.workflow_name} · ${tab.objectId.slice(0, 8)}` : null
}
