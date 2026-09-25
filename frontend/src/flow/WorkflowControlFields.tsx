import { Alert, Button, Input, InputNumber, Select, Space, Typography } from 'antd'
import { useState } from 'react'
import type { ApiDefinition, WorkflowDefinition, WorkflowNode, WorkflowRegion } from '../lib/api'
import ConditionLoopStateFields from './ConditionLoopStateFields'
import ControlConditionFields from './ControlConditionFields'
import ControlConfigurationJson from './ControlConfigurationJson'
import ControlSourcePicker from './ControlSourcePicker'
import {
  appendRegionApi,
  appendRegionDelay,
  appendRegionSignal,
  canAppendRegionSignal,
} from './editor/control-blocks'
import {
  conditionStateSources,
  parseValueSource,
  type SourceChoice,
  type ValueSource,
} from './editor/control-source-browser'
import { switchToRules, switchToValue } from './editor/control-switch'
import WorkflowRegionCanvasModal from './WorkflowRegionCanvasModal'

type Props = {
  node: WorkflowNode
  definition?: WorkflowDefinition
  regions: WorkflowRegion[]
  editable: boolean
  apis?: ApiDefinition[]
  onUpdate: (node: WorkflowNode) => void
  onRegionUpdate: (region: WorkflowRegion) => void
}

export default function WorkflowControlFields({
  node,
  definition,
  regions,
  editable,
  apis = [],
  onUpdate,
  onRegionUpdate,
}: Props) {
  const configuration = node.configuration ?? {}
  const [configDirty, setConfigDirty] = useState(false)
  const configFieldsEditable = editable && !configDirty
  function updateConfiguration(value: Record<string, unknown>) {
    onUpdate({ ...node, configuration: value })
  }
  return (
    <section className="workflow-config-section" aria-label="控制块配置">
      <Typography.Title level={5}>控制块</Typography.Title>
      {node.capability_id === 'flow.control.return' && (
        <Alert
          type="warning"
          showIcon
          title="返回仅在当前工作流被子流程调用时有效；直接运行会以 RETURN_OUTSIDE_CALL 失败。"
        />
      )}
      <RepeatCountFields
        node={node}
        configuration={configuration}
        editable={configFieldsEditable}
        onChange={updateConfiguration}
      />
      {definition && (
        <ControlSourceShortcuts
          node={node}
          configuration={configuration}
          choices={conditionStateSources(
            definition,
            node,
            node.capability_id === 'flow.control.foreach' ? 'initial' : 'condition',
          )}
          editable={configFieldsEditable}
          onChange={updateConfiguration}
        />
      )}
      <ControlConfigurationJson
        nodeId={node.id}
        value={configuration}
        editable={editable}
        onChange={updateConfiguration}
        onDirtyChange={setConfigDirty}
      />
      <Typography.Paragraph type="secondary">
        控制块的来源、条件和策略按版本化配置保存；修改后先应用节点配置。
      </Typography.Paragraph>
      {configDirty && (
        <Typography.Text type="secondary">
          先修正或丢弃配置 JSON 草稿，再使用可视化状态编辑。
        </Typography.Text>
      )}
      <ControlConditionSections
        node={node}
        definition={definition}
        configuration={configuration}
        editable={configFieldsEditable}
        onChange={updateConfiguration}
      />
      {['flow.control.while', 'flow.control.do_while', 'flow.control.until'].includes(
        node.capability_id ?? '',
      ) && (
        <ConditionLoopStateFields
          definition={definition}
          node={node}
          configuration={configuration}
          editable={configFieldsEditable}
          onChange={updateConfiguration}
        />
      )}
      {regions.map((region) => (
        <RegionEditor
          key={region.id}
          region={region}
          owner={node}
          editable={editable}
          apis={apis}
          onUpdate={onRegionUpdate}
        />
      ))}
    </section>
  )
}

function RepeatCountFields({
  node,
  configuration,
  editable,
  onChange,
}: {
  node: WorkflowNode
  configuration: Record<string, unknown>
  editable: boolean
  onChange: (configuration: Record<string, unknown>) => void
}) {
  if (node.capability_id !== 'flow.control.repeat') return null
  return (
    <label>
      重复次数
      <InputNumber
        min={1}
        max={1000}
        disabled={!editable}
        value={typeof configuration.count === 'number' ? configuration.count : 3}
        onChange={(count) => {
          if (count !== null) onChange({ ...configuration, count })
        }}
      />
    </label>
  )
}

function ControlSourceShortcuts({
  node,
  configuration,
  choices,
  editable,
  onChange,
}: {
  node: WorkflowNode
  configuration: Record<string, unknown>
  choices: SourceChoice[]
  editable: boolean
  onChange: (configuration: Record<string, unknown>) => void
}) {
  if (node.capability_id === 'flow.control.foreach') {
    return (
      <SourceShortcut
        label="遍历集合来源"
        value={configuration.collection}
        choices={choices}
        editable={editable}
        onChange={(collection) => onChange({ ...configuration, collection })}
      />
    )
  }
  if (node.capability_id === 'flow.control.switch' && configuration.mode === 'value') {
    return (
      <SourceShortcut
        label="多分支判断来源"
        value={configuration.value}
        choices={choices}
        editable={editable}
        onChange={(value) => onChange({ ...configuration, value })}
      />
    )
  }
  return null
}

function ControlConditionSections({
  node,
  definition,
  configuration,
  editable,
  onChange,
}: {
  node: WorkflowNode
  definition?: WorkflowDefinition
  configuration: Record<string, unknown>
  editable: boolean
  onChange: (configuration: Record<string, unknown>) => void
}) {
  const conditionLoop = [
    'flow.control.while',
    'flow.control.do_while',
    'flow.control.until',
  ].includes(node.capability_id ?? '')
  const choices = definition ? conditionStateSources(definition, node, 'condition') : []
  if (node.capability_id === 'flow.control.if' || conditionLoop) {
    return (
      <ControlConditionFields
        label={conditionLoop ? '循环条件' : '判断条件'}
        value={configuration.condition}
        choices={choices}
        editable={editable}
        onChange={(condition) => onChange({ ...configuration, condition })}
      />
    )
  }
  if (node.capability_id !== 'flow.control.switch') return null
  return (
    <SwitchBranchFields
      configuration={configuration}
      choices={choices}
      editable={editable}
      onChange={onChange}
    />
  )
}

function SwitchBranchFields({
  configuration,
  choices,
  editable,
  onChange,
}: {
  configuration: Record<string, unknown>
  choices: SourceChoice[]
  editable: boolean
  onChange: (configuration: Record<string, unknown>) => void
}) {
  if (!Array.isArray(configuration.branches)) return null
  const valueMode = switchToValue(configuration)
  return (
    <Space direction="vertical">
      <Select
        aria-label="多分支模式"
        disabled={!editable}
        value={configuration.mode === 'rules' ? 'rules' : 'value'}
        options={[
          {
            label: '按值匹配',
            value: 'value',
            disabled: configuration.mode === 'rules' && !valueMode,
          },
          { label: '按条件匹配', value: 'rules' },
        ]}
        onChange={(mode: 'value' | 'rules') => {
          const next = mode === 'rules' ? switchToRules(configuration) : valueMode
          if (next) onChange(next)
        }}
      />
      {configuration.mode === 'rules' && !valueMode && (
        <Typography.Text type="secondary">
          当前条件不能无损转换为按值匹配；可在高级配置中编辑模式。
        </Typography.Text>
      )}
      {configuration.branches.map((raw, index) => {
        const branch = asRecord(raw)
        if (!branch) return null
        const label = `分支 ${String(branch.label ?? branch.id ?? index + 1)}`
        const update = (patch: Record<string, unknown>) =>
          onChange({
            ...configuration,
            branches: (configuration.branches as unknown[]).map((item, position) =>
              position === index ? { ...branch, ...patch } : item,
            ),
          })
        return configuration.mode === 'rules' ? (
          <ControlConditionFields
            key={String(branch.id ?? index)}
            label={`${label} 条件`}
            value={branch.condition}
            choices={choices}
            editable={editable}
            onChange={(condition) => update({ condition })}
          />
        ) : (
          <SourceShortcut
            key={String(branch.id ?? index)}
            label={`${label} 匹配来源`}
            value={branch.match}
            choices={choices}
            editable={editable}
            onChange={(match) => update({ match })}
          />
        )
      })}
    </Space>
  )
}

function SourceShortcut({
  label,
  value,
  choices,
  editable,
  onChange,
}: {
  label: string
  value: unknown
  choices: SourceChoice[]
  editable: boolean
  onChange: (source: ValueSource) => void
}) {
  const source = parseValueSource(value)
  if (!source) return null
  return (
    <div>
      <Typography.Text>{label}</Typography.Text>
      <ControlSourcePicker
        label={label}
        source={source}
        choices={choices}
        editable={editable}
        onChange={onChange}
      />
    </div>
  )
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null
}

function RegionEditor({
  region,
  owner,
  editable,
  apis,
  onUpdate,
}: {
  region: WorkflowRegion
  owner: WorkflowNode
  editable: boolean
  apis: ApiDefinition[]
  onUpdate: (region: WorkflowRegion) => void
}) {
  const currentText = JSON.stringify(region, null, 2)
  const [text, setText] = useState(currentText)
  const [baseText, setBaseText] = useState(currentText)
  const [dirty, setDirty] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [canvasOpen, setCanvasOpen] = useState(false)
  function apply() {
    if (baseText !== currentText) {
      setError('区域已从其他编辑更新。请先复制草稿，再丢弃并重新编辑。')
      return
    }
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
      <Button onClick={() => setCanvasOpen(true)}>打开区域画布</Button>
      <WorkflowRegionCanvasModal
        open={canvasOpen}
        region={region}
        apis={apis}
        editable={editable && !dirty}
        onClose={() => setCanvasOpen(false)}
        onUpdate={onUpdate}
      />
      <RegionStepList
        region={region}
        owner={owner}
        editable={editable && !dirty}
        apis={apis}
        onUpdate={onUpdate}
      />
      {dirty && (
        <Typography.Text type="secondary">先应用或丢弃区域 JSON 草稿，再编辑步骤。</Typography.Text>
      )}
      <Typography.Text strong>高级：区域定义 JSON</Typography.Text>
      <Input.TextArea
        aria-label={`${region.role} 区域定义`}
        className="code-input"
        rows={8}
        disabled={!editable}
        value={dirty ? text : currentText}
        status={error ? 'error' : undefined}
        onChange={(event) => {
          if (!dirty) setBaseText(currentText)
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
            setText(currentText)
            setBaseText(currentText)
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

function RegionStepList({
  region,
  owner,
  editable,
  apis,
  onUpdate,
}: {
  region: WorkflowRegion
  owner: WorkflowNode
  editable: boolean
  apis: ApiDefinition[]
  onUpdate: (region: WorkflowRegion) => void
}) {
  const availableApis = apis.filter((api) => api.is_active)
  const [selectedApiId, setSelectedApiId] = useState<string | undefined>()
  const activeApiId = selectedApiId ?? availableApis[0]?.id
  const canAppend = region.nodes.length === 0 || region.exit_node_ids.length === 1
  return (
    <div aria-label={`${region.role} 区域步骤`}>
      {region.nodes.map((node) => (
        <div className="workflow-control-region-step" key={node.id}>
          <Typography.Text>
            {node.name} · {node.type}
          </Typography.Text>
          {node.type === 'delay' && (
            <InputNumber
              aria-label={`${node.name} 等待秒数`}
              min={0}
              max={300}
              step={0.1}
              disabled={!editable}
              value={typeof node.config.seconds === 'number' ? node.config.seconds : 0}
              onChange={(seconds) => {
                if (seconds === null) return
                onUpdate({
                  ...region,
                  nodes: region.nodes.map((item) =>
                    item.id === node.id ? { ...item, config: { ...item.config, seconds } } : item,
                  ),
                })
              }}
            />
          )}
          {node.type === 'api' && (
            <RegionApiFields
              node={node}
              region={region}
              apis={apis}
              editable={editable}
              onUpdate={onUpdate}
            />
          )}
        </div>
      ))}
      <Button
        disabled={!editable || !canAppend}
        onClick={() => {
          const next = appendRegionDelay(region)
          if (next) onUpdate(next)
        }}
      >
        添加等待步骤
      </Button>
      {availableApis.length > 0 && (
        <Space>
          <Select
            aria-label={`${region.role} 待添加接口`}
            value={activeApiId}
            disabled={!editable || !canAppend}
            options={availableApis.map((api) => ({ value: api.id, label: api.name }))}
            onChange={setSelectedApiId}
            style={{ minWidth: 180 }}
          />
          <Button
            disabled={!editable || !canAppend || !activeApiId}
            onClick={() => {
              const api = availableApis.find((item) => item.id === activeApiId)
              if (!api) return
              const next = appendRegionApi(region, api.id, api.current_version)
              if (next) onUpdate(next)
            }}
          >
            添加接口步骤
          </Button>
        </Space>
      )}
      {canAppendRegionSignal(region, owner) && (
        <Space>
          <Button
            disabled={!editable}
            onClick={() => {
              const next = appendRegionSignal(region, owner, 'break')
              if (next) onUpdate(next)
            }}
          >
            添加退出循环
          </Button>
          <Button
            disabled={!editable}
            onClick={() => {
              const next = appendRegionSignal(region, owner, 'continue')
              if (next) onUpdate(next)
            }}
          >
            添加继续下一轮
          </Button>
        </Space>
      )}
    </div>
  )
}

function RegionApiFields({
  node,
  region,
  apis,
  editable,
  onUpdate,
}: {
  node: WorkflowNode
  region: WorkflowRegion
  apis: ApiDefinition[]
  editable: boolean
  onUpdate: (region: WorkflowRegion) => void
}) {
  const selectedId = node.config.api_definition_id
  const options = apis.map((api) => ({ value: api.id, label: api.name }))
  if (typeof selectedId === 'string' && !apis.some((api) => api.id === selectedId))
    options.push({ value: selectedId, label: `已引用接口 ${selectedId}` })
  return (
    <Select
      aria-label={`${node.name} 接口`}
      value={typeof selectedId === 'string' ? selectedId : undefined}
      disabled={!editable}
      options={options}
      onChange={(apiId: string) => {
        const api = apis.find((item) => item.id === apiId)
        if (!api) return
        onUpdate({
          ...region,
          nodes: region.nodes.map((item) =>
            item.id === node.id
              ? {
                  ...item,
                  config: {
                    ...item.config,
                    api_definition_id: api.id,
                    api_version: api.current_version,
                  },
                }
              : item,
          ),
        })
      }}
      style={{ minWidth: 180 }}
    />
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
