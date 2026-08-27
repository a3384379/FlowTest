import type { ApiVersion } from '../../lib/api'
import type { KeyValueField } from './bulk-edit'

export type BodyMode = 'none' | 'multipart' | 'form' | 'raw'
export type RawBodyType = 'json' | 'text' | 'xml' | 'html'
export type MultipartField = {
  name: string
  kind: 'text' | 'file'
  value: string
}

export type BodyEditorFields = {
  body_mode: BodyMode
  body_raw_type: RawBodyType
  body_text: string
  body_form: KeyValueField[]
  body_multipart: MultipartField[]
}

export function toBodyFields(
  version: Pick<ApiVersion, 'body_kind' | 'body' | 'headers'>,
): BodyEditorFields {
  return {
    body_mode: bodyMode(version.body_kind),
    body_raw_type: rawBodyType(version.body_kind, version.headers),
    body_text: bodyText(version.body_kind, version.body),
    body_form: version.body_kind === 'form' ? recordFields(version.body) : [],
    body_multipart: version.body_kind === 'multipart' ? multipartFields(version.body) : [],
  }
}

export function toBodyInput(fields: BodyEditorFields): Pick<ApiVersion, 'body_kind' | 'body'> {
  if (fields.body_mode === 'none') return { body_kind: 'none', body: null }
  if (fields.body_mode === 'form') {
    return { body_kind: 'form', body: toRecord(fields.body_form ?? []) }
  }
  if (fields.body_mode === 'multipart') {
    const multipartFields = fields.body_multipart ?? []
    return {
      body_kind: 'multipart',
      body: {
        fields: toRecord(
          multipartFields
            .filter((field) => field.kind === 'text')
            .map(({ name, value }) => ({ name, value })),
        ),
        files: multipartFields
          .filter((field) => field.kind === 'file' && field.name && field.value)
          .map((field) => ({ field: field.name, artifact_id: field.value })),
      },
    }
  }
  if (fields.body_raw_type === 'json') {
    const bodyText = fields.body_text ?? ''
    return {
      body_kind: 'json',
      body: bodyText.trim() ? JSON.parse(bodyText) : null,
    }
  }
  return { body_kind: 'raw', body: fields.body_text ?? '' }
}

export function recommendedContentType(mode: BodyMode, rawType: RawBodyType): string | null {
  if (mode === 'form') return 'application/x-www-form-urlencoded'
  if (mode !== 'raw') return null
  const types: Record<RawBodyType, string> = {
    json: 'application/json',
    text: 'text/plain',
    xml: 'application/xml',
    html: 'text/html',
  }
  return types[rawType]
}

export function updateAutoContentType(
  headers: KeyValueField[],
  previousAutoValue: string | null,
  nextValue: string | null,
): { headers: KeyValueField[]; autoValue: string | null } {
  const index = headers.findIndex((header) => header.name.trim().toLowerCase() === 'content-type')
  if (index < 0) {
    return nextValue
      ? { headers: [...headers, { name: 'Content-Type', value: nextValue }], autoValue: nextValue }
      : { headers, autoValue: null }
  }
  if (!previousAutoValue || headers[index].value !== previousAutoValue) {
    return { headers, autoValue: null }
  }
  if (!nextValue) {
    return { headers: headers.filter((_, headerIndex) => headerIndex !== index), autoValue: null }
  }
  return {
    headers: headers.map((header, headerIndex) =>
      headerIndex === index ? { ...header, value: nextValue } : header,
    ),
    autoValue: nextValue,
  }
}

function bodyMode(kind: ApiVersion['body_kind']): BodyMode {
  return kind === 'json' || kind === 'raw' ? 'raw' : kind
}

function rawBodyType(kind: ApiVersion['body_kind'], headers: Record<string, string>): RawBodyType {
  if (kind === 'json') return 'json'
  if (kind !== 'raw') return 'json'
  const contentType = Object.entries(headers).find(
    ([name]) => name.toLowerCase() === 'content-type',
  )?.[1]
  if (contentType?.toLowerCase().includes('xml')) return 'xml'
  if (contentType?.toLowerCase().includes('html')) return 'html'
  return 'text'
}

function bodyText(kind: ApiVersion['body_kind'], body: unknown): string {
  if (kind === 'json') return body === null ? '' : JSON.stringify(body, null, 2)
  if (kind !== 'raw') return ''
  return typeof body === 'string' ? body : String(body ?? '')
}

function recordFields(value: unknown): KeyValueField[] {
  if (!isRecord(value)) return []
  return Object.entries(value).map(([name, fieldValue]) => ({
    name,
    value: typeof fieldValue === 'string' ? fieldValue : String(fieldValue ?? ''),
  }))
}

function multipartFields(value: unknown): MultipartField[] {
  if (!isRecord(value)) return []
  const fields = recordFields(value.fields).map((field) => ({ ...field, kind: 'text' as const }))
  const files = Array.isArray(value.files)
    ? value.files.flatMap((file) => {
        if (!isRecord(file) || typeof file.field !== 'string') return []
        if (typeof file.artifact_id !== 'string') return []
        return [{ name: file.field, kind: 'file' as const, value: file.artifact_id }]
      })
    : []
  return [...fields, ...files]
}

function toRecord(fields: KeyValueField[]): Record<string, string> {
  return Object.fromEntries(
    fields.filter((field) => field.name).map(({ name, value }) => [name, value]),
  )
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}
