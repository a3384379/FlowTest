import { BulbOutlined } from '@ant-design/icons'
import { Button, Popover, Space, Switch, Typography } from 'antd'
import { useEffect, useState } from 'react'

export default function AppearanceSettings({ userId }: { userId: string }) {
  const key = `flowtest:appearance:v5:${encodeURIComponent(userId)}`
  const [reduceTransparency, setReduceTransparency] = useState(() => readPreference(key))
  useEffect(() => {
    document.documentElement.dataset.reduceTransparency = String(reduceTransparency)
    return () => {
      delete document.documentElement.dataset.reduceTransparency
    }
  }, [reduceTransparency])
  function update(value: boolean): void {
    setReduceTransparency(value)
    try {
      localStorage.setItem(key, JSON.stringify({ reduceTransparency: value }))
    } catch {
      /* The current view remains usable without preference storage. */
    }
  }
  return (
    <Popover
      trigger="click"
      title="外观"
      content={
        <Space orientation="vertical">
          <Typography.Text>冰蓝白 · 浅色工作台</Typography.Text>
          <Space>
            <Switch aria-label="减少透明效果" checked={reduceTransparency} onChange={update} />
            <span>减少透明效果</span>
          </Space>
          <Typography.Text type="secondary">动效跟随系统的减少动态效果设置。</Typography.Text>
        </Space>
      }
    >
      <Button type="text" icon={<BulbOutlined />} aria-label="外观设置" />
    </Popover>
  )
}

function readPreference(key: string): boolean {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(key) ?? 'null')
    return Boolean(
      value &&
      typeof value === 'object' &&
      'reduceTransparency' in value &&
      value.reduceTransparency === true,
    )
  } catch {
    return false
  }
}
