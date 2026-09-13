import { Alert, Button, Drawer } from 'antd'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useAuthStore } from '../features/auth/auth-store'
import {
  readLayoutPreferences,
  workflowLayoutKey,
  writeLayoutPreferences,
} from './editor/layout-preferences'
export default function WorkflowRequestDrawer({
  projectId,
  open,
  onClose,
  children,
}: {
  projectId?: string | null
  open: boolean
  onClose: () => void
  children: ReactNode
}) {
  const userId = useAuthStore((store) => store.user?.id)
  const key = workflowLayoutKey(userId, projectId)
  const [width, setWidth] = useState(() => readLayoutPreferences(key).requestWidth)
  const latestWidth = useRef(width)
  const [viewport, setViewport] = useState(window.innerWidth)
  const [maximized, setMaximized] = useState(false)
  const [error, setError] = useState(false)
  useEffect(() => {
    const resize = () => setViewport(window.innerWidth)
    window.addEventListener('resize', resize)
    return () => window.removeEventListener('resize', resize)
  }, [])
  function resize(size: number) {
    const next = Math.max(Math.min(480, viewport), Math.min(size, viewport))
    latestWidth.current = next
    setWidth(next)
  }
  return (
    <Drawer
      title="节点请求配置"
      open={open}
      onClose={onClose}
      size={maximized ? '100vw' : Math.min(width, viewport)}
      resizable={{
        onResize: resize,
        onResizeEnd: () =>
          setError(!writeLayoutPreferences(key, { requestWidth: latestWidth.current })),
      }}
      extra={
        <Button onClick={() => setMaximized((value) => !value)}>
          {maximized ? '还原' : '最大化'}
        </Button>
      }
    >
      {error && <Alert type="info" title="布局偏好未保存" />}
      {children}
    </Drawer>
  )
}
