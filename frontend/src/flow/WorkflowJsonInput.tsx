import { Input, Typography } from 'antd'
import { useState } from 'react'
import { useNodeEditContext } from './editor/node-edit-session'

export default function WorkflowJsonInput({
  fieldKey,
  value,
  editable,
  onChange,
}: {
  fieldKey: string
  value: unknown
  editable: boolean
  onChange: (value: unknown) => void
}) {
  const session = useNodeEditContext()
  const [local, setLocal] = useState(
    () =>
      session?.draft.rawFields[fieldKey] ?? { text: JSON.stringify(value, null, 2), error: null },
  )
  function update(text: string) {
    if (!editable || text === local.text) return
    let error: string | null = null
    let parsed: unknown
    try {
      parsed = JSON.parse(text)
    } catch (caught) {
      error = caught instanceof Error ? caught.message : 'JSON 格式不正确'
    }
    const next = { text, error }
    setLocal(next)
    session?.setRaw(fieldKey, next)
    if (!error) onChange(parsed)
  }
  return (
    <>
      <Input.TextArea
        className="code-input"
        rows={4}
        disabled={!editable}
        value={local.text}
        status={local.error ? 'error' : undefined}
        onChange={(event) => update(event.target.value)}
        onBlur={(event) => update(event.target.value)}
      />
      {local.error && (
        <Typography.Text type="danger" role="alert">
          JSON 格式错误：{local.error}
        </Typography.Text>
      )}
    </>
  )
}
