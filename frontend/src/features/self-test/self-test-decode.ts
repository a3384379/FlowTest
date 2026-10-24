/** Validate the bounded self-test API at the HTTP boundary; never invent fallback data. */
export type Decoder<T> = (value: unknown) => T
export type Decoded<T> = T extends Decoder<infer V> ? V : never

export class SelfTestContractError extends Error {
  constructor() {
    super('自测响应格式或范围无效，请刷新并核对服务端接口版本。')
    this.name = 'SelfTestContractError'
  }
}
function invalid(): never {
  throw new SelfTestContractError()
}

export function text(value: unknown): string {
  return typeof value === 'string' && value.length <= 4000 ? value : invalid()
}
export function identifier(value: unknown): string {
  const result = text(value)
  return result.length > 0 && result.length <= 200 ? result : invalid()
}
export function uuid(value: unknown): string {
  const result = text(value)
  return /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(result) ? result : invalid()
}
export function bool(value: unknown): boolean {
  return typeof value === 'boolean' ? value : invalid()
}
export function integer(value: unknown): number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 && value <= 1000000
    ? value
    : invalid()
}
export function positive(value: unknown): number {
  const number = integer(value)
  return number > 0 ? number : invalid()
}
export function timestamp(value: unknown): string {
  const result = text(value)
  return /(?:Z|[+-]\d{2}:\d{2})$/.test(result) && Number.isFinite(Date.parse(result))
    ? result
    : invalid()
}
export function nullable<T>(decode: Decoder<T>): Decoder<T | null> {
  return (value) => (value === null ? null : decode(value))
}
export function optional<T>(decode: Decoder<T>): Decoder<T | undefined> {
  return (value) => (value === undefined ? undefined : decode(value))
}
export function choice<const T extends readonly string[]>(values: T): Decoder<T[number]> {
  return (value) =>
    typeof value === 'string' && values.includes(value) ? (value as T[number]) : invalid()
}
export function array<T>(decode: Decoder<T>, maximum = 500): Decoder<T[]> {
  return (value) =>
    Array.isArray(value) && value.length <= maximum ? value.map(decode) : invalid()
}
export function object<const T extends Record<string, Decoder<unknown>>>(
  shape: T,
): Decoder<{ [K in keyof T]: Decoded<T[K]> }> {
  return (value) => {
    if (typeof value !== 'object' || value === null || Array.isArray(value)) return invalid()
    const fields = value as Record<string, unknown>
    if (Object.keys(fields).some((key) => !(key in shape))) return invalid()
    return Object.fromEntries(
      Object.entries(shape).map(([key, decode]) => [key, decode(fields[key])]),
    ) as { [K in keyof T]: Decoded<T[K]> }
  }
}

export function boundedText(minimum: number, maximum: number): Decoder<string> {
  return (value) =>
    typeof value === 'string' && value.length >= minimum && value.length <= maximum
      ? value
      : invalid()
}
export function nonEmptyArray<T>(decode: Decoder<T>, maximum: number): Decoder<T[]> {
  const bounded = array(decode, maximum)
  return (value) => {
    const result = bounded(value)
    return result.length ? result : invalid()
  }
}
