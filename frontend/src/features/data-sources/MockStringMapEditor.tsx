import { Button, Input, Space, Typography } from 'antd'
import { useState } from 'react'

import { readStringMap, stringMapDraft, type StringMapDraft } from './mock-form-values'

export default function MockStringMapEditor({
  value = stringMapDraft(),
  onChange,
  disabled,
  label,
  id,
  header = false,
}: {
  value?: StringMapDraft
  onChange?: (value: StringMapDraft) => void
  disabled?: boolean
  label: string
  id?: string
  header?: boolean
}) {
  const [error, setError] = useState('')
  function changeMode() {
    try {
      const parsed = readStringMap(value, header)
      const next = stringMapDraft(parsed)
      onChange?.({ ...next, mode: value.mode === 'json' ? 'rows' : 'json' })
      setError('')
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '配置无效')
    }
  }
  function changeRow(index: number, field: 'name' | 'value', text: string) {
    onChange?.({
      ...value,
      rows: value.rows.map((row, rowIndex) =>
        rowIndex === index ? { ...row, [field]: text } : row,
      ),
    })
  }
  return (
    <Space orientation="vertical" className="full-width">
      <Button size="small" disabled={disabled} onClick={changeMode}>
        {value.mode === 'rows' ? `${label}：高级 JSON` : `${label}：返回键值行`}
      </Button>
      {value.mode === 'json' ? (
        <Input.TextArea
          id={id}
          aria-label={`${label} JSON`}
          disabled={disabled}
          rows={3}
          value={value.json}
          onChange={(event) => onChange?.({ ...value, json: event.target.value })}
        />
      ) : (
        <>
          {value.rows.map((row, index) => (
            <Space.Compact key={index} className="full-width">
              <Input
                aria-label={`${label} 键 ${index + 1}`}
                placeholder="键名"
                value={row.name}
                disabled={disabled}
                onChange={(event) => changeRow(index, 'name', event.target.value)}
              />
              <Input
                aria-label={`${label} 值 ${index + 1}`}
                placeholder="字符串值（允许为空）"
                value={row.value}
                disabled={disabled}
                onChange={(event) => changeRow(index, 'value', event.target.value)}
              />
              <Button
                disabled={disabled}
                aria-label={`${label} 删除行 ${index + 1}`}
                onClick={() =>
                  onChange?.({
                    ...value,
                    rows: value.rows.filter((_, rowIndex) => rowIndex !== index),
                  })
                }
              >
                删除
              </Button>
            </Space.Compact>
          ))}
          <Button
            disabled={disabled}
            onClick={() => onChange?.({ ...value, rows: [...value.rows, { name: '', value: '' }] })}
          >
            {label}：添加一行
          </Button>
        </>
      )}
      {error && <Typography.Text type="danger">{error}</Typography.Text>}
    </Space>
  )
}
