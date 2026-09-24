import { Alert, Button, Input, InputNumber, Space, Typography } from 'antd'
import { useState } from 'react'
import type { WorkflowNode, WorkflowRegion } from '../lib/api'
import WorkflowJsonInput from './WorkflowJsonInput'

type Props = {
  node: WorkflowNode
  regions: WorkflowRegion[]
  editable: boolean
  onUpdate: (node: WorkflowNode) => void
  onRegionUpdate: (region: WorkflowRegion) => void
}

export default function WorkflowControlFields({
  node,
  regions,
  editable,
  onUpdate,
  onRegionUpdate,
}: Props) {
  const configuration = node.configuration ?? {}
  function updateConfiguration(value: Record<string, unknown>) {
    onUpdate({ ...node, configuration: value })
  }
  return (
    <section className="workflow-config-section" aria-label="控制块配置">
      <Typography.Title level={5}>控制块</Typography.Title>
      {node.capability_id === 'flow.control.repeat' && (
        <label>
          重复次数
          <InputNumber
            min={1}
            max={1000}
            disabled={!editable}
            value={typeof configuration.count === 'number' ? configuration.count : 3}
            onChange={(count) => {
              if (count !== null) updateConfiguration({ ...configuration, count })
            }}
          />
        </label>
      )}
      <Typography.Text strong>配置 JSON</Typography.Text>
      <WorkflowJsonInput
        fieldKey={`control-config-${node.id}`}
        value={configuration}
        editable={editable}
        onChange={(value) => {
          if (value && typeof value === 'object' && !Array.isArray(value))
            updateConfiguration(value as Record<string, unknown>)
        }}
      />
      <Typography.Paragraph type="secondary">
        控制块的来源、条件和策略按版本化配置保存；修改后先应用节点配置。
      </Typography.Paragraph>
      {regions.map((region) => (
        <RegionEditor
          key={`${region.id}:${JSON.stringify(region)}`}
          region={region}
          editable={editable}
          onUpdate={onRegionUpdate}
        />
      ))}
    </section>
  )
}

function RegionEditor({
  region,
  editable,
  onUpdate,
}: {
  region: WorkflowRegion
  editable: boolean
  onUpdate: (region: WorkflowRegion) => void
}) {
  const [text, setText] = useState(() => JSON.stringify(region, null, 2))
  const [dirty, setDirty] = useState(false)
  const [error, setError] = useState<string | null>(null)
  function apply() {
    try {
      const parsed: unknown = JSON.parse(text)
      if (!validRegionDraft(parsed, region)) {
        setError('区域标识与所属节点不能修改；节点、连线和边界必须是数组。')
        return
      }
      onUpdate(parsed)
      setDirty(false)
      setError(null)
    } catch {
      setError('区域 JSON 格式错误。')
    }
  }
  return (
    <div className="workflow-control-region">
      <Typography.Title level={5}>{region.role} 区域</Typography.Title>
      <Typography.Paragraph type="secondary">
        {region.nodes.length} 个步骤。区域节点和连线属于流程定义，单次执行的轮次不会复制画布节点。
      </Typography.Paragraph>
      <Input.TextArea
        aria-label={`${region.role} 区域定义`}
        className="code-input"
        rows={8}
        disabled={!editable}
        value={text}
        status={error ? 'error' : undefined}
        onChange={(event) => {
          setText(event.target.value)
          setDirty(true)
          setError(null)
        }}
      />
      <Space>
        <Button disabled={!editable || !dirty} onClick={apply}>
          应用区域
        </Button>
        <Button
          disabled={!editable || !dirty}
          onClick={() => {
            setText(JSON.stringify(region, null, 2))
            setDirty(false)
            setError(null)
          }}
        >
          丢弃
        </Button>
      </Space>
      {error && <Alert type="error" title={error} />}
    </div>
  )
}

function validRegionDraft(value: unknown, original: WorkflowRegion): value is WorkflowRegion {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const draft = value as Record<string, unknown>
  return (
    draft.id === original.id &&
    draft.owner_node_id === original.owner_node_id &&
    draft.role === original.role &&
    Array.isArray(draft.nodes) &&
    Array.isArray(draft.edges) &&
    Array.isArray(draft.exit_node_ids)
  )
}
