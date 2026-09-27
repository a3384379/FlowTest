import { Alert, Button, Select, Space, Typography } from 'antd'
import { SourceFields } from './ConditionLoopStateFields'
import {
  addCondition,
  conditionNeedsRight,
  CONDITION_OPERATORS,
  countComparisons,
  defaultCondition,
  parseCondition,
  removeCondition,
  replaceCondition,
  type ConditionExpression,
  type ConditionOperator,
} from './editor/control-condition'
import type { SourceChoice } from './editor/control-source-browser'
import { useNodeEditContext } from './editor/node-edit-session'

const kindOptions = [
  { label: '比较', value: 'compare' },
  { label: '全部满足', value: 'all' },
  { label: '任一满足', value: 'any' },
  { label: '取反', value: 'not' },
]

const operatorLabels: Record<ConditionOperator, string> = {
  equals: '等于',
  not_equals: '不等于',
  gt: '大于',
  gte: '大于等于',
  lt: '小于',
  lte: '小于等于',
  contains: '包含',
  in: '属于集合',
  exists: '存在',
  not_exists: '不存在',
  is_null: '为空值',
  not_null: '不为空值',
  is_empty: '为空集合或字符串',
  not_empty: '非空集合或字符串',
  length_equals: '长度等于',
  length_gt: '长度大于',
  length_lt: '长度小于',
}

export default function ControlConditionFields({
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
  onChange: (condition: ConditionExpression) => void
}) {
  const condition = parseCondition(value)
  const session = useNodeEditContext()
  const hasLiteralDraft = Object.keys(session?.draft.rawFields ?? {}).some((key) =>
    key.startsWith(`state-literal-${label}`),
  )
  if (!condition)
    return <Alert type="warning" title={`${label}无法可视化编辑，请检查配置 JSON。`} />
  return (
    <section aria-label={label}>
      <Typography.Title level={5}>{label}</Typography.Title>
      {hasLiteralDraft && (
        <Typography.Text type="secondary">先应用或丢弃条件值草稿，再修改条件结构。</Typography.Text>
      )}
      <ConditionRow
        label={label}
        root={condition}
        value={condition}
        path={[]}
        depth={1}
        choices={choices}
        editable={editable}
        structureEditable={editable && !hasLiteralDraft}
        onChange={onChange}
      />
    </section>
  )
}

function ConditionRow({
  label,
  root,
  value,
  path,
  depth,
  choices,
  editable,
  structureEditable,
  onChange,
}: {
  label: string
  root: ConditionExpression
  value: ConditionExpression
  path: number[]
  depth: number
  choices: SourceChoice[]
  editable: boolean
  structureEditable: boolean
  onChange: (condition: ConditionExpression) => void
}) {
  const update = (next: ConditionExpression) => onChange(replaceCondition(root, path, next))
  const childProps = { root, choices, editable, structureEditable, onChange }
  return (
    <div className="workflow-control-condition" aria-label={label}>
      <Space wrap>
        <Select
          aria-label={`${label} 组合方式`}
          value={value.kind}
          disabled={!structureEditable}
          options={kindOptions.filter((option) => depth < 8 || option.value === 'compare')}
          onChange={(kind: ConditionExpression['kind']) => update(defaultCondition(kind))}
        />
        {path.length > 0 && (
          <Button
            danger
            disabled={!structureEditable || !canRemove(root, path)}
            onClick={() => onChange(removeCondition(root, path))}
          >
            删除此条件
          </Button>
        )}
      </Space>
      {value.kind === 'compare' && (
        <ComparisonFields
          label={label}
          value={value}
          choices={choices}
          editable={editable}
          onChange={update}
        />
      )}
      {value.kind === 'not' && (
        <ConditionRow
          {...childProps}
          label={`${label} 的子条件`}
          value={value.condition}
          path={[...path, 0]}
          depth={depth + 1}
        />
      )}
      {(value.kind === 'all' || value.kind === 'any') && (
        <Space orientation="vertical">
          {value.conditions.map((child, index) => (
            <ConditionRow
              {...childProps}
              key={index}
              label={`${label} 第 ${index + 1} 项`}
              value={child}
              path={[...path, index]}
              depth={depth + 1}
            />
          ))}
          <Button
            disabled={!structureEditable || depth >= 8 || countComparisons(root) >= 100}
            onClick={() => onChange(addCondition(root, path))}
          >
            添加比较条件
          </Button>
        </Space>
      )}
    </div>
  )
}

function canRemove(root: ConditionExpression, path: number[]): boolean {
  const parent = conditionAt(root, path.slice(0, -1))
  return (parent?.kind === 'all' || parent?.kind === 'any') && parent.conditions.length > 1
}

function conditionAt(root: ConditionExpression, path: number[]): ConditionExpression | null {
  let current = root
  for (const index of path) {
    if (current.kind === 'not') {
      if (index !== 0) return null
      current = current.condition
    } else if (current.kind === 'all' || current.kind === 'any') {
      if (!current.conditions[index]) return null
      current = current.conditions[index]
    } else {
      return null
    }
  }
  return current
}

function ComparisonFields({
  label,
  value,
  choices,
  editable,
  onChange,
}: {
  label: string
  value: Extract<ConditionExpression, { kind: 'compare' }>
  choices: SourceChoice[]
  editable: boolean
  onChange: (condition: ConditionExpression) => void
}) {
  return (
    <Space orientation="vertical">
      <SourceFields
        label={`${label} 左侧`}
        source={value.left}
        choices={choices}
        editable={editable}
        onChange={(left) => onChange({ ...value, left })}
      />
      <Select
        aria-label={`${label} 运算符`}
        disabled={!editable}
        value={value.operator}
        options={CONDITION_OPERATORS.map((operator) => ({
          value: operator,
          label: operatorLabels[operator],
        }))}
        onChange={(operator: ConditionOperator) =>
          onChange(
            conditionNeedsRight(operator)
              ? { ...value, operator, right: value.right ?? { kind: 'literal', value: true } }
              : { kind: 'compare', left: value.left, operator },
          )
        }
      />
      {value.right && (
        <SourceFields
          label={`${label} 右侧`}
          source={value.right}
          choices={choices}
          editable={editable}
          onChange={(right) => onChange({ ...value, right })}
        />
      )}
    </Space>
  )
}
