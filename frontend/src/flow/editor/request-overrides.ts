import { toBodyInput } from '../../features/api-console/body-edit'
import type { ApiVersion, WorkflowNode } from '../../lib/api'
import type {
  RequestEditorFields,
  RequestModes,
  WorkflowRequestEditorDraft,
} from './node-edit-session'

type SectionEdit<T> = { mode: 'inherit' } | { mode: 'custom'; value: T }
export type RequestSectionEdits = {
  params: SectionEdit<ApiVersion['query_parameters']>
  headers: SectionEdit<Record<string, string>>
  body: SectionEdit<{ kind: ApiVersion['body_kind']; value: unknown }>
}
export type RequestOverrides = {
  query_parameters?: ApiVersion['query_parameters']
  headers?: Record<string, string>
  body?: { kind: ApiVersion['body_kind']; value: unknown }
}

export function requestOverridesFromFields(
  fields: RequestEditorFields,
  modes: RequestModes,
): RequestOverrides {
  const body = toBodyInput(fields)
  return {
    ...(modes.params === 'custom' ? { query_parameters: fields.query_parameters ?? [] } : {}),
    ...(modes.headers === 'custom' ? { headers: toRecord(fields.headers) } : {}),
    ...(modes.body === 'custom' ? { body: { kind: body.body_kind, value: body.body } } : {}),
  }
}

export function applyRequestEditorDraft(
  node: WorkflowNode,
  draft: WorkflowRequestEditorDraft,
): WorkflowNode {
  assertRequestDraftCanApply(draft)
  const overrides = requestOverridesFromFields(draft.fields, draft.modes)
  return {
    ...node,
    config: {
      ...node.config,
      api_version: draft.apiVersion,
      request_overrides: applyOwnedRequestSections(node.config.request_overrides, {
        params:
          overrides.query_parameters === undefined
            ? { mode: 'inherit' }
            : { mode: 'custom', value: overrides.query_parameters },
        headers:
          overrides.headers === undefined
            ? { mode: 'inherit' }
            : { mode: 'custom', value: overrides.headers },
        body:
          overrides.body === undefined
            ? { mode: 'inherit' }
            : { mode: 'custom', value: overrides.body },
      }),
    },
  }
}

function assertRequestDraftCanApply(draft: WorkflowRequestEditorDraft): void {
  if (Object.values(draft.bulkDrafts ?? {}).some((bulkDraft) => bulkDraft.text !== null)) {
    throw new Error('请先应用或取消批量输入')
  }
  if (
    draft.modes.params === 'custom' &&
    (draft.fields.query_parameters ?? []).some((parameter) => !parameter.name)
  ) {
    throw new Error('参数名不能为空')
  }
  if (
    draft.modes.headers === 'custom' &&
    (draft.fields.headers ?? []).some((header) => !header.name)
  ) {
    throw new Error('Header 名称不能为空')
  }
  if (draft.modes.body === 'custom') toBodyInput(draft.fields)
}
export function applyOwnedRequestSections(
  original: unknown,
  edits: RequestSectionEdits,
): Record<string, unknown> {
  const next = isRecord(original) ? structuredClone(original) : {}
  applySection(next, 'query_parameters', edits.params)
  applySection(next, 'headers', edits.headers)
  applySection(next, 'body', edits.body)
  return next
}
function applySection<T>(target: Record<string, unknown>, key: string, edit: SectionEdit<T>): void {
  if (edit.mode === 'inherit') delete target[key]
  else target[key] = structuredClone(edit.value)
}
export function extraRequestPolicies(original: unknown): string[] {
  if (!isRecord(original)) return []
  return Object.keys(original).filter(
    (key) => !['query_parameters', 'headers', 'body'].includes(key),
  )
}
function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function toRecord(values: Array<{ name: string; value: string }> = []): Record<string, string> {
  return Object.fromEntries(
    values.filter((item) => item.name).map((item) => [item.name, item.value]),
  )
}
