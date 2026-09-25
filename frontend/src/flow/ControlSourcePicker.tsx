import { Select } from 'antd'

import type { SourceChoice, ValueSource } from './editor/control-source-browser'

export default function ControlSourcePicker({
  label,
  source,
  choices,
  editable,
  onChange,
}: {
  label: string
  source: ValueSource
  choices: SourceChoice[]
  editable: boolean
  onChange: (source: ValueSource) => void
}) {
  if (!choices.length) return null
  return (
    <Select
      aria-label={label}
      placeholder="浏览可用字段"
      disabled={!editable}
      value={
        choices.find((choice) => JSON.stringify(choice.source) === JSON.stringify(source))?.key
      }
      options={choices.map((choice) => ({
        value: choice.key,
        label: choice.reason ? `${choice.label}（${choice.reason}）` : choice.label,
        disabled: choice.source === null,
      }))}
      onChange={(key: string) => {
        const selected = choices.find((choice) => choice.key === key)
        if (selected?.source) onChange(selected.source)
      }}
    />
  )
}
