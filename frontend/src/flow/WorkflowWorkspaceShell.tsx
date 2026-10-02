import { Button, Drawer } from 'antd'
import { useRef, useState, type ReactNode } from 'react'
import { readLayoutPreferences } from './editor/layout-preferences'
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
  const trigger = useRef<HTMLButtonElement>(null)
  const [listOpen, setListOpen] = useState(false)
  const [preferences] = useState(() => readLayoutPreferences(preferenceKey))
  return (
    <div ref={root} className="workflow-workspace" data-testid="workflow-workbench">
      {header}
      <Button
        ref={trigger}
        className="workflow-list-toggle"
        aria-label="切换工作流列表"
        aria-expanded={listOpen}
        onClick={() => setListOpen((open) => !open)}
      >
        列表
      </Button>
      <Drawer
        title="工作流列表"
        open={listOpen}
        onClose={() => setListOpen(false)}
        placement="left"
        size={Math.max(280, preferences.listWidth)}
        getContainer={false}
        rootClassName="workflow-catalog-drawer"
        styles={{ root: { position: 'absolute' }, body: { padding: 0 } }}
        afterOpenChange={(open) => !open && trigger.current?.focus()}
      >
        <div className="workflow-list-pane" data-testid="workflow-list-panel">
          {list}
        </div>
      </Drawer>
      <div className="workflow-workspace-main" data-testid="workflow-editor-main">
        {children}
        {runtimeDock}
      </div>
    </div>
  )
}
