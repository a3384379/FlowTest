import { CopyOutlined } from '@ant-design/icons'
import { Button, Typography } from 'antd'
import { useState } from 'react'

export default function SelfTestIdentityValue({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState<{ value: string; message: string } | null>(null)
  const abbreviated = value.length > 32
  async function copy() {
    try {
      await navigator.clipboard.writeText(value)
      setCopied({ value, message: '已复制完整值' })
    } catch {
      setCopied({ value, message: '复制失败，可展开完整值后手动复制' })
    }
  }
  return (
    <div className="self-test-identity-value">
      <div className="self-test-identity-preview">
        <Typography.Text title={value}>
          {abbreviated ? `${value.slice(0, 12)}…${value.slice(-12)}` : value}
        </Typography.Text>
        <Button
          size="small"
          type="text"
          icon={<CopyOutlined />}
          aria-label={`复制完整${label}`}
          onClick={() => void copy()}
        />
      </div>
      {abbreviated && (
        <details className="self-test-identity-full">
          <summary>显示完整值</summary>
          <Typography.Text>{value}</Typography.Text>
        </details>
      )}
      {copied?.value === value && (
        <Typography.Text role="status" type="secondary">
          {copied.message}
        </Typography.Text>
      )}
    </div>
  )
}
