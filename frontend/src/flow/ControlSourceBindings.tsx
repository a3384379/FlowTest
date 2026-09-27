import { Button, Input, Space, Typography } from 'antd'
import { useState } from 'react'

import ControlSourcePicker from './ControlSourcePicker'
import {
  parseValueSource,
  type SourceChoice,
  type ValueSource,
} from './editor/control-source-browser'

type Props = {
  label: string
  values: Record<string, unknown>
  choices: SourceChoice[]
  editable: boolean
  blockedNames?: string[]
  onChange: (values: Record<string, unknown>) => void
}

const validName = /^[A-Za-z_][A-Za-z0-9_.-]*$/

export default function ControlSourceBindings({
  label,
  values,
  choices,
  editable,
  blockedNames = [],
  onChange,
}: Props) {
  const [name, setName] = useState('')
  const trimmed = name.trim()
  const canAdd =
    editable &&
    validName.test(trimmed) &&
    trimmed.length <= 160 &&
    Object.keys(values).length < 100 &&
    !(trimmed in values) &&
    !blockedNames.includes(trimmed)
  return (
    <div aria-label={label}>
      <Typography.Text strong>{label}</Typography.Text>
      {Object.entries(values).map(([key, value]) => {
        const source = parseValueSource(value)
        return (
          <div key={key}>
            <Space>
              <Typography.Text>{key}</Typography.Text>
              {source ? (
                <ControlSourcePicker
                  label={`${label} ${key} 来源浏览器`}
                  source={source}
                  choices={choices}
                  editable={editable}
                  onChange={(next: ValueSource) => onChange({ ...values, [key]: next })}
                />
              ) : (
                <Typography.Text type="danger">来源需在高级 JSON 中修正</Typography.Text>
              )}
              <Button
                disabled={!editable}
                onClick={() => {
                  const next = { ...values }
                  delete next[key]
                  onChange(next)
                }}
              >
                删除{label} {key}
              </Button>
            </Space>
          </div>
        )
      })}
      <Space>
        <Input
          aria-label={`新增${label}名称`}
          placeholder="输入名称"
          maxLength={160}
          disabled={!editable}
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
        <Button
          disabled={!canAdd}
          onClick={() => {
            onChange({ ...values, [trimmed]: { kind: 'literal', value: null } })
            setName('')
          }}
        >
          添加{label}
        </Button>
      </Space>
      {name && !canAdd && editable && (
        <Typography.Text type="secondary">名称需合法、未重复，且每组最多 100 项。</Typography.Text>
      )}
    </div>
  )
}
