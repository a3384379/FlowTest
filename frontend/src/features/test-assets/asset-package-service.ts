import { apiClient, type TestCaseDefinition, type TestSuiteItem } from '../../lib/api'
import { exportError } from '../api-console/export-download'
import type { AssetKind } from './asset-workspace-service'

export type PackageCaseVersion = {
  version: number
  definition: TestCaseDefinition & { workflow_version: number }
  fingerprint: string
  change_note: string
}

export type PackageSuiteVersion = {
  version: number
  definition: { items: TestSuiteItem[] }
  fingerprint: string
  change_note: string
}

export type PackageAsset = {
  id: string
  name: string
  description: string
  folder_id: string | null
  tags: string[]
}

export type TestAssetPackage = {
  format: 'flowtest-test-assets'
  format_version: 1
  source_project_id: string
  folders: { id: string; name: string; parent_id: string | null }[]
  environments: { id: string; name: string }[]
  workflows: { id: string; name: string; versions: { version: number; fingerprint: string }[] }[]
  cases: (PackageAsset & {
    is_template: boolean
    draft_definition: TestCaseDefinition
    versions: PackageCaseVersion[]
  })[]
  suites: (PackageAsset & {
    draft_definition: { items: TestSuiteItem[] }
    versions: PackageSuiteVersion[]
  })[]
}

export type PackageAction = 'create' | 'clone' | 'update' | 'skip'
export type PackageChoice = {
  kind: AssetKind
  source_id: string
  action: PackageAction
  name?: string
  target_id?: string
}

export type PackageBindings = {
  workflows?: Record<string, { target_id: string; versions: Record<number, number> }>
  environments?: Record<string, string>
  folders?: Record<string, string | null>
}

export type PackageVersionMapping = {
  source_version: number
  target_version: number
  creates_version: boolean
}

export type PackageAssetPreview = {
  kind: AssetKind
  source_id: string
  source_name: string
  action: PackageAction
  target_id: string | null
  target_name: string
  existing_version: number | null
  existing_updated_at: string | null
  existing_draft_fingerprint: string | null
  existing_content_fingerprint: string | null
  versions: PackageVersionMapping[]
  problems: string[]
}

export type PackagePreview = {
  fingerprint: string
  can_apply: boolean
  assets: PackageAssetPreview[]
  dependencies: {
    kind: 'workflow' | 'environment' | 'folder'
    source_id: string
    source_name: string
    target_id: string | null
    target_name: string | null
    source_version: number | null
    target_version: number | null
    fingerprint_changed: boolean
    problems: string[]
  }[]
}

export type PackagePreviewInput = {
  package: TestAssetPackage
  choices: PackageChoice[]
  bindings: PackageBindings
}

export type PackageImportResult = {
  assets: {
    kind: AssetKind
    source_id: string
    target_id: string
    action: PackageAction
    versions: PackageVersionMapping[]
  }[]
}

export async function readAndPreviewAssetPackage(
  projectId: string,
  file: File,
): Promise<{ package: TestAssetPackage; preview: PackagePreview }> {
  if (file.size > 10 * 1024 * 1024) throw new Error('原生包超过 10 MiB，请缩小文件')
  let candidate: unknown
  try {
    candidate = JSON.parse(await file.text())
  } catch (error) {
    if (!(error instanceof SyntaxError)) throw error
    throw new Error('原生包必须是合法的 JSON 文件', { cause: error })
  }
  const response = await apiClient.post<PackagePreview>(
    `/projects/${projectId}/test-assets/import/preview`,
    { package: candidate, choices: [], bindings: {} },
  )
  // The server has validated the complete versioned package contract before it is used by the UI.
  return { package: candidate as TestAssetPackage, preview: response.data }
}

export async function previewAssetPackage(
  projectId: string,
  input: PackagePreviewInput,
): Promise<PackagePreview> {
  const response = await apiClient.post<PackagePreview>(
    `/projects/${projectId}/test-assets/import/preview`,
    input,
  )
  return response.data
}

export async function applyAssetPackage(
  projectId: string,
  input: PackagePreviewInput,
  expectedFingerprint: string,
): Promise<PackageImportResult> {
  const response = await apiClient.post<PackageImportResult>(
    `/projects/${projectId}/test-assets/import/apply`,
    { ...input, expected_preview_fingerprint: expectedFingerprint },
  )
  const expected = new Set([
    ...input.package.cases.map((asset) => `case:${asset.id}`),
    ...input.package.suites.map((asset) => `suite:${asset.id}`),
  ])
  const returned = new Set(response.data.assets.map((asset) => `${asset.kind}:${asset.source_id}`))
  if (!samePackageScope(expected, returned, response.data.assets.length)) {
    throw new Error('导入响应范围与确认的原生包不一致，请刷新资产列表核对结果')
  }
  return response.data
}

function samePackageScope(expected: Set<string>, returned: Set<string>, length: number): boolean {
  return (
    length === expected.size &&
    expected.size === returned.size &&
    [...expected].every((key) => returned.has(key))
  )
}

export async function exportAssetPackage(
  projectId: string,
  caseIds: string[],
  suiteIds: string[],
): Promise<void> {
  const response = await apiClient
    .post<Blob>(
      `/projects/${projectId}/test-assets/export`,
      { case_ids: caseIds, suite_ids: suiteIds },
      { responseType: 'blob' },
    )
    .catch(async (error: unknown) => {
      throw await exportError(error)
    })
  const url = URL.createObjectURL(response.data)
  try {
    const link = document.createElement('a')
    link.href = url
    link.download = `flowtest-test-assets-${projectId}.json`
    link.click()
  } finally {
    URL.revokeObjectURL(url)
  }
}
