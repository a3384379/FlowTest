export type EnvironmentMapValue =
  | { format: 'table'; rows: Array<{ name: string; value: string }> }
  | { format: 'json'; text: string }

export function mapValue(values: Record<string, string>): EnvironmentMapValue {
  return { format: 'table', rows: Object.entries(values).map(([name, value]) => ({ name, value })) }
}

export function parseEnvironmentMap(
  value: EnvironmentMapValue,
  kind: 'variables' | 'headers',
): Record<string, string> {
  const label = kind === 'variables' ? '变量' : '请求头'
  const entries = mapEntries(value, label)
  const seen = new Set<string>()
  for (const [name] of entries) {
    if (!name.trim()) throw new Error(`${label}名称不能为空`)
    if (kind === 'variables' && !/^[A-Za-z_][A-Za-z0-9_.-]{0,159}$/.test(name))
      throw new Error('变量名称须以字母或下划线开头，只能包含字母、数字、下划线、点和短横线')
    if (kind === 'headers' && !/^[!#$%&'*+.^_`|~0-9A-Za-z-]+$/.test(name))
      throw new Error('请求头名称格式不正确')
    const key = kind === 'headers' ? name.toLowerCase() : name
    if (seen.has(key)) throw new Error(`${label}名称不能重复：${name}`)
    seen.add(key)
  }
  return Object.fromEntries(entries)
}

function mapEntries(value: EnvironmentMapValue, label: string): Array<[string, string]> {
  if (value.format === 'table')
    return value.rows.filter((row) => row.name || row.value).map((row) => [row.name, row.value])
  let parsed: unknown
  try {
    parsed = JSON.parse(value.text || '{}')
  } catch {
    throw new Error(`${label} JSON 格式不正确`)
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed))
    throw new Error(`${label}必须是 JSON 对象`)
  const entries = Object.entries(parsed)
  if (entries.some(([, item]) => typeof item !== 'string'))
    throw new Error(`${label}的值必须是字符串`)
  return entries as Array<[string, string]>
}
