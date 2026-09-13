import { MinusCircleOutlined } from '@ant-design/icons'
import { Button, Input, Select } from 'antd'
import type { WorkflowFieldMapping } from '../lib/api'

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
      <Input
        aria-label="映射源表达式"
        disabled={!editable}
        placeholder="源 JMESPath"
        value={mapping.source.path}
        onChange={(event) =>
          onUpdate({ ...mapping, source: { ...mapping.source, path: event.target.value } })
        }
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
      <Input
        aria-label="映射目标字段"
        disabled={!editable}
        placeholder="目标字段"
        value={mapping.target.key}
        onChange={(event) =>
          onUpdate({ ...mapping, target: { ...mapping.target, key: event.target.value } })
        }
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
