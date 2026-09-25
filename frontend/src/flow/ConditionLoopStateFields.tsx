import { Alert, Button, Input, InputNumber, Select, Space, Typography } from 'antd'
import { useMemo, useState } from 'react'
import type { WorkflowDefinition, WorkflowNode } from '../lib/api'
import {
  conditionStateSources,
  type SourceChoice,
  type ValueSource,
} from './editor/control-source-browser'
import { useNodeEditContext } from './editor/node-edit-session'
import ControlSourcePicker from './ControlSourcePicker'

type LiteralSource = Extract<ValueSource, { kind: 'literal' }>
type VariableSource = Extract<ValueSource, { kind: 'variable' }>
type NodeOutputSource = Extract<ValueSource, { kind: 'node_output' }>
type StateUpdate = { kind: 'set' | 'add' | 'append'; value: ValueSource }

const namePattern = /^[A-Za-z_][A-Za-z0-9_.-]*$/
const variableScopes = ['runtime', 'workflow', 'input', 'local', 'loop', 'state', 'error']

export default function ConditionLoopStateFields({
  definition,
  node,
  configuration,
  editable,
  onChange,
}: {
  definition?: WorkflowDefinition
  node?: WorkflowNode
  configuration: Record<string, unknown>
  editable: boolean
  onChange: (configuration: Record<string, unknown>) => void
}) {
  const state = asRecord(configuration.state)
  const updates = asRecord(configuration.update)
  const [newName, setNewName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const initialChoices = useMemo(
    () => (definition && node ? conditionStateSources(definition, node, 'initial') : []),
    [definition, node],
  )
  const updateChoices = useMemo(
    () => (definition && node ? conditionStateSources(definition, node, 'update') : []),
    [definition, node],
  )
  if (!state || !updates) {
    return <Alert type="warning" title="状态配置无法可视化编辑，请检查配置 JSON。" />
  }
  const declaredState = state

  function setSource(name: string, source: ValueSource) {
    onChange({ ...configuration, state: { ...declaredState, [name]: source } })
  }

  function setUpdate(name: string, update: StateUpdate | null) {
    const next = { ...updates }
    if (update) next[name] = update
    else delete next[name]
    onChange({ ...configuration, update: next })
  }

  function addState() {
    const name = newName.trim()
    if (!namePattern.test(name) || name.length > 160 || name in declaredState) {
      setError('状态名须唯一，并以字母或下划线开头；最多 160 个字符。')
      return
    }
    onChange({
      ...configuration,
      state: { ...declaredState, [name]: { kind: 'literal', value: 0 } },
      update: { ...updates, [name]: { kind: 'add', value: { kind: 'literal', value: 1 } } },
    })
    setNewName('')
    setError(null)
  }

  return (
    <section aria-label="条件循环状态">
      <Typography.Title level={5}>循环状态</Typography.Title>
      <Typography.Paragraph type="secondary">
        初始化值在循环前求值；更新值在每轮结束后从同一轮快照求值。只有声明的状态字段可更新。
      </Typography.Paragraph>
      {Object.entries(state).map(([name, raw]) => {
        const source = asSource(raw)
        const update = asUpdate(updates[name])
        const typeWarning = stateTypeWarning(source, update)
        return (
          <div className="workflow-control-state-row" key={name} aria-label={`状态 ${name}`}>
            <Space>
              <Typography.Text strong>{name}</Typography.Text>
              <Button
                danger
                disabled={!editable}
                onClick={() => {
                  const nextState = { ...state }
                  const nextUpdates = { ...updates }
                  delete nextState[name]
                  delete nextUpdates[name]
                  onChange({ ...configuration, state: nextState, update: nextUpdates })
                }}
              >
                删除状态
              </Button>
            </Space>
            {source ? (
              <SourceFields
                label={`${name} 初始值`}
                source={source}
                choices={initialChoices}
                editable={editable}
                onChange={(value) => setSource(name, value)}
              />
            ) : (
              <Alert type="warning" title="初始值来源无法可视化编辑，请检查配置 JSON。" />
            )}
            <label>
              每轮更新
              <Select
                aria-label={`${name} 更新方式`}
                disabled={!editable}
                value={update?.kind ?? 'none'}
                options={[
                  { label: '不更新', value: 'none' },
                  { label: '设置', value: 'set' },
                  { label: '数值相加', value: 'add' },
                  { label: '追加数组', value: 'append' },
                ]}
                onChange={(kind: StateUpdate['kind'] | 'none') =>
                  setUpdate(name, kind === 'none' ? null : nextUpdate(kind, update))
                }
              />
            </label>
            {typeWarning && <Alert type="warning" title={typeWarning} />}
            {update && (
              <SourceFields
                label={`${name} 更新值`}
                source={update.value}
                choices={updateChoices}
                editable={editable}
                onChange={(value) => setUpdate(name, { ...update, value })}
              />
            )}
            {updates[name] !== undefined && !update && (
              <Alert type="warning" title="更新值无法可视化编辑，请检查配置 JSON。" />
            )}
          </div>
        )
      })}
      <Space>
        <Input
          aria-label="新状态名"
          placeholder="例如 page、cursor、hasNext"
          disabled={!editable}
          value={newName}
          maxLength={160}
          onChange={(event) => setNewName(event.target.value)}
        />
        <Button disabled={!editable} onClick={addState}>
          添加状态字段
        </Button>
      </Space>
      {error && <Alert type="error" title={error} />}
    </section>
  )
}

function SourceFields({
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
  return (
    <div aria-label={label}>
      <ControlSourcePicker
        label={`${label} 来源浏览器`}
        source={source}
        choices={choices}
        editable={editable}
        onChange={onChange}
      />
      <Select
        aria-label={`${label} 来源类型`}
        disabled={!editable}
        value={source.kind}
        options={[
          { label: '固定值', value: 'literal' },
          { label: '作用域变量', value: 'variable' },
          { label: '节点输出', value: 'node_output' },
        ]}
        onChange={(kind: ValueSource['kind']) => onChange(defaultSource(kind))}
      />
      {source.kind === 'literal' && (
        <LiteralField
          label={label}
          value={source.value}
          editable={editable}
          onChange={(value) => onChange(literal(value))}
        />
      )}
      {source.kind === 'variable' && (
        <>
          <Select
            aria-label={`${label} 作用域`}
            disabled={!editable}
            value={source.scope}
            options={variableScopes.map((scope) => ({ label: scope, value: scope }))}
            onChange={(scope: string) => onChange({ ...source, scope })}
          />
          <PathFields
            label={`${label} 路径`}
            path={source.path}
            editable={editable}
            required
            onChange={(path) => onChange({ ...source, path })}
          />
        </>
      )}
      {source.kind === 'node_output' && (
        <>
          <Input
            aria-label={`${label} 节点 ID`}
            disabled={!editable}
            value={source.node_id}
            maxLength={128}
            onChange={(event) => onChange({ ...source, node_id: event.target.value })}
          />
          <PathFields
            label={`${label} 路径`}
            path={source.path}
            editable={editable}
            required={false}
            onChange={(path) => onChange({ ...source, path })}
          />
        </>
      )}
    </div>
  )
}

function LiteralField({
  label,
  value,
  editable,
  onChange,
}: {
  label: string
  value: unknown
  editable: boolean
  onChange: (value: unknown) => void
}) {
  const current = JSON.stringify(value, null, 2) as string
  const session = useNodeEditContext()
  const fieldKey = `state-literal-${label}`
  const saved = session?.draft.rawFields[fieldKey]
  const [initial] = useState(() => initialLiteralDraft(saved, current))
  const [text, setText] = useState(initial.text)
  const [base, setBase] = useState(initial.base)
  const [dirty, setDirty] = useState(initial.dirty)
  const [error, setError] = useState<string | null>(null)
  function discard() {
    setText(current)
    setBase(current)
    setDirty(false)
    setError(null)
    session?.clearRaw(fieldKey)
  }
  function apply() {
    if (base !== current) {
      setError('值已从其他编辑更新，请丢弃旧草稿。')
      return
    }
    try {
      const parsed: unknown = JSON.parse(text)
      onChange(parsed)
      setDirty(false)
      setError(null)
      session?.clearRaw(fieldKey)
    } catch {
      setError('请输入有效的 JSON 值。')
    }
  }
  return (
    <div>
      <Input.TextArea
        aria-label={`${label} JSON 值`}
        disabled={!editable}
        rows={2}
        value={dirty ? text : current}
        status={error ? 'error' : undefined}
        onChange={(event) => {
          if (event.target.value === current) {
            discard()
            return
          }
          if (!dirty) setBase(current)
          setText(event.target.value)
          setDirty(true)
          setError(null)
          session?.setRaw(fieldKey, {
            text: event.target.value,
            baseText: dirty ? base : current,
            error: '请先应用或丢弃状态值草稿。',
          })
        }}
      />
      <Button disabled={!editable || !dirty} onClick={apply}>
        应用值
      </Button>
      <Button disabled={!editable || !dirty} onClick={discard}>
        丢弃值草稿
      </Button>
      {error && <Alert type="error" title={error} />}
    </div>
  )
}

function initialLiteralDraft(
  saved: { text: string; baseText?: string } | undefined,
  current: string,
) {
  return {
    text: saved?.text ?? current,
    base: saved?.baseText ?? current,
    dirty: saved !== undefined,
  }
}

function PathFields({
  label,
  path,
  editable,
  required,
  onChange,
}: {
  label: string
  path: Array<string | number>
  editable: boolean
  required: boolean
  onChange: (path: Array<string | number>) => void
}) {
  return (
    <div aria-label={label}>
      {path.map((segment, index) => (
        <Space key={index}>
          <Select
            aria-label={`${label} 第 ${index + 1} 段类型`}
            disabled={!editable}
            value={typeof segment === 'number' ? 'index' : 'field'}
            options={[
              { label: '字段', value: 'field' },
              { label: '数组索引', value: 'index' },
            ]}
            onChange={(kind: 'field' | 'index') =>
              onChange(replaceSegment(path, index, kind === 'index' ? 0 : 'field'))
            }
          />
          {typeof segment === 'number' ? (
            <InputNumber
              aria-label={`${label} 第 ${index + 1} 段`}
              disabled={!editable}
              min={0}
              value={segment}
              onChange={(value) => {
                if (value !== null) onChange(replaceSegment(path, index, value))
              }}
            />
          ) : (
            <Input
              aria-label={`${label} 第 ${index + 1} 段`}
              disabled={!editable}
              value={segment}
              onChange={(event) => onChange(replaceSegment(path, index, event.target.value))}
            />
          )}
          <Button
            disabled={!editable || (required && path.length === 1)}
            onClick={() => onChange(path.filter((_, position) => position !== index))}
          >
            删除路径段
          </Button>
        </Space>
      ))}
      <Button
        disabled={!editable || path.length >= 32}
        onClick={() => onChange([...path, 'field'])}
      >
        添加路径段
      </Button>
    </div>
  )
}

function replaceSegment(path: Array<string | number>, index: number, value: string | number) {
  return path.map((item, position) => (position === index ? value : item))
}

function literal(value: unknown): LiteralSource {
  return { kind: 'literal', value }
}

function nextUpdate(kind: StateUpdate['kind'], current: StateUpdate | null): StateUpdate {
  if (current?.kind === kind) return current
  if (kind === 'add') return { kind, value: literal(1) }
  if (kind === 'append') return { kind, value: literal(null) }
  return { kind, value: current?.value ?? literal(null) }
}

function stateTypeWarning(source: ValueSource | null, update: StateUpdate | null): string | null {
  if (source?.kind !== 'literal' || !update) return null
  if (update.kind === 'add') return addTypeWarning(source.value, update.value)
  if (update.kind === 'append' && !Array.isArray(source.value)) {
    return '追加数组要求初始状态是数组。'
  }
  return null
}

function addTypeWarning(initialValue: unknown, updateValue: ValueSource): string | null {
  if (typeof initialValue !== 'number') {
    return '数值相加要求初始状态是数字。'
  }
  if (updateValue.kind === 'literal' && typeof updateValue.value !== 'number') {
    return '数值相加要求更新值是数字。'
  }
  return null
}

function defaultSource(kind: ValueSource['kind']): ValueSource {
  if (kind === 'variable') return { kind, scope: 'state', path: ['page'] }
  if (kind === 'node_output') return { kind, node_id: '', path: [] }
  return literal(0)
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null
}

function asSource(value: unknown): ValueSource | null {
  const source = asRecord(value)
  if (!source) return null
  if (source.kind === 'literal') return asLiteralSource(source)
  if (source.kind === 'variable') return asVariableSource(source)
  if (source.kind === 'node_output') return asNodeOutputSource(source)
  return null
}

function asLiteralSource(source: Record<string, unknown>): LiteralSource | null {
  return source.value !== undefined && onlyKeys(source, ['kind', 'value'])
    ? { kind: 'literal', value: source.value }
    : null
}

function asVariableSource(source: Record<string, unknown>): VariableSource | null {
  if (
    !onlyKeys(source, ['kind', 'scope', 'path']) ||
    typeof source.scope !== 'string' ||
    !variableScopes.includes(source.scope) ||
    !validPath(source.path, true)
  )
    return null
  return { kind: 'variable', scope: source.scope, path: source.path }
}

function asNodeOutputSource(source: Record<string, unknown>): NodeOutputSource | null {
  if (
    !onlyKeys(source, ['kind', 'node_id', 'path']) ||
    typeof source.node_id !== 'string' ||
    !validPath(source.path, false)
  )
    return null
  return { kind: 'node_output', node_id: source.node_id, path: source.path }
}

function validPath(value: unknown, required: boolean): value is Array<string | number> {
  return (
    Array.isArray(value) &&
    (!required || value.length > 0) &&
    value.length <= 32 &&
    value.every(
      (segment) => typeof segment === 'string' || (Number.isInteger(segment) && segment >= 0),
    )
  )
}

function asUpdate(value: unknown): StateUpdate | null {
  const update = asRecord(value)
  const source = asSource(update?.value)
  if (
    !update ||
    !source ||
    !onlyKeys(update, ['kind', 'value']) ||
    !['set', 'add', 'append'].includes(String(update.kind))
  )
    return null
  return { kind: update.kind as StateUpdate['kind'], value: source }
}

function onlyKeys(value: Record<string, unknown>, allowed: string[]): boolean {
  return Object.keys(value).every((key) => allowed.includes(key))
}
