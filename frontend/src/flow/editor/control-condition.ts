import { parseValueSource, type ValueSource } from './control-source-browser'

export const CONDITION_OPERATORS = [
  'equals',
  'not_equals',
  'gt',
  'gte',
  'lt',
  'lte',
  'contains',
  'in',
  'exists',
  'not_exists',
  'is_null',
  'not_null',
  'is_empty',
  'not_empty',
  'length_equals',
  'length_gt',
  'length_lt',
] as const

export type ConditionOperator = (typeof CONDITION_OPERATORS)[number]
export type ConditionExpression =
  | { kind: 'compare'; left: ValueSource; operator: ConditionOperator; right?: ValueSource }
  | { kind: 'all' | 'any'; conditions: ConditionExpression[] }
  | { kind: 'not'; condition: ConditionExpression }

const unaryOperators = new Set<ConditionOperator>([
  'exists',
  'not_exists',
  'is_null',
  'not_null',
  'is_empty',
  'not_empty',
])

export function conditionNeedsRight(operator: ConditionOperator): boolean {
  return !unaryOperators.has(operator)
}

export function defaultCondition(
  kind: ConditionExpression['kind'] = 'compare',
): ConditionExpression {
  const compare: ConditionExpression = {
    kind: 'compare',
    left: { kind: 'literal', value: true },
    operator: 'equals',
    right: { kind: 'literal', value: true },
  }
  if (kind === 'not') return { kind, condition: compare }
  if (kind === 'all' || kind === 'any') return { kind, conditions: [compare] }
  return compare
}

export function parseCondition(value: unknown): ConditionExpression | null {
  return parseConditionNode(value, 1, { comparisons: 0 })
}

type ParseBudget = { comparisons: number }

function parseConditionNode(
  value: unknown,
  depth: number,
  budget: ParseBudget,
): ConditionExpression | null {
  const record = asRecord(value)
  if (!record || depth > 8 || !onlyConditionKeys(record)) return null
  if (record.kind === 'compare') {
    budget.comparisons += 1
    return budget.comparisons <= 100 ? parseComparison(record) : null
  }
  if (record.kind === 'all' || record.kind === 'any') return parseGroup(record, depth, budget)
  if (record.kind === 'not') return parseNot(record, depth, budget)
  return null
}

function parseComparison(value: Record<string, unknown>): ConditionExpression | null {
  const left = parseValueSource(value.left)
  const operator = value.operator
  if (
    !left ||
    !CONDITION_OPERATORS.some((item) => item === operator) ||
    value.conditions != null ||
    value.condition != null
  )
    return null
  const typedOperator = operator as ConditionOperator
  if (!conditionNeedsRight(typedOperator)) {
    return value.right == null ? { kind: 'compare', left, operator: typedOperator } : null
  }
  const right = parseValueSource(value.right)
  return right ? { kind: 'compare', left, operator: typedOperator, right } : null
}

function parseGroup(
  value: Record<string, unknown>,
  depth: number,
  budget: ParseBudget,
): ConditionExpression | null {
  if (
    !Array.isArray(value.conditions) ||
    !value.conditions.length ||
    value.conditions.length > 100 ||
    value.left != null ||
    value.right != null ||
    value.operator != null ||
    value.condition != null
  )
    return null
  const conditions: ConditionExpression[] = []
  for (const raw of value.conditions) {
    const condition = parseConditionNode(raw, depth + 1, budget)
    if (!condition) return null
    conditions.push(condition)
  }
  return { kind: value.kind as 'all' | 'any', conditions }
}

function parseNot(
  value: Record<string, unknown>,
  depth: number,
  budget: ParseBudget,
): ConditionExpression | null {
  if (
    value.left != null ||
    value.right != null ||
    value.operator != null ||
    value.conditions != null
  )
    return null
  const condition = parseConditionNode(value.condition, depth + 1, budget)
  return condition ? { kind: 'not', condition } : null
}

function onlyConditionKeys(value: Record<string, unknown>): boolean {
  return Object.keys(value).every((key) =>
    ['kind', 'left', 'right', 'operator', 'conditions', 'condition'].includes(key),
  )
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null
}

export function countComparisons(condition: ConditionExpression): number {
  if (condition.kind === 'compare') return 1
  if (condition.kind === 'not') return countComparisons(condition.condition)
  return condition.conditions.reduce((total, item) => total + countComparisons(item), 0)
}

export function replaceCondition(
  root: ConditionExpression,
  path: number[],
  replacement: ConditionExpression,
): ConditionExpression {
  return editCondition(root, path, () => replacement)
}

export function addCondition(root: ConditionExpression, path: number[]): ConditionExpression {
  if (countComparisons(root) >= 100) return root
  return editCondition(root, path, (item) =>
    item.kind === 'all' || item.kind === 'any'
      ? { ...item, conditions: [...item.conditions, defaultCondition()] }
      : item,
  )
}

export function removeCondition(root: ConditionExpression, path: number[]): ConditionExpression {
  const index = path.at(-1)
  if (index === undefined) return root
  return editCondition(root, path.slice(0, -1), (item) =>
    (item.kind === 'all' || item.kind === 'any') && item.conditions.length > 1
      ? { ...item, conditions: item.conditions.filter((_, position) => position !== index) }
      : item,
  )
}

function editCondition(
  item: ConditionExpression,
  path: number[],
  edit: (condition: ConditionExpression) => ConditionExpression,
): ConditionExpression {
  if (!path.length) return edit(item)
  const [index, ...rest] = path
  if (item.kind === 'not') {
    return index === 0 ? { ...item, condition: editCondition(item.condition, rest, edit) } : item
  }
  if (item.kind !== 'all' && item.kind !== 'any') return item
  if (index < 0 || index >= item.conditions.length) return item
  return {
    ...item,
    conditions: item.conditions.map((child, position) =>
      position === index ? editCondition(child, rest, edit) : child,
    ),
  }
}
