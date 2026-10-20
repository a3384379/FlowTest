import axios from 'axios'

export type ProtocolErrorPath = Array<string | number>
export function protocolErrorPaths(error: unknown): ProtocolErrorPath[] {
  if (!axios.isAxiosError(error)) return []
  const payload: unknown = error.response?.data
  if (!record(payload) || !record(payload.error) || !record(payload.error.details)) return []
  const output = payload.error.details.output
  if (!record(output) || !record(output.body) || !Array.isArray(output.body.errors)) return []
  return output.body.errors.slice(0, 20).flatMap((item: unknown) => {
    if (
      !record(item) ||
      !Array.isArray(item.path) ||
      item.path.length === 0 ||
      item.path.length > 20
    )
      return []
    const path: unknown[] = item.path
    if (!path.every(validSegment)) return []
    return [path as ProtocolErrorPath]
  })
}
function validSegment(value: unknown): boolean {
  return typeof value === 'string'
    ? value.length > 0 && value.length <= 512
    : typeof value === 'number' && Number.isSafeInteger(value) && value >= 0
}
function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}
