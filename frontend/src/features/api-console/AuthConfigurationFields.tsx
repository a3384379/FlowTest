import { Form, Input, Select, Space, Typography } from 'antd'
import type { ApiVersion } from '../../lib/api'
import type { BulkRedactionMode, KeyValueField } from './bulk-edit'
import { authConfigurationFields, authFieldValue } from './auth-configuration'

export default function AuthConfigurationFields({
  kind,
  redactionMode,
  value = [],
  onChange,
}: {
  kind: ApiVersion['auth_kind']
  redactionMode: BulkRedactionMode
  value?: KeyValueField[]
  onChange?: (value: KeyValueField[]) => void
}) {
  const known = authConfigurationFields[kind]
  const advanced = value.filter((item) => !known.some((field) => field.name === item.name))
  function update(name: string, next: string) {
    const index = value.findIndex((item) => item.name === name)
    onChange?.(
      index < 0
        ? [...value, { name, value: next }]
        : value.map((item, position) => (position === index ? { ...item, value: next } : item)),
    )
  }
  return (
    <Space orientation="vertical" className="full-width">
      {kind === 'none' && <Typography.Text type="secondary">此请求不生成认证头。</Typography.Text>}
      {known.map((field) => (
        <Form.Item label={field.label} key={field.name}>
          {field.name === 'in' ? (
            <Select
              aria-label={field.label}
              value={authFieldValue(value, field)}
              options={[
                { value: 'header', label: '请求头 Header' },
                { value: 'query', label: '查询参数 Query' },
                { value: 'cookie', label: 'Cookie' },
              ]}
              onChange={(next: string) => update(field.name, next)}
            />
          ) : (
            <Input
              aria-label={field.label}
              type={redactionMode === 'on' ? 'password' : 'text'}
              value={authFieldValue(value, field)}
              placeholder="值或 {{secret.NAME}}"
              onChange={(event) => update(field.name, event.target.value)}
            />
          )}
        </Form.Item>
      ))}
      <Typography.Text type="secondary">
        认证仅用于当前请求；可引用项目只写 Secret，不会读取或回填 Secret 的实际值。
      </Typography.Text>
      <details>
        <summary>高级：其他认证配置（{advanced.length} 项）</summary>
        {advanced.map((item) => (
          <Form.Item label={item.name} key={item.name}>
            <Input
              aria-label={`其他认证配置 ${item.name}`}
              value={item.value}
              type={redactionMode === 'on' ? 'password' : 'text'}
              onChange={(event) => update(item.name, event.target.value)}
            />
          </Form.Item>
        ))}
      </details>
    </Space>
  )
}
