import { DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import { Alert, Button, Input, Space, Typography } from 'antd'
import { useState } from 'react'

import { mapValue, parseEnvironmentMap, type EnvironmentMapValue } from './environment-map'

type Props = {
  value?: EnvironmentMapValue
  onChange?: (value: EnvironmentMapValue) => void
  kind: 'variables' | 'headers'
  readOnly: boolean
  id?: string
}
export default function EnvironmentMapEditor({
  value = mapValue({}),
  onChange,
  kind,
  readOnly,
  id,
}: Props) {
  const [error, setError] = useState('')
  const label = kind === 'variables' ? '变量' : '请求头'
  function changeFormat() {
    try {
      const parsed = parseEnvironmentMap(value, kind)
      onChange?.(
        value.format === 'table'
          ? { format: 'json', text: JSON.stringify(parsed, null, 2) }
          : mapValue(parsed),
      )
      setError('')
    } catch (cause) {
      setError((cause as Error).message)
    }
  }
  return (
    <div id={id}>
      <Space className="environment-map-heading">
        <Typography.Text type="secondary">{label}名称和值</Typography.Text>
        <Button size="small" disabled={false} onClick={changeFormat}>
          {value.format === 'table' ? `${label}高级 JSON` : `${label}返回表格`}
        </Button>
      </Space>
      {error && <Alert type="error" title={error} />}
      {value.format === 'json' ? (
        <Input.TextArea
          aria-label={`${label} JSON`}
          value={value.text}
          readOnly={readOnly}
          autoSize={{ minRows: 5, maxRows: 12 }}
          onChange={(event) => {
            setError('')
            onChange?.({ format: 'json', text: event.target.value })
          }}
        />
      ) : (
        <div className="environment-map-table">
          {value.rows.map((row, index) => (
            <div className="environment-map-row" key={index}>
              <Input
                aria-label={`${label}名称 ${index + 1}`}
                placeholder="名称"
                value={row.name}
                readOnly={readOnly}
                onChange={(event) =>
                  onChange?.({
                    format: 'table',
                    rows: value.rows.map((item, itemIndex) =>
                      itemIndex === index ? { ...item, name: event.target.value } : item,
                    ),
                  })
                }
              />
              <Input
                aria-label={`${label}值 ${index + 1}`}
                placeholder="值"
                value={row.value}
                readOnly={readOnly}
                onChange={(event) =>
                  onChange?.({
                    format: 'table',
                    rows: value.rows.map((item, itemIndex) =>
                      itemIndex === index ? { ...item, value: event.target.value } : item,
                    ),
                  })
                }
              />
              {!readOnly && (
                <Button
                  icon={<DeleteOutlined />}
                  aria-label={`删除${label} ${index + 1}`}
                  onClick={() =>
                    onChange?.({
                      format: 'table',
                      rows: value.rows.filter((_, itemIndex) => itemIndex !== index),
                    })
                  }
                />
              )}
            </div>
          ))}
          {!readOnly && (
            <Button
              size="small"
              icon={<PlusOutlined />}
              onClick={() =>
                onChange?.({ format: 'table', rows: [...value.rows, { name: '', value: '' }] })
              }
            >
              添加{label}
            </Button>
          )}
        </div>
      )}
    </div>
  )
}
