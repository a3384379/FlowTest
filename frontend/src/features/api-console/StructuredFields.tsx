import { DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import { Alert, Button, Input, Space, Typography } from 'antd'

export type DynamicField = { key: number; name: number }

export function DynamicFields({
  fields,
  onAdd,
  onRemove,
  onBulkEdit,
  bulkEditLabel = '批量编辑',
  render,
}: {
  fields: DynamicField[]
  onAdd: () => void
  onRemove: (index: number) => void
  onBulkEdit?: () => void
  bulkEditLabel?: string
  render: (field: DynamicField) => React.ReactNode
}) {
  return (
    <Space orientation="vertical" className="full-width">
      {fields.map((field) => (
        <div className="workbench-dynamic-row" key={field.key}>
          {render(field)}
          <Button
            type="text"
            danger
            icon={<DeleteOutlined />}
            aria-label="删除配置行"
            onClick={() => onRemove(field.name)}
          />
        </div>
      ))}
      <Space wrap>
        <Button type="dashed" icon={<PlusOutlined />} onClick={onAdd}>
          添加一行
        </Button>
        {onBulkEdit && <Button onClick={onBulkEdit}>{bulkEditLabel}</Button>}
      </Space>
    </Space>
  )
}

export function BulkEditor({
  label,
  text,
  errors,
  help,
  onChange,
  onApply,
  onCancel,
}: {
  label: string
  text: string
  errors: string[]
  help: string
  onChange: (value: string) => void
  onApply: () => void
  onCancel: () => void
}) {
  return (
    <Space orientation="vertical" className="full-width" size="middle">
      <Typography.Text type="secondary">{help}</Typography.Text>
      {errors.length > 0 && (
        <Alert
          type="error"
          showIcon
          title="批量内容存在问题"
          description={errors.map((error) => (
            <div key={error}>{error}</div>
          ))}
        />
      )}
      <Input.TextArea
        autoFocus
        aria-label={`批量编辑 ${label}`}
        className="code-input"
        autoSize={{ minRows: 10, maxRows: 18 }}
        value={text}
        onChange={(event) => onChange(event.target.value)}
      />
      <Space>
        <Button type="primary" onClick={onApply}>
          应用并返回表格
        </Button>
        <Button onClick={onCancel}>取消</Button>
      </Space>
    </Space>
  )
}
