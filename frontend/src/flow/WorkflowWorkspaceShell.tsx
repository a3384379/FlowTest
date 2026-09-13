import { Button, Splitter } from 'antd'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { readLayoutPreferences, writeLayoutPreferences } from './editor/layout-preferences'
export default function WorkflowWorkspaceShell({
  header,
  list,
  children,
  runtimeDock,
  preferenceKey,
}: {
  header: ReactNode
  list: ReactNode
  children: ReactNode
  runtimeDock?: ReactNode
  preferenceKey: string
}) {
  const root = useRef<HTMLDivElement>(null)
  const [preferences, setPreferences] = useState(() => readLayoutPreferences(preferenceKey))
  const [width, setWidth] = useState(0)
  const [storageError, setStorageError] = useState(false)
  useEffect(() => {
    if (!root.current) return
    const observer = new ResizeObserver((entries) => setWidth(entries[0]?.contentRect.width ?? 0))
    observer.observe(root.current)
    return () => observer.disconnect()
  }, [])
  const collapsed = listCollapsed(preferences.listCollapsed, width)
  function toggleList() {
    const patch = { listCollapsed: !collapsed }
    setPreferences((current) => ({ ...current, ...patch }))
    setStorageError(!writeLayoutPreferences(preferenceKey, patch))
  }
  function saveWidth(sizes: number[]) {
    if (collapsed || !Number.isFinite(sizes[0])) return
    setStorageError(!writeLayoutPreferences(preferenceKey, { listWidth: sizes[0] }))
  }
  return (
    <div ref={root} className="workflow-workspace" data-testid="workflow-workbench">
      {header}
      <Button
        className="workflow-list-toggle"
        aria-label="切换工作流列表"
        aria-expanded={!collapsed}
        onClick={toggleList}
      >
        列表
      </Button>
      {storageError && (
        <span role="status" className="workflow-layout-status">
          布局偏好未保存
        </span>
      )}
      <Splitter
        onResize={(sizes) => {
          if (sizes[0] >= 180) setPreferences((current) => ({ ...current, listWidth: sizes[0] }))
        }}
        onResizeEnd={saveWidth}
      >
        <Splitter.Panel
          size={collapsed ? 0 : preferences.listWidth}
          min={collapsed ? 0 : 180}
          max={320}
          resizable={!collapsed}
        >
          <div className="workflow-list-pane" data-testid="workflow-list-panel" hidden={collapsed}>
            {list}
          </div>
        </Splitter.Panel>
        <Splitter.Panel min={0}>
          <div className="workflow-workspace-main" data-testid="workflow-editor-main">
            {children}
            {runtimeDock}
          </div>
        </Splitter.Panel>
      </Splitter>
    </div>
  )
}
function listCollapsed(preference: boolean | null, width: number): boolean {
  if (preference === true) return true
  if (width > 0 && width < 920) return true
  if (preference === false) return false
  return width > 0 && width < 1120
}
