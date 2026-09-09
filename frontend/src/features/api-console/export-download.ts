import axios from 'axios'

export type ExportFormat = 'har' | 'curl' | 'bruno' | 'excel'

export function exportFilename(disposition: string, format: ExportFormat): string {
  const extended = disposition.match(/filename\*\s*=\s*UTF-8'[^']*'([^;]+)/i)?.[1]
  if (extended) {
    try {
      return safeFilename(decodeURIComponent(extended.trim()))
    } catch (error) {
      if (!(error instanceof URIError)) throw error
      // Invalid encoding falls back to the ordinary filename.
    }
  }
  const filename = disposition.match(/filename\s*=\s*(?:"([^"]+)"|([^;]+))/i)
  const suffix = { har: 'har', curl: 'curl.txt', bruno: 'bruno.json', excel: 'xlsx' }[format]
  return safeFilename(filename?.[1] ?? filename?.[2]?.trim() ?? `flowtest.${suffix}`)
}

function safeFilename(value: string): string {
  return Array.from(value, (character) =>
    character.charCodeAt(0) < 32 || '/\\'.includes(character) ? '_' : character,
  ).join('')
}

export async function exportError(error: unknown): Promise<Error> {
  if (!axios.isAxiosError(error) || !(error.response?.data instanceof Blob)) {
    return error instanceof Error ? error : new Error('导出失败')
  }
  const text = await error.response.data.text()
  let payload: unknown
  try {
    payload = JSON.parse(text)
  } catch (parseError) {
    if (!(parseError instanceof SyntaxError)) throw parseError
    return new Error(text.slice(0, 500) || '导出失败')
  }
  return new Error(envelopeMessage(payload))
}

function envelopeMessage(payload: unknown): string {
  if (typeof payload !== 'object' || payload === null || !('error' in payload))
    return '导出失败：错误响应无效'
  const detail = payload.error
  if (typeof detail !== 'object' || detail === null) return '导出失败：错误响应无效'
  return (
    ['message', 'code', 'trace_id']
      .map((key) => Reflect.get(detail, key))
      .filter((value): value is string => typeof value === 'string')
      .join(' · ') || '导出失败'
  )
}
