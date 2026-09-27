import { parseCondition, type ConditionExpression } from './control-condition'
import { parseValueSource, type ValueSource } from './control-source-browser'

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null
}

export function switchToRules(
  configuration: Record<string, unknown>,
): Record<string, unknown> | null {
  if (configuration.mode !== 'value' || !Array.isArray(configuration.branches)) return null
  const value = parseValueSource(configuration.value)
  if (!value) return null
  const branches = configuration.branches.map((raw) => {
    const branch = asRecord(raw)
    const match = parseValueSource(branch?.match)
    if (!branch || !match) return null
    return {
      ...branch,
      match: null,
      condition: { kind: 'compare', left: value, operator: 'equals', right: match },
    }
  })
  if (branches.some((branch) => !branch)) return null
  return { ...configuration, mode: 'rules', value: null, branches }
}

export function switchToValue(
  configuration: Record<string, unknown>,
): Record<string, unknown> | null {
  if (configuration.mode !== 'rules' || !Array.isArray(configuration.branches)) return null
  const parsed = configuration.branches.map((raw) => {
    const branch = asRecord(raw)
    const condition = parseCondition(branch?.condition)
    if (!branch || !isEquality(condition)) return null
    return { branch, condition }
  })
  const first = parsed[0]
  if (
    !first ||
    parsed.some((item) => !item || !sameSource(item.condition.left, first.condition.left))
  )
    return null
  return {
    ...configuration,
    mode: 'value',
    value: first.condition.left,
    branches: parsed.map((item) => ({
      ...item!.branch,
      condition: null,
      match: item!.condition.right,
    })),
  }
}

function isEquality(
  condition: ConditionExpression | null,
): condition is Extract<ConditionExpression, { kind: 'compare' }> & { right: ValueSource } {
  return condition?.kind === 'compare' && condition.operator === 'equals' && !!condition.right
}

function sameSource(left: ValueSource, right: ValueSource): boolean {
  return JSON.stringify(left) === JSON.stringify(right)
}
