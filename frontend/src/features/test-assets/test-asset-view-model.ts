import type { Folder, TestCase, TestSuite } from '../../lib/api'
import type { TestCaseDraftInput, TestSuiteDraftInput } from './test-asset-service'

export type CaseFormValues = {
  name: string
  description: string
  folderId?: string
  tags: string[]
  workflowId: string
  workflowVersion?: number | null
  environmentId: string
  runtimeVariables?: KeyValueEntry[]
  runtimeHeaders?: KeyValueEntry[]
}

export type KeyValueEntry = { name: string; value: string }

export type SuiteFormValues = {
  name: string
  description: string
  folderId?: string
  tags: string[]
  caseIds: string[]
  memberVersions?: Record<string, number | null>
}

export function entries(value: Record<string, string>): KeyValueEntry[] {
  return Object.entries(value).map(([name, item]) => ({ name, value: item }))
}

export function validateEntries(values: KeyValueEntry[], headers: boolean): string | undefined {
  const seen = new Set<string>()
  for (const item of values) {
    const name = item.name ?? ''
    if (!validEntryName(name, headers)) return invalidNameMessage(headers)
    if (headers && /[\r\n]/.test(item.value ?? '')) return 'Header 值不能包含换行'
    const key = headers ? name.toLowerCase() : name
    if (seen.has(key)) return duplicateNameMessage(headers)
    seen.add(key)
  }
}

function validEntryName(name: string, headers: boolean): boolean {
  return headers
    ? /^[!#$%&'*+.^_`|~0-9A-Za-z-]+$/.test(name)
    : /^[A-Za-z_][A-Za-z0-9_.-]{0,159}$/.test(name)
}

function invalidNameMessage(headers: boolean): string {
  return headers ? 'Header 名称不合法' : '变量名不合法'
}

function duplicateNameMessage(headers: boolean): string {
  return headers ? 'Header 名称重复（不区分大小写）' : '变量名重复'
}

function toRecord(values: KeyValueEntry[]): Record<string, string> {
  return Object.fromEntries(values.map(({ name, value }) => [name, value]))
}

export function caseInput(
  values: CaseFormValues,
  previous: TestCase['draft_definition'] | undefined,
  isTemplate = false,
): TestCaseDraftInput {
  return {
    name: values.name,
    description: values.description,
    folderId: values.folderId ?? null,
    tags: values.tags ?? [],
    isTemplate,
    definition: {
      workflow_id: values.workflowId,
      workflow_version: selectedWorkflowVersion(values, previous),
      environment_id: values.environmentId,
      runtime_variables: selectedEntries(values.runtimeVariables, previous?.runtime_variables),
      runtime_headers: selectedEntries(values.runtimeHeaders, previous?.runtime_headers),
    },
  }
}

function selectedWorkflowVersion(
  values: CaseFormValues,
  previous: TestCase['draft_definition'] | undefined,
): number | null {
  if (values.workflowVersion !== undefined) return values.workflowVersion
  if (previous?.workflow_id === values.workflowId) return previous.workflow_version
  return null
}

function selectedEntries(
  values: KeyValueEntry[] | undefined,
  previous: Record<string, string> | undefined,
): Record<string, string> {
  return values ? toRecord(values) : (previous ?? {})
}

export function suiteInput(
  values: SuiteFormValues,
  cases: TestCase[],
  previous?: TestSuite,
): TestSuiteDraftInput {
  return {
    name: values.name,
    description: values.description,
    folderId: values.folderId ?? null,
    tags: values.tags ?? [],
    items: values.caseIds.map((caseId) => ({
      test_case_id: caseId,
      test_case_version: selectedMemberVersion(caseId, values, previous, cases),
    })),
  }
}

function selectedMemberVersion(
  caseId: string,
  values: SuiteFormValues,
  previous: TestSuite | undefined,
  cases: TestCase[],
): number | null {
  if (values.memberVersions && Object.hasOwn(values.memberVersions, caseId)) {
    return values.memberVersions[caseId]
  }
  const saved = previous?.draft_definition.items.find((item) => item.test_case_id === caseId)
  if (saved) return saved.test_case_version
  return cases.find((item) => item.id === caseId)?.current_version ?? null
}

export function pageItems<T>(page: { items: T[] } | undefined): T[] {
  return page?.items ?? []
}

export function folderItems(state: { folders: { data?: Folder[] } }): Folder[] {
  return state.folders.data ?? []
}

export function editorKey(item: { id: string } | null, fallback: string) {
  return item?.id ?? fallback
}
