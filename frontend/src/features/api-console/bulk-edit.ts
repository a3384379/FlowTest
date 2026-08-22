export type KeyValueField = { name: string; value: string }
export type ParameterField = KeyValueField & { enabled: boolean }
export type BulkParseResult<T> = { values: T[]; errors: string[] }

export const REDACTED_BULK_VALUE = '******'

const secretReferencePattern = /\{\{\s*secret\.[A-Za-z_][A-Za-z0-9_.-]*\s*\}\}/
const sensitiveNamePattern =
  /(^|[-_.])(password|passwd|authorization|cookie|token|secret|api[-_]?key|apikey)([-_.]|$)/i

export function serializeBulkParameters(parameters: ParameterField[]): string {
  return parameters
    .map((parameter) => {
      const prefix = parameter.enabled ? '' : '# '
      return `${prefix}${parameter.name}: ${parameter.value}`
    })
    .join('\n')
}

export function parseBulkParameters(text: string): BulkParseResult<ParameterField> {
  const values: ParameterField[] = []
  const errors: string[] = []
  for (const line of meaningfulLines(text)) {
    const enabled = !line.content.startsWith('#')
    const content = enabled ? line.content : line.content.slice(1).trimStart()
    const parsed = parseKeyValue(content, line.number)
    if (typeof parsed === 'string') {
      errors.push(parsed)
      continue
    }
    if (parsed.name.length > 160) {
      errors.push(lineError(line.number, '参数名不能超过 160 位'))
      continue
    }
    if (parsed.value.length > 65_536) {
      errors.push(lineError(line.number, '参数值不能超过 65536 位'))
      continue
    }
    values.push({ enabled, ...parsed })
  }
  if (values.length > 200) errors.push('参数最多支持 200 行')
  return { values, errors }
}

export function serializeBulkHeaders(headers: KeyValueField[]): string {
  return headers
    .map((header) => {
      const value = shouldMaskHeader(header) ? REDACTED_BULK_VALUE : header.value
      return `${header.name}: ${value}`
    })
    .join('\n')
}

export function serializeBulkKeyValues(values: KeyValueField[]): string {
  return values.map((item) => `${item.name}: ${item.value}`).join('\n')
}

export function parseBulkKeyValues(text: string): BulkParseResult<KeyValueField> {
  const values: KeyValueField[] = []
  const errors: string[] = []
  const seen = new Map<string, number>()
  for (const line of meaningfulLines(text)) {
    if (line.content.startsWith('#')) continue
    const parsed = parseKeyValue(line.content, line.number)
    if (typeof parsed === 'string') {
      errors.push(parsed)
      continue
    }
    const previousLine = seen.get(parsed.name)
    if (previousLine !== undefined) {
      errors.push(lineError(line.number, `名称与第 ${previousLine} 行重复`))
      continue
    }
    seen.set(parsed.name, line.number)
    values.push(parsed)
  }
  return { values, errors }
}

export function parseBulkHeaders(
  text: string,
  currentHeaders: KeyValueField[],
): BulkParseResult<KeyValueField> {
  const values: KeyValueField[] = []
  const errors: string[] = []
  const existing = new Map(
    currentHeaders.map((header) => [normalizeName(header.name), header.value]),
  )
  const seen = new Map<string, number>()
  for (const line of meaningfulLines(text)) {
    if (line.content.startsWith('#')) continue
    const parsed = parseKeyValue(line.content, line.number)
    if (typeof parsed === 'string') {
      errors.push(parsed)
      continue
    }
    const normalizedName = normalizeName(parsed.name)
    const previousLine = seen.get(normalizedName)
    if (previousLine !== undefined) {
      errors.push(lineError(line.number, `Header 名称与第 ${previousLine} 行重复`))
      continue
    }
    seen.set(normalizedName, line.number)
    const restored = restoreHeaderValue(parsed, existing, line.number)
    if (typeof restored === 'string') {
      errors.push(restored)
      continue
    }
    values.push(restored)
  }
  return { values, errors }
}

function meaningfulLines(text: string): Array<{ number: number; content: string }> {
  return text
    .split(/\r?\n/)
    .map((content, index) => ({ number: index + 1, content: content.trim() }))
    .filter((line) => line.content.length > 0)
}

function parseKeyValue(content: string, lineNumber: number): KeyValueField | string {
  const separator = content.indexOf(':')
  if (separator < 0) return lineError(lineNumber, '请使用“名称: 值”格式')
  const name = content.slice(0, separator).trim()
  if (!name) return lineError(lineNumber, '名称不能为空')
  return { name, value: content.slice(separator + 1).trim() }
}

function restoreHeaderValue(
  header: KeyValueField,
  existing: Map<string, string>,
  lineNumber: number,
): KeyValueField | string {
  if (!isSensitiveName(header.name)) return header
  if (header.value === REDACTED_BULK_VALUE) {
    const currentValue = existing.get(normalizeName(header.name))
    return currentValue === undefined
      ? lineError(lineNumber, '脱敏占位符没有可保留的原值')
      : { ...header, value: currentValue }
  }
  if (header.value && !secretReferencePattern.test(header.value)) {
    return lineError(lineNumber, '敏感 Header 请使用 {{secret.NAME}} 引用')
  }
  return header
}

function shouldMaskHeader(header: KeyValueField): boolean {
  return isSensitiveName(header.name) && !secretReferencePattern.test(header.value)
}

function isSensitiveName(name: string): boolean {
  return sensitiveNamePattern.test(name.trim())
}

function normalizeName(name: string): string {
  return name.trim().toLowerCase()
}

function lineError(lineNumber: number, message: string): string {
  return `第 ${lineNumber} 行：${message}`
}
