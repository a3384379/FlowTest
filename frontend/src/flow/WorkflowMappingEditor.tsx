import { MinusCircleOutlined } from '@ant-design/icons'
import { Button, Input, Select } from 'antd'
import type { WorkflowFieldMapping } from '../lib/api'
import { useRef, useState } from 'react'

export default function MappingEditor({
  mapping,
  editable,
  onUpdate,
  onDelete,
}: {
  mapping: WorkflowFieldMapping
  editable: boolean
  onUpdate: (mapping: WorkflowFieldMapping) => void
  onDelete: () => void
}) {
  return (
    <div className="mapping-editor">
      <MappingTextInput
        aria-label="映射源表达式"
        disabled={!editable}
        placeholder="源 JMESPath"
        value={mapping.source.path}
        onCommit={(path) => onUpdate({ ...mapping, source: { ...mapping.source, path } })}
      />
      <Select
        aria-label="映射目标位置"
        disabled={!editable}
        value={mapping.target.location}
        options={[
          { value: 'query', label: 'Query' },
          { value: 'header', label: 'Header' },
          { value: 'body', label: 'Body' },
          { value: 'variable', label: 'Variable' },
        ]}
        onChange={(value) =>
          onUpdate({ ...mapping, target: { ...mapping.target, location: value } })
        }
      />
      <MappingTextInput
        aria-label="映射目标字段"
        disabled={!editable}
        placeholder="目标字段"
        value={mapping.target.key}
        onCommit={(key) => onUpdate({ ...mapping, target: { ...mapping.target, key } })}
      />
      <Button
        danger
        type="text"
        aria-label="删除映射"
        icon={<MinusCircleOutlined />}
        disabled={!editable}
        onClick={onDelete}
      />
    </div>
  )
}

// One focus session is one graph transaction. Leaving a field (including a row
// switch or structural action) commits; Enter commits; Escape cancels.
function MappingTextInput({
  value,
  onCommit,
  ...props
}: {
  value: string
  onCommit: (value: string) => void
  disabled: boolean
  placeholder: string
  'aria-label': string
}) {
  const [text, setText] = useState<string | null>(null)
  const pending = useRef<string | null>(null)
  function finish(commit: boolean) {
    const next = pending.current
    pending.current = null
    setText(null)
    if (commit && !props.disabled && next !== null && next !== value) onCommit(next)
  }
  return (
    <Input
      {...props}
      value={text ?? value}
      onFocus={() => {
        pending.current = value
        setText(value)
      }}
      onChange={(event) => {
        pending.current = event.target.value
        setText(event.target.value)
      }}
      onBlur={() => finish(true)}
      onKeyDown={(event) => {
        if (event.nativeEvent.isComposing) return
        if (event.key !== 'Enter' && event.key !== 'Escape') return
        event.preventDefault()
        event.stopPropagation()
        finish(event.key === 'Enter')
        event.currentTarget.blur()
      }}
    />
  )
}
