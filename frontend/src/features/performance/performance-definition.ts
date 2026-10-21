import type { PerformanceDefinition, PerformanceStep } from './performance-service'
export type PerformanceStepDraft = Omit<PerformanceStep, 'headers' | 'body'> & {
  header_pairs: Array<{ name: string; value: string }>
  body_json: string
}
export type PerformanceDraft = Omit<PerformanceDefinition, 'steps'> & {
  steps: PerformanceStepDraft[]
}
export type PerformanceForm = { name: string; description: string; definition: PerformanceDraft }
type Path = Array<string | number>
export class PerformanceFieldError extends Error {
  constructor(
    public readonly path: Path,
    message: string,
  ) {
    super(message)
  }
}
function fail(path: Path, message: string): never {
  throw new PerformanceFieldError(path, message)
}
function object(value: unknown, path: Path, keys: string[]): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value))
    fail(path, '请输入完整的配置对象')
  const item = value as Record<string, unknown>,
    extra = Object.keys(item).find((key) => !keys.includes(key))
  if (extra) fail([...path, extra], `配置不支持字段 ${extra}`)
  return item
}
function text(value: unknown, path: Path, min: number, max: number, pattern?: RegExp): string {
  if (typeof value !== 'string' || value.length < min || value.length > max)
    fail(path, `请输入${min}至${max}个字符`)
  if (pattern && !pattern.test(value)) fail(path, '字段格式不符合声明式合同')
  return value
}
function number(value: unknown, path: Path, min: number, max: number, integer = true): number {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < min || value > max)
    fail(path, `请输入${min}至${max}之间的数值`)
  if (integer && !Number.isInteger(value)) fail(path, '请输入整数')
  return value
}
function list(value: unknown, path: Path, min: number, max: number): unknown[] {
  if (!Array.isArray(value) || value.length < min || value.length > max)
    fail(path, `数量应为${min}至${max}项`)
  return value
}
function headers(value: unknown, path: Path): Record<string, string> {
  if (!value || typeof value !== 'object' || Array.isArray(value))
    fail(path, '请求头需为名称和值的对象')
  return Object.fromEntries(
    Object.entries(value).map(([key, raw]) => {
      const name = text(key.trim(), path, 1, 128, /^[^\r\n]+$/)
      return [name, text(raw, [...path, name], 0, 8192, /^[^\r\n]*$/)]
    }),
  )
}
function step(value: unknown, index: number): PerformanceStep {
  const path: Path = ['steps', index],
    item = object(value, path, [
      'name',
      'method',
      'url',
      'headers',
      'body',
      'expected_statuses',
      'pause_seconds',
    ])
  const method = text(item.method, [...path, 'method'], 3, 7)
  if (!['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'].includes(method))
    fail([...path, 'method'], '请选择HTTP方法')
  const url = text(item.url, [...path, 'url'], 1, 2048)
  let target: URL
  try {
    target = new URL(url)
  } catch {
    return fail([...path, 'url'], '请输入有效的 HTTP 或 HTTPS URL')
  }
  if (!['http:', 'https:'].includes(target.protocol))
    fail([...path, 'url'], '请输入有效的 HTTP 或 HTTPS URL')
  const statuses = list(item.expected_statuses, [...path, 'expected_statuses'], 1, 20).map(
    (value) => number(value, [...path, 'expected_statuses'], 100, 599),
  )
  return {
    name: text(item.name, [...path, 'name'], 1, 120),
    method: method as PerformanceStep['method'],
    url,
    headers: headers(item.headers, [...path, 'headers']),
    body: item.body ?? null,
    expected_statuses: [...new Set(statuses)].sort((a, b) => a - b),
    pause_seconds: number(item.pause_seconds, [...path, 'pause_seconds'], 0, 60, false),
  }
}
function threshold(value: unknown, index: number): PerformanceDefinition['thresholds'][number] {
  const path: Path = ['thresholds', index],
    item = object(value, path, [
      'metric',
      'aggregation',
      'operator',
      'value',
      'abort_on_fail',
      'delay_abort_seconds',
    ])
  const metric = text(
    item.metric,
    [...path, 'metric'],
    1,
    160,
    /^[a-z][a-z0-9_]*(?:\{[a-zA-Z0-9_=,:.-]+\})?$/,
  )
  const aggregation = text(
    item.aggregation,
    [...path, 'aggregation'],
    1,
    Number.MAX_SAFE_INTEGER,
    /^(?:avg|med|min|max|rate|count|p\((?:[1-9]\d?|100)(?:\.\d+)?\))$/,
  )
  if (!['<', '<=', '>', '>='].includes(String(item.operator)))
    fail([...path, 'operator'], '请选择比较符')
  if (typeof item.abort_on_fail !== 'boolean')
    fail([...path, 'abort_on_fail'], '请选择失败时是否中止')
  const delay = number(item.delay_abort_seconds, [...path, 'delay_abort_seconds'], 0, 3600)
  if (!item.abort_on_fail && delay)
    fail([...path, 'delay_abort_seconds'], '延迟中止需要先开启失败中止')
  return {
    metric,
    aggregation,
    operator: item.operator as '<' | '<=' | '>' | '>=',
    value: number(item.value, [...path, 'value'], 0, 1_000_000_000, false),
    abort_on_fail: item.abort_on_fail,
    delay_abort_seconds: delay,
  }
}
function load(
  item: Record<string, unknown>,
): Pick<PerformanceDefinition, 'executor' | 'vus' | 'duration_seconds' | 'start_vus' | 'stages'> {
  if (item.executor === 'constant_vus') {
    if (item.start_vus !== null || !Array.isArray(item.stages) || item.stages.length)
      fail(['executor'], '固定VU不能同时包含阶梯配置')
    return {
      executor: 'constant_vus',
      vus: number(item.vus, ['vus'], 1, 1000),
      duration_seconds: number(item.duration_seconds, ['duration_seconds'], 1, 3600),
      start_vus: null,
      stages: [],
    }
  }
  if (item.executor !== 'ramping_vus') fail(['executor'], '请选择固定VU或阶梯模型')
  if (item.vus !== null || item.duration_seconds !== null)
    fail(['executor'], '阶梯模型不能同时包含固定VU配置')
  const stages = list(item.stages, ['stages'], 1, 20).map((value, index) => {
    const path: Path = ['stages', index],
      stage = object(value, path, ['duration_seconds', 'target_vus'])
    return {
      duration_seconds: number(stage.duration_seconds, [...path, 'duration_seconds'], 1, 3600),
      target_vus: number(stage.target_vus, [...path, 'target_vus'], 0, 1000),
    }
  })
  if (stages.reduce((sum, stage) => sum + stage.duration_seconds, 0) > 3600)
    fail(['stages'], '各阶段总时长不能超过3600秒')
  return {
    executor: 'ramping_vus',
    vus: null,
    duration_seconds: null,
    start_vus: number(item.start_vus, ['start_vus'], 0, 1000),
    stages,
  }
}
export function validatePerformanceDefinition(value: unknown): PerformanceDefinition {
  const item = object(
    value,
    [],
    [
      'executor',
      'steps',
      'thresholds',
      'vus',
      'duration_seconds',
      'start_vus',
      'stages',
      'graceful_stop_seconds',
    ],
  )
  const steps = list(item.steps, ['steps'], 1, 20).map(step),
    thresholds = list(item.thresholds, ['thresholds'], 1, 30).map(threshold)
  if (new Set(steps.map((item) => item.name)).size !== steps.length)
    fail(['steps'], '步骤名称不能重复')
  const keys = thresholds.map(
    (item) => `${item.metric}:${item.aggregation}${item.operator}${item.value}`,
  )
  if (new Set(keys).size !== keys.length) fail(['thresholds'], '相同指标和表达式的阈值不能重复')
  return {
    ...load(item),
    steps,
    thresholds,
    graceful_stop_seconds: number(item.graceful_stop_seconds, ['graceful_stop_seconds'], 0, 300),
  }
}
export function parsePerformanceDefinition(value: string): PerformanceDefinition {
  let parsed: unknown
  try {
    parsed = JSON.parse(value)
  } catch {
    throw new PerformanceFieldError([], '请输入有效的声明式JSON配置')
  }
  return validatePerformanceDefinition(parsed)
}
export function defaultPerformanceStep(name = '接口请求'): PerformanceStepDraft {
  return {
    name,
    method: 'GET',
    url: '',
    header_pairs: [],
    body_json: 'null',
    expected_statuses: [200],
    pause_seconds: 0,
  }
}
export function defaultPerformanceDraft(): PerformanceDraft {
  return {
    executor: 'constant_vus',
    steps: [defaultPerformanceStep()],
    thresholds: [
      {
        metric: 'http_req_duration',
        aggregation: 'p(95)',
        operator: '<',
        value: 500,
        abort_on_fail: false,
        delay_abort_seconds: 0,
      },
      {
        metric: 'http_req_failed',
        aggregation: 'rate',
        operator: '<=',
        value: 0.01,
        abort_on_fail: false,
        delay_abort_seconds: 0,
      },
    ],
    vus: 5,
    duration_seconds: 30,
    start_vus: 0,
    stages: [{ duration_seconds: 60, target_vus: 20 }],
    graceful_stop_seconds: 30,
  }
}
export function performanceDraft(definition: PerformanceDefinition): PerformanceDraft {
  return {
    ...structuredClone(definition),
    vus: definition.vus ?? 5,
    duration_seconds: definition.duration_seconds ?? 30,
    start_vus: definition.start_vus ?? 0,
    stages: definition.stages.length
      ? structuredClone(definition.stages)
      : [{ duration_seconds: 60, target_vus: 20 }],
    steps: definition.steps.map(({ headers, body, ...step }) => ({
      ...step,
      header_pairs: Object.entries(headers).map(([name, value]) => ({ name, value })),
      body_json: JSON.stringify(body, null, 2),
    })),
  }
}
export function draftDefinition(draft: PerformanceDraft): PerformanceDefinition {
  const steps = draft.steps.map(({ header_pairs, body_json, ...step }, index) => {
    header_pairs.forEach((pair, pairIndex) => {
      const path: Path = ['steps', index, 'header_pairs', pairIndex]
      text(pair.name.trim(), [...path, 'name'], 1, 128, /^[^\r\n]+$/)
      text(pair.value, [...path, 'value'], 0, 8192, /^[^\r\n]*$/)
    })
    const names = header_pairs.map((pair) => pair.name.trim())
    if (new Set(names).size !== names.length)
      fail(['steps', index, 'header_pairs'], '请求头名称不能重复')
    let body: unknown
    try {
      body = JSON.parse(body_json)
    } catch {
      return fail(['steps', index, 'body_json'], '请求体需为有效JSON；字符串请使用双引号')
    }
    return {
      ...step,
      headers: Object.fromEntries(header_pairs.map((pair) => [pair.name, pair.value])),
      body,
    }
  })
  const constant = draft.executor === 'constant_vus'
  return {
    ...draft,
    steps,
    vus: constant ? draft.vus : null,
    duration_seconds: constant ? draft.duration_seconds : null,
    start_vus: constant ? null : draft.start_vus,
    stages: constant ? [] : draft.stages,
  }
}
export function performanceThresholdUnit(metric: string, aggregation: string): string {
  if (
    [
      'duration',
      'waiting',
      'blocked',
      'connecting',
      'sending',
      'receiving',
      'tls_handshaking',
    ].some((part) => metric.includes(part))
  )
    return '毫秒'
  if (aggregation === 'count') return '次数'
  if (metric === 'http_reqs' && aggregation === 'rate') return '次/秒'
  if (aggregation === 'rate') return '比例（1=100%）'
  return '指标原生单位'
}
