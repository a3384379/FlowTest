import { Alert, Button, Input, Space, Typography } from 'antd'
import { useEffect, useState } from 'react'
import { useNodeEditContext } from './editor/node-edit-session'

export default function ControlConfigurationJson({
  nodeId,
  value,
  editable,
  onChange,
  onDirtyChange,
}: {
  nodeId: string
  value: Record<string, unknown>
  editable: boolean
  onChange: (value: Record<string, unknown>) => void
  onDirtyChange: (dirty: boolean) => void
}) {
  const currentText = JSON.stringify(value, null, 2)
  const fieldKey = `control-config-${nodeId}`
  const session = useNodeEditContext()
  const saved = session?.draft.rawFields[fieldKey]
  const [initial] = useState(() => initialDraft(saved, value, currentText))
  const [text, setText] = useState(initial.text)
  const [baseText, setBaseText] = useState(initial.baseText)
  const [dirty, setDirty] = useState(initial.dirty)
  const [error, setError] = useState<string | null>(initial.error)
  const actionsDisabled = !editable || !dirty

  useEffect(() => onDirtyChange(dirty), [dirty, onDirtyChange])

  function edit(next: string) {
    if (!draftDiffers(next, value)) {
      discard()
      return
    }
    if (!dirty) setBaseText(currentText)
    setText(next)
    setDirty(true)
    setError(null)
    session?.setRaw(fieldKey, { text: next, error: null, baseText: dirty ? baseText : currentText })
  }

  function apply() {
    const result = validateConfigurationDraft(text, baseText, currentText)
    if (result.value === undefined) {
      setError(result.error)
      return
    }
    onChange(result.value)
    setDirty(false)
    setError(null)
    session?.clearRaw(fieldKey)
  }

  function discard() {
    setText(currentText)
    setBaseText(currentText)
    setDirty(false)
    setError(null)
    session?.clearRaw(fieldKey)
  }

  return (
    <>
      <Typography.Text strong>配置 JSON</Typography.Text>
      <DraftInput
        editable={editable}
        dirty={dirty}
        text={text}
        currentText={currentText}
        error={error}
        onChange={edit}
      />
      <Space>
        <Button disabled={actionsDisabled} onClick={apply}>
          应用配置
        </Button>
        <Button disabled={actionsDisabled} onClick={discard}>
          丢弃配置草稿
        </Button>
      </Space>
      {error && <Alert type="error" title={error} />}
    </>
  )
}

function initialDraft(
  saved: { text: string; error: string | null; baseText?: string } | undefined,
  value: Record<string, unknown>,
  currentText: string,
) {
  const dirty = saved ? draftDiffers(saved.text, value) : false
  return {
    text: saved?.text ?? currentText,
    baseText: dirty ? (saved?.baseText ?? '') : currentText,
    dirty,
    error: saved?.error ?? null,
  }
}

function DraftInput({
  editable,
  dirty,
  text,
  currentText,
  error,
  onChange,
}: {
  editable: boolean
  dirty: boolean
  text: string
  currentText: string
  error: string | null
  onChange: (text: string) => void
}) {
  return (
    <Input.TextArea
      aria-label="控制块配置 JSON"
      className="code-input"
      rows={4}
      disabled={!editable}
      value={dirty ? text : currentText}
      status={error ? 'error' : undefined}
      onChange={(event) => onChange(event.target.value)}
    />
  )
}

function validateConfigurationDraft(
  text: string,
  baseText: string,
  currentText: string,
): { value: Record<string, unknown>; error?: never } | { value?: never; error: string } {
  if (baseText !== currentText) {
    return { error: '配置已从其他编辑更新。请先复制草稿，再丢弃并重新编辑。' }
  }
  const parsed = parseConfiguration(text)
  if (parsed === null) return { error: '控制块配置必须是有效的 JSON 对象。' }
  return { value: parsed }
}

function parseConfiguration(text: string): Record<string, unknown> | null {
  try {
    const parsed: unknown = JSON.parse(text)
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : null
  } catch {
    return null
  }
}

function draftDiffers(text: string, value: Record<string, unknown>): boolean {
  const parsed = parseConfiguration(text)
  return parsed === null || JSON.stringify(parsed) !== JSON.stringify(value)
}
