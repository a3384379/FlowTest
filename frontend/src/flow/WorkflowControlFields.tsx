import {
  Alert,
  Button,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Typography,
} from 'antd'
import { useState } from 'react'
import type { ApiDefinition, WorkflowDefinition, WorkflowNode, WorkflowRegion } from '../lib/api'
import { NodeEditContext } from './editor/node-edit-session'
import ConditionLoopStateFields from './ConditionLoopStateFields'
import ControlConditionFields from './ControlConditionFields'
import ControlConfigurationJson from './ControlConfigurationJson'
import ControlSourcePicker from './ControlSourcePicker'
import {
  appendRegionApi,
  appendRegionDelay,
  appendRegionSignal,
  canAppendRegionSignal,
  addSwitchBranch,
  addTryCatch,
  removeSwitchBranch,
  removeTryCatch,
  setSwitchDefaultBehavior,
  setTryFinally,
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
  onStructureChange?: (definition: WorkflowDefinition) => void
  onRegionUpdate: (region: WorkflowRegion) => void
  inline?: boolean
}

export default function WorkflowControlFields({
  node,
  definition,
  regions,
  editable,
  apis = [],
  onUpdate,
  onStructureChange,
  onRegionUpdate,
  inline,
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
      <ControlPolicyFields
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
      <ControlEditHint inline={inline} />
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
        onStructureChange={onStructureChange}
      />
      <TryCatchFields
        node={node}
        definition={definition}
        configuration={configuration}
        editable={configFieldsEditable}
        onChange={updateConfiguration}
        onStructureChange={onStructureChange}
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
          definition={definition}
          onStructureChange={onStructureChange}
          editable={editable}
          apis={apis}
          onUpdate={onRegionUpdate}
        />
      ))}
    </section>
  )
}

function ControlEditHint({ inline }: { inline?: boolean }) {
  return (
    <Typography.Paragraph type="secondary">
      {inline
        ? '嵌套控制块的可视化配置直接更新流程草稿；JSON 修改需先应用，再保存工作流。'
        : '控制块的来源、条件和策略按版本化配置保存；修改后先应用节点配置。'}
    </Typography.Paragraph>
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
        aria-label="重复次数"
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

function ControlPolicyFields({
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
  const kind = policyKind(node.capability_id)
  if (!kind) return null
  const policy = asRecord(configuration.policy) ?? {}
  const change = (key: string, value: number | string) =>
    onChange({ ...configuration, policy: { ...policy, [key]: value } })
  return (
    <section aria-label="控制执行策略">
      <Typography.Title level={5}>执行策略</Typography.Title>
      <Space wrap>
        {policyNumbers(kind).map((field) => (
          <PolicyNumber
            key={field.key}
            label={field.label}
            value={policy[field.key]}
            fallback={field.fallback}
            max={field.max}
            editable={editable}
            onChange={(value) => change(field.key, value)}
          />
        ))}
        {kind !== 'conditional' && (
          <label>
            出错策略
            <Select
              aria-label="出错策略"
              disabled={!editable}
              value={
                typeof policy.on_error === 'string'
                  ? policy.on_error
                  : kind === 'parallel'
                    ? 'stop_on_error'
                    : 'stop'
              }
              options={policyErrorOptions(kind)}
              onChange={(value: string) => change('on_error', value)}
              style={{ minWidth: 180 }}
            />
          </label>
        )}
      </Space>
    </section>
  )
}

type PolicyKind = 'loop' | 'conditional' | 'parallel'
type PolicyNumberField = { key: string; label: string; fallback: number; max: number }

function policyKind(capabilityId: string | undefined): PolicyKind | null {
  if (capabilityId === 'flow.control.foreach' || capabilityId === 'flow.control.repeat')
    return 'loop'
  if (capabilityId === 'flow.control.parallel') return 'parallel'
  if (
    ['flow.control.while', 'flow.control.do_while', 'flow.control.until'].includes(
      capabilityId ?? '',
    )
  )
    return 'conditional'
  return null
}

function policyNumbers(kind: PolicyKind): PolicyNumberField[] {
  const fields: PolicyNumberField[] = []
  if (kind !== 'conditional')
    fields.push({
      key: 'concurrency',
      label: '最大并发数',
      fallback: kind === 'parallel' ? 2 : 1,
      max: 20,
    })
  if (kind !== 'parallel')
    fields.push({
      key: 'max_iterations',
      label: '最大迭代次数',
      fallback: kind === 'conditional' ? 100 : 1000,
      max: 1000,
    })
  fields.push({ key: 'timeout_seconds', label: '控制块超时秒数', fallback: 120, max: 3600 })
  return fields
}

function policyErrorOptions(kind: PolicyKind) {
  return kind === 'parallel'
    ? [
        { value: 'stop_on_error', label: '首个错误后停止' },
        { value: 'collect_all', label: '收集所有分支结果' },
      ]
    : [
        { value: 'stop', label: '首个错误后停止' },
        { value: 'continue_collect', label: '继续并收集结果' },
      ]
}

function PolicyNumber({
  label,
  value,
  fallback,
  max,
  editable,
  onChange,
}: {
  label: string
  value: unknown
  fallback: number
  max: number
  editable: boolean
  onChange: (value: number) => void
}) {
  return (
    <label>
      {label}
      <InputNumber
        aria-label={label}
        min={1}
        max={max}
        precision={0}
        disabled={!editable}
        value={typeof value === 'number' ? value : fallback}
        onChange={(number) => {
          if (number !== null) onChange(number)
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
  onStructureChange,
}: {
  node: WorkflowNode
  definition?: WorkflowDefinition
  configuration: Record<string, unknown>
  editable: boolean
  onChange: (configuration: Record<string, unknown>) => void
  onStructureChange?: (definition: WorkflowDefinition) => void
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
      node={node}
      definition={definition}
      configuration={configuration}
      choices={choices}
      editable={editable}
      onChange={onChange}
      onStructureChange={onStructureChange}
    />
  )
}

function SwitchBranchFields({
  node,
  definition,
  configuration,
  choices,
  editable,
  onChange,
  onStructureChange,
}: {
  node: WorkflowNode
  definition?: WorkflowDefinition
  configuration: Record<string, unknown>
  choices: SourceChoice[]
  editable: boolean
  onChange: (configuration: Record<string, unknown>) => void
  onStructureChange?: (definition: WorkflowDefinition) => void
}) {
  const [modal, holder] = Modal.useModal()
  if (!Array.isArray(configuration.branches)) return null
  const branches = configuration.branches as unknown[]
  const valueMode = switchToValue(configuration)
  const applyStructure = (next: WorkflowDefinition | null) => {
    if (next) onStructureChange?.(next)
  }
  async function changeDefaultBehavior(behavior: 'run' | 'skip' | 'fail') {
    if (!definition || switchDefaultBehavior(configuration.default) === behavior) return
    const confirmed = await modal.confirm({
      title: '切换默认分支行为？',
      content: '切换后默认区域及其中的步骤可能从草稿移除；此操作可通过撤销恢复。',
      okText: '确定切换',
      cancelText: '保留当前行为',
    })
    if (confirmed) applyStructure(setSwitchDefaultBehavior(definition, node.id, behavior))
  }
  return (
    <>
      {holder}
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
        {definition && onStructureChange && (
          <Space wrap>
            <Button
              disabled={!editable || branches.length >= 100}
              onClick={() => applyStructure(addSwitchBranch(definition, node.id))}
            >
              添加分支
            </Button>
            <Select
              aria-label="默认分支行为"
              disabled={!editable}
              value={switchDefaultBehavior(configuration.default)}
              options={[
                { value: 'run', label: '执行默认区域' },
                { value: 'skip', label: '无匹配时跳过' },
                { value: 'fail', label: '无匹配时失败' },
              ]}
              onChange={(behavior: 'run' | 'skip' | 'fail') => void changeDefaultBehavior(behavior)}
              style={{ minWidth: 180 }}
            />
          </Space>
        )}
        {branches.map((raw, index) => {
          const branch = asRecord(raw)
          if (!branch) return null
          return (
            <SwitchBranchRow
              key={String(branch.id ?? index)}
              branch={branch}
              index={index}
              branches={branches}
              configuration={configuration}
              choices={choices}
              editable={editable}
              onChange={onChange}
              onRemove={
                definition && onStructureChange
                  ? () => applyStructure(removeSwitchBranch(definition, node.id, String(branch.id)))
                  : undefined
              }
            />
          )
        })}
      </Space>
    </>
  )
}

function SwitchBranchRow({
  branch,
  index,
  branches,
  configuration,
  choices,
  editable,
  onChange,
  onRemove,
}: {
  branch: Record<string, unknown>
  index: number
  branches: unknown[]
  configuration: Record<string, unknown>
  choices: SourceChoice[]
  editable: boolean
  onChange: (configuration: Record<string, unknown>) => void
  onRemove?: () => void
}) {
  const label = `分支 ${String(branch.label)}`
  const update = (patch: Record<string, unknown>) =>
    onChange({
      ...configuration,
      branches: branches.map((item, position) =>
        position === index ? { ...branch, ...patch } : item,
      ),
    })
  const move = (direction: -1 | 1) => {
    const reordered = [...branches]
    const target = index + direction
    if (target < 0 || target >= reordered.length) return
    ;[reordered[index], reordered[target]] = [reordered[target], reordered[index]]
    onChange({ ...configuration, branches: reordered })
  }
  return (
    <div className="workflow-switch-branch">
      <SwitchBranchHeader
        key={`${String(branch.id)}:${String(branch.label)}`}
        id={String(branch.id)}
        label={String(branch.label)}
        index={index}
        total={branches.length}
        editable={editable}
        onRename={(name) => update({ label: name })}
        onMove={move}
      />
      {onRemove && (
        <Popconfirm
          title="删除分支及所属区域？"
          description="该分支的区域与嵌套区域将从草稿移除；此操作可撤销。"
          disabled={!editable || branches.length <= 1}
          onConfirm={onRemove}
        >
          <Button danger disabled={!editable || branches.length <= 1}>
            删除分支 {String(branch.label)}
          </Button>
        </Popconfirm>
      )}
      {configuration.mode === 'rules' ? (
        <ControlConditionFields
          label={`${label} 条件`}
          value={branch.condition}
          choices={choices}
          editable={editable}
          onChange={(condition) => update({ condition })}
        />
      ) : (
        <SourceShortcut
          label={`${label} 匹配来源`}
          value={branch.match}
          choices={choices}
          editable={editable}
          onChange={(match) => update({ match })}
        />
      )}
    </div>
  )
}

function switchDefaultBehavior(value: unknown): 'run' | 'skip' | 'fail' | undefined {
  const behavior = asRecord(value)?.behavior
  if (behavior === 'run' || behavior === 'skip' || behavior === 'fail') return behavior
  return undefined
}

function TryCatchFields({
  node,
  definition,
  configuration,
  editable,
  onChange,
  onStructureChange,
}: {
  node: WorkflowNode
  definition?: WorkflowDefinition
  configuration: Record<string, unknown>
  editable: boolean
  onChange: (configuration: Record<string, unknown>) => void
  onStructureChange?: (definition: WorkflowDefinition) => void
}) {
  if (node.capability_id !== 'flow.control.try' || !Array.isArray(configuration.catches))
    return null
  const catches = configuration.catches as unknown[]
  const structural = Boolean(definition && onStructureChange)
  const updateCatch = (id: string, patch: Record<string, unknown>) =>
    onChange({
      ...configuration,
      catches: catches.map((item) =>
        asRecord(item)?.id === id ? { ...asRecord(item), ...patch } : item,
      ),
    })
  const moveCatch = (index: number, direction: -1 | 1) => {
    const next = [...catches]
    const target = index + direction
    if (target < 0 || target >= next.length) return
    ;[next[index], next[target]] = [next[target], next[index]]
    onChange({ ...configuration, catches: next })
  }
  const applyStructure = (next: WorkflowDefinition | null) => {
    if (next) onStructureChange?.(next)
  }
  return (
    <section className="workflow-config-section" aria-label="异常处理配置">
      <Typography.Title level={5}>异常处理</Typography.Title>
      {structural && (
        <Space wrap>
          <Button
            disabled={!editable || catches.length >= 20}
            onClick={() => applyStructure(addTryCatch(definition!, node.id))}
          >
            添加 Catch
          </Button>
          {configuration.finally_body ? (
            <Popconfirm
              title="移除 Finally 区域？"
              description="区域内步骤及其嵌套控制块将一并移除；草稿可撤销。"
              onConfirm={() => applyStructure(setTryFinally(definition!, node.id, false))}
            >
              <Button disabled={!editable || catches.length === 0}>移除 Finally</Button>
            </Popconfirm>
          ) : (
            <Button
              disabled={!editable}
              onClick={() => applyStructure(setTryFinally(definition!, node.id, true))}
            >
              添加 Finally
            </Button>
          )}
        </Space>
      )}
      {catches.map((item, index) => {
        const itemRecord = asRecord(item)
        if (!itemRecord || typeof itemRecord.id !== 'string') return null
        const id = itemRecord.id
        return (
          <TryCatchRow
            key={`${id}:${String(itemRecord.label)}:${JSON.stringify(itemRecord.error_codes)}`}
            item={itemRecord}
            index={index}
            count={catches.length}
            editable={editable}
            canRemove={structural && (catches.length > 1 || Boolean(configuration.finally_body))}
            onChange={(patch) => updateCatch(id, patch)}
            onMove={(direction) => moveCatch(index, direction)}
            onRemove={() => applyStructure(removeTryCatch(definition!, node.id, id))}
          />
        )
      })}
    </section>
  )
}

function TryCatchRow({
  item,
  index,
  count,
  editable,
  canRemove,
  onChange,
  onMove,
  onRemove,
}: {
  item: Record<string, unknown>
  index: number
  count: number
  editable: boolean
  canRemove: boolean
  onChange: (patch: Record<string, unknown>) => void
  onMove: (direction: -1 | 1) => void
  onRemove: () => void
}) {
  const label = String(item.label ?? '')
  const codes = Array.isArray(item.error_codes)
    ? item.error_codes.filter((code): code is string => typeof code === 'string')
    : []
  const [labelDraft, setLabelDraft] = useState(label)
  const [codesDraft, setCodesDraft] = useState(codes.join(', '))
  const [codesError, setCodesError] = useState(false)
  const id = String(item.id)
  function applyCodes() {
    const parsed = [
      ...new Set(
        codesDraft
          .split(',')
          .map((code) => code.trim())
          .filter(Boolean),
      ),
    ]
    if (parsed.length === 0 || parsed.length > 20) {
      setCodesError(true)
      return
    }
    setCodesError(false)
    if (JSON.stringify(parsed) !== JSON.stringify(codes)) onChange({ error_codes: parsed })
  }
  return (
    <div className="workflow-switch-branch">
      <Space wrap>
        <Input
          aria-label={`Catch ${id} 名称`}
          value={labelDraft}
          maxLength={200}
          disabled={!editable}
          status={labelDraft.trim() ? undefined : 'error'}
          onChange={(event) => setLabelDraft(event.target.value)}
          onBlur={() => {
            const next = labelDraft.trim()
            if (next && next !== label) onChange({ label: next })
            else setLabelDraft(label)
          }}
          onPressEnter={(event) => event.currentTarget.blur()}
        />
        <Button disabled={!editable || index === 0} onClick={() => onMove(-1)}>
          上移 Catch
        </Button>
        <Button disabled={!editable || index === count - 1} onClick={() => onMove(1)}>
          下移 Catch
        </Button>
        {canRemove && (
          <Popconfirm
            title={`删除 Catch ${label}？`}
            description="此 Catch 区域及其嵌套步骤将被删除；草稿可撤销。"
            onConfirm={onRemove}
          >
            <Button danger disabled={!editable}>
              删除 Catch
            </Button>
          </Popconfirm>
        )}
      </Space>
      <Input
        aria-label={`Catch ${id} 错误码`}
        value={codesDraft}
        disabled={!editable}
        status={codesError ? 'error' : undefined}
        onChange={(event) => {
          setCodesDraft(event.target.value)
          setCodesError(false)
        }}
        onBlur={applyCodes}
        onPressEnter={(event) => event.currentTarget.blur()}
      />
      {codesError && (
        <Typography.Text type="danger">请输入 1–20 个逗号分隔的错误码。</Typography.Text>
      )}
    </div>
  )
}

function SwitchBranchHeader({
  id,
  label,
  index,
  total,
  editable,
  onRename,
  onMove,
}: {
  id: string
  label: string
  index: number
  total: number
  editable: boolean
  onRename: (label: string) => void
  onMove: (direction: -1 | 1) => void
}) {
  const [draft, setDraft] = useState(label)
  return (
    <Space wrap>
      <Input
        aria-label={`分支 ${id} 名称`}
        value={draft}
        maxLength={200}
        status={draft.trim() ? undefined : 'error'}
        disabled={!editable}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={() => {
          const name = draft.trim()
          if (name && name !== label) onRename(name)
          else setDraft(label)
        }}
        onPressEnter={(event) => event.currentTarget.blur()}
      />
      <Button disabled={!editable || index === 0} onClick={() => onMove(-1)}>
        上移分支
      </Button>
      <Button disabled={!editable || index === total - 1} onClick={() => onMove(1)}>
        下移分支
      </Button>
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
  definition,
  onStructureChange,
  editable,
  apis,
  onUpdate,
}: {
  region: WorkflowRegion
  owner: WorkflowNode
  definition?: WorkflowDefinition
  onStructureChange?: (definition: WorkflowDefinition) => void
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
        definition={definition}
        onStructureChange={onStructureChange}
        renderNestedControl={(node, containing) => (
          <NestedControlEditor
            node={node}
            containing={containing}
            definition={definition}
            apis={apis}
            editable={editable && !dirty}
            onRegionUpdate={onUpdate}
            onStructureChange={onStructureChange}
          />
        )}
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

function NestedControlEditor({
  node,
  containing,
  definition,
  apis,
  editable,
  onRegionUpdate,
  onStructureChange,
}: {
  node: WorkflowNode
  containing: WorkflowRegion
  definition?: WorkflowDefinition
  apis: ApiDefinition[]
  editable: boolean
  onRegionUpdate: (region: WorkflowRegion) => void
  onStructureChange?: (definition: WorkflowDefinition) => void
}) {
  if (!definition) return null
  return (
    <NodeEditContext.Provider value={null}>
      <WorkflowControlFields
        key={node.id}
        node={node}
        definition={definition}
        regions={definition.regions?.filter((region) => region.owner_node_id === node.id) ?? []}
        editable={editable}
        inline
        apis={apis}
        onUpdate={(updated) =>
          onRegionUpdate({
            ...containing,
            nodes: containing.nodes.map((item) => (item.id === node.id ? updated : item)),
          })
        }
        onRegionUpdate={onRegionUpdate}
        onStructureChange={onStructureChange}
      />
    </NodeEditContext.Provider>
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
