import type { MockRoute } from '../../lib/api'
import type { MockRouteInput } from './data-source-service'

export type StringMapDraft = {
  mode: 'rows' | 'json'
  rows: Array<{ name: string; value: string }>
  json: string
}

export type MockRouteFields = {
  name: string
  method: MockRouteInput['method']
  path_pattern: string
  scenario: string
  query_conditions: StringMapDraft
  header_conditions: StringMapDraft
  response_headers: StringMapDraft
  body_mode: 'json' | 'text'
  response_body: string
  response_status: number
  delay_ms: number
  priority: number
  is_enabled: boolean
}

export function stringMapDraft(value: Record<string, string> = {}): StringMapDraft {
  return {
    mode: 'rows',
    rows: Object.entries(value).map(([name, entry]) => ({ name, value: entry })),
    json: JSON.stringify(value, null, 2),
  }
}

export function readStringMap(value: StringMapDraft, header = false): Record<string, string> {
  const entries = value.mode === 'json' ? jsonEntries(value.json) : value.rows
  const names = new Set<string>()
  for (const row of entries) {
    if (!row.name) throw new Error('每行必须填写键名')
    const identity = header ? row.name.toLowerCase() : row.name
    if (names.has(identity)) throw new Error('键名不能重复；Header 名称不区分大小写')
    names.add(identity)
  }
  return Object.fromEntries(entries.map(({ name, value: entry }) => [name, entry]))
}

function jsonEntries(text: string): StringMapDraft['rows'] {
  let value: unknown
  try {
    value = JSON.parse(text)
  } catch {
    throw new Error('请输入有效 JSON 对象')
  }
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('必须是 JSON 对象，不能是数组、数字或 null')
  }
  return Object.entries(value).map(([name, entry]) => {
    if (typeof entry !== 'string') throw new Error(`键“${name}”的值必须是字符串`)
    return { name, value: entry }
  })
}

export function mockRouteFields(route: MockRoute | null): MockRouteFields {
  const base: MockRouteInput = route ?? {
    name: '',
    method: 'GET',
    path_pattern: '',
    scenario: null,
    query_conditions: {},
    header_conditions: {},
    response_headers: {},
    response_body: {},
    response_status: 200,
    delay_ms: 0,
    priority: 0,
    is_enabled: true,
  }
  return {
    ...base,
    scenario: base.scenario ?? '',
    query_conditions: stringMapDraft(base.query_conditions),
    header_conditions: stringMapDraft(base.header_conditions),
    response_headers: stringMapDraft(base.response_headers),
    body_mode: typeof base.response_body === 'string' ? 'text' : 'json',
    response_body:
      typeof base.response_body === 'string'
        ? base.response_body
        : JSON.stringify(base.response_body, null, 2),
  }
}

export function mockRouteInput(values: MockRouteFields): MockRouteInput {
  return {
    name: values.name,
    method: values.method,
    path_pattern: values.path_pattern,
    scenario: values.scenario || null,
    query_conditions: readStringMap(values.query_conditions),
    header_conditions: readStringMap(values.header_conditions, true),
    response_headers: readStringMap(values.response_headers, true),
    response_body:
      values.body_mode === 'text' ? values.response_body : JSON.parse(values.response_body),
    response_status: values.response_status,
    delay_ms: values.delay_ms,
    priority: values.priority,
    is_enabled: values.is_enabled,
  }
}

export const mockHttpMethods = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE'].map((value) => ({
  value,
  label: value,
}))

export function mapRule(header: boolean) {
  return {
    validator: async (_: unknown, value: StringMapDraft) => {
      readStringMap(value, header)
    },
  }
}

export const jsonValueRule = {
  validator: async (_: unknown, value: string) => {
    try {
      JSON.parse(value)
    } catch {
      throw new Error('请输入有效 JSON')
    }
  },
}
