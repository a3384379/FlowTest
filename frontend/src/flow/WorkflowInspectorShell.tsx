import { readLayoutPreferences, writeLayoutPreferences } from './editor/layout-preferences'
import { useInspectorDialog } from './editor/use-inspector-dialog'
import { InspectorPresentationContext } from './editor/inspector-presentation'
import { CloseOutlined, ExpandOutlined, ShrinkOutlined } from '@ant-design/icons'
import { Button, Space, Splitter } from 'antd'
import { useEffect, useRef, useState, type ReactNode } from 'react'

export default function WorkflowInspectorShell({
  canvas,
  children,
  visible,
  onClose,
  preferenceKey,
  title = '配置面板',
}: {
  canvas: ReactNode
  children: ReactNode
  visible: boolean
  onClose: () => void
  preferenceKey: string
  title?: string
}) {
  const container = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(0)
  const [inspectorWidth, setInspectorWidth] = useState(
    () => readLayoutPreferences(preferenceKey).inspectorWidth,
  )
  const [maximized, setMaximized] = useState(false)
  const [storageError, setStorageError] = useState(false)
  const inspector = useRef<HTMLDivElement>(null)
  const dialogKeyDown = useInspectorDialog(maximized, inspector, () => setMaximized(false))
  useEffect(() => {
    if (!container.current) return
    const observer = new ResizeObserver((entries) => setWidth(entries[0]?.contentRect.width ?? 0))
    observer.observe(container.current)
    return () => observer.disconnect()
  }, [])
  const overlay = width > 0 && width < 880
  const docked = visible && !overlay
  function saveWidth(sizes: number[]) {
    const size = sizes[1]
    if (!Number.isFinite(size) || size < 320) return
    setStorageError(!writeLayoutPreferences(preferenceKey, { inspectorWidth: size }))
  }
  return (
    <div ref={container} className={inspectorShellClassName(overlay, maximized)}>
      <Splitter
        onResize={(sizes) => {
          if (sizes[1] >= 320) setInspectorWidth(sizes[1])
        }}
        onResizeEnd={saveWidth}
      >
        <Splitter.Panel min={canvasMinimumWidth(overlay, width)}>{canvas}</Splitter.Panel>
        <Splitter.Panel
          size={docked ? inspectorWidth : 0}
          min={docked ? 320 : 0}
          max={640}
          resizable={docked}
        >
          <div
            ref={inspector}
            className="workflow-inspector-shell"
            data-testid="workflow-inspector"
            hidden={!visible}
            {...dialogAttributes(maximized)}
            aria-label="节点与连线配置"
            onKeyDown={dialogKeyDown}
          >
            <div className="workflow-inspector-controls">
              <strong>{title}</strong>
              <Space>
                <InspectorMaximizeButton
                  maximized={maximized}
                  onClick={() => setMaximized((value) => !value)}
                />
                <Button
                  type="text"
                  icon={<CloseOutlined />}
                  aria-label="关闭配置"
                  onClick={onClose}
                />
              </Space>
            </div>
            {storageError && <p role="status">布局偏好未保存</p>}
            <div className="workflow-inspector-body">
              <InspectorPresentationContext.Provider value={maximized ? 'fullscreen' : 'quick'}>
                {children}
              </InspectorPresentationContext.Provider>
            </div>
          </div>
        </Splitter.Panel>
      </Splitter>
    </div>
  )
}

function InspectorMaximizeButton({
  maximized,
  onClick,
}: {
  maximized: boolean
  onClick: () => void
}) {
  return (
    <Button
      type="text"
      aria-label={maximized ? '还原配置' : '最大化配置'}
      icon={maximized ? <ShrinkOutlined /> : <ExpandOutlined />}
      onClick={onClick}
    >
      {maximized ? '还原配置' : '最大化配置'}
    </Button>
  )
}
function dialogAttributes(active: boolean) {
  return { role: active ? 'dialog' : undefined, 'aria-modal': active || undefined }
}

function inspectorShellClassName(overlay: boolean, maximized: boolean): string {
  return `workflow-designer-body workflow-split-body${overlay ? ' inspector-overlay' : ''}${maximized ? ' inspector-maximized' : ''}`
}

function canvasMinimumWidth(overlay: boolean, containerWidth: number): number {
  if (overlay) return 0
  return Math.max(480, Math.ceil(containerWidth * 0.52))
}
