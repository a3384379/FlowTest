import { Dropdown } from 'antd'
export type WorkflowMenuAction = { key: string; label: string; disabled?: boolean; run: () => void }
export default function WorkflowContextMenu({
  point,
  actions,
  onClose,
}: {
  point: { x: number; y: number } | null
  actions: WorkflowMenuAction[]
  onClose: () => void
}) {
  if (!point) return null
  return (
    <Dropdown
      open
      trigger={[]}
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
      menu={{
        items: actions.map(({ key, label, disabled }) => ({ key, label, disabled })),
        onClick: ({ key }) => {
          const action = actions.find((item) => item.key === key)
          if (action && !action.disabled) action.run()
          onClose()
        },
      }}
    >
      <span
        style={{
          position: 'fixed',
          left: point.x,
          top: point.y,
          width: 1,
          height: 1,
          zIndex: 1000,
        }}
      />
    </Dropdown>
  )
}
