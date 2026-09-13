import type { ReactNode } from 'react'

export default function WorkflowWorkbenchHeader({
  left,
  center,
  right,
}: {
  left: ReactNode
  center: ReactNode
  right: ReactNode
}) {
  return (
    <header className="workflow-workbench-header" data-testid="workflow-workbench-header">
      <div className="workflow-workbench-header-left">{left}</div>
      <div className="workflow-workbench-header-center">{center}</div>
      <div className="workflow-workbench-header-right">{right}</div>
    </header>
  )
}
