import type { Folder, TestCase } from '../../lib/api'
import type { TestCaseDraftInput, TestSuiteDraftInput } from './test-asset-service'

export type CaseFormValues = {
  name: string
  description: string
  folderId?: string
  tags: string[]
  isTemplate: boolean
  workflowId: string
  environmentId: string
}

export type SuiteFormValues = {
  name: string
  description: string
  folderId?: string
  tags: string[]
  caseIds: string[]
}

export function caseInput(
  values: CaseFormValues,
  previous: TestCase['draft_definition'] | undefined,
): TestCaseDraftInput {
  return {
    name: values.name,
    description: values.description,
    folderId: values.folderId ?? null,
    tags: values.tags ?? [],
    isTemplate: values.isTemplate,
    definition: {
      workflow_id: values.workflowId,
      workflow_version:
        previous?.workflow_id === values.workflowId ? previous.workflow_version : null,
      environment_id: values.environmentId,
      runtime_variables: previous?.runtime_variables ?? {},
      runtime_headers: previous?.runtime_headers ?? {},
    },
  }
}

export function suiteInput(values: SuiteFormValues, cases: TestCase[]): TestSuiteDraftInput {
  return {
    name: values.name,
    description: values.description,
    folderId: values.folderId ?? null,
    tags: values.tags ?? [],
    items: values.caseIds.map((caseId) => ({
      test_case_id: caseId,
      test_case_version: cases.find((item) => item.id === caseId)?.current_version ?? null,
    })),
  }
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
