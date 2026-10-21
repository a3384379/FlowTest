import type {
  OracleSpec,
  ScenarioCandidate,
  TestEngineeringProposal,
} from './test-engineering-service'

export function materializationBlocker(proposal: TestEngineeringProposal): string | null {
  if (proposal.design.review_requirements.includes('constraint_unsatisfiable'))
    return '设计约束不可满足，请补充来源并重新生成设计。'
  if (!proposal.scenario_ids.length) return '审核记录未提供生成场景范围。'
  const selected = proposal.design.scenarios.filter((value) =>
    proposal.scenario_ids.includes(value.id),
  )
  if (selected.length !== new Set(proposal.scenario_ids).size)
    return '部分已审核场景未提供，暂不能生成资产。'
  const unavailable = selected.find((value) => scenarioReason(value, proposal.design.oracles))
  return unavailable
    ? `${unavailable.title}：${scenarioReason(unavailable, proposal.design.oracles)}`
    : null
}

export function scenarioReason(scenario: ScenarioCandidate, oracles: OracleSpec[]): string | null {
  if (scenario.requires_review) return '证据冲突、敏感测试数据或前置条件待审核'
  if (!scenario.deterministic || scenario.confidence !== 1)
    return '输入或预期确定性不足，需要人工复核'
  if (scenario.mutations.some((value) => value.location === 'path' && value.operation === 'omit'))
    return '必填路径参数缺失，无法表示为真实 HTTP 请求'
  const linked = oracles.filter((value) => value.applies_to.includes(scenario.id))
  if (linked.filter(executableStatus).length !== 1) return '缺少唯一的确定性状态码预期'
  if (linked.some((value) => !supportedOracle(value)))
    return '关联预期包含待复核或尚不支持的判断方式'
  return null
}

function executableStatus(value: OracleSpec): boolean {
  return (
    value.kind === 'status' &&
    value.operator === 'equals' &&
    Number.isInteger(value.expected) &&
    supportedOracle(value)
  )
}

function supportedOracle(value: OracleSpec): boolean {
  if (!value.deterministic || value.requires_review || value.confidence !== 1) return false
  if (!['status', 'schema', 'json_path', 'expression'].includes(value.kind)) return false
  return (
    !['json_path', 'expression'].includes(value.kind) ||
    ['equals', 'not_equals', 'contains', 'exists', 'matches'].includes(value.operator)
  )
}

export function scenarioKind(value: string): string {
  const names: Record<string, string> = {
    happy_path: '正常请求',
    auth_missing: '缺失认证',
    required_omitted: '缺失必填值',
    required_null: '必填值为空',
    optional_omitted: '省略可选值',
    invalid_type: '错误类型',
    enum_value: '枚举有效值',
    enum_invalid: '枚举无效值',
    number_below_min: '低于最小值',
    number_at_min: '最小边界',
    number_above_min: '高于最小值',
    number_below_max: '低于最大值',
    number_at_max: '最大边界',
    number_above_max: '超过最大值',
    string_at_max_length: '最大长度',
    string_above_max_length: '超过最大长度',
  }
  return names[value] ?? `其他场景（${value}）`
}
