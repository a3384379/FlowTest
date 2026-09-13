import { DownOutlined, UpOutlined } from '@ant-design/icons'
import { Button, Space, Tag, Typography } from 'antd'
import { useState, type ReactNode } from 'react'

type RuntimeDockMode = 'run' | 'history' | 'debug'

const modeLabels: Record<RuntimeDockMode, string> = {
  run: '运行视图',
  history: '历史快照',
  debug: '调试结果',
}

export default function WorkflowRuntimeDock({
  mode,
  status,
  children,
}: {
  mode: RuntimeDockMode
  status?: ReactNode
  children: ReactNode
}) {
  const [collapsed, setCollapsed] = useState(false)
  return (
    <section
      className={`workflow-runtime-dock${collapsed ? ' is-collapsed' : ''}`}
      data-testid="workflow-runtime-dock"
      aria-label="运行与历史"
    >
      <header className="workflow-runtime-dock-header">
        <Space size={8}>
          <Typography.Text strong>运行与历史</Typography.Text>
          <Tag variant="filled">{modeLabels[mode]}</Tag>
          {status}
        </Space>
        <Button
          type="text"
          size="small"
          icon={collapsed ? <UpOutlined /> : <DownOutlined />}
          aria-label={collapsed ? '展开运行面板' : '折叠运行面板'}
          aria-expanded={!collapsed}
          onClick={() => setCollapsed((value) => !value)}
        />
      </header>
      {!collapsed && <div className="workflow-runtime-dock-body">{children}</div>}
    </section>
  )
}
