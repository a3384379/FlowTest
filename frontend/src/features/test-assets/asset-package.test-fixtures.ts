import { environment, project, workflow } from '../../test/fixtures'
import type { PackageImportResult, PackagePreview, TestAssetPackage } from './asset-package-service'

const definition = {
  workflow_id: workflow.id,
  workflow_version: 1,
  environment_id: environment.id,
  runtime_variables: { fixture: 'v1' },
  runtime_headers: {},
}
const caseId = '00000000-0000-4000-8000-000000000071'
const suiteId = '00000000-0000-4000-8000-000000000072'
const members = { items: [{ test_case_id: caseId, test_case_version: 1 }] }

export const nativePackage: TestAssetPackage = {
  format: 'flowtest-test-assets',
  format_version: 1,
  source_project_id: project.id,
  folders: [],
  environments: [{ id: environment.id, name: environment.name }],
  workflows: [
    {
      id: workflow.id,
      name: workflow.name,
      versions: [{ version: 1, fingerprint: 'a'.repeat(64) }],
    },
  ],
  cases: [
    {
      id: caseId,
      name: '包用例',
      description: '用例说明',
      folder_id: null,
      tags: ['包标签'],
      is_template: true,
      draft_definition: definition,
      versions: [{ version: 1, definition, fingerprint: 'b'.repeat(64), change_note: '版本说明' }],
    },
  ],
  suites: [
    {
      id: suiteId,
      name: '包套件',
      description: '',
      folder_id: null,
      tags: ['包标签'],
      draft_definition: members,
      versions: [{ version: 1, definition: members, fingerprint: 'c'.repeat(64), change_note: '' }],
    },
  ],
}

export const packagePreview: PackagePreview = {
  fingerprint: 'd'.repeat(64),
  can_apply: true,
  assets: [
    ...nativePackage.cases.map((asset) => ({
      ...previewAsset(asset.id, asset.name),
      kind: 'case' as const,
    })),
    ...nativePackage.suites.map((asset) => ({
      ...previewAsset(asset.id, asset.name),
      kind: 'suite' as const,
    })),
  ],
  dependencies: [
    {
      kind: 'workflow',
      source_id: workflow.id,
      source_name: workflow.name,
      target_id: workflow.id,
      target_name: workflow.name,
      source_version: 1,
      target_version: 1,
      fingerprint_changed: false,
      problems: [],
    },
  ],
}

function previewAsset(id: string, name: string) {
  return {
    source_id: id,
    source_name: name,
    action: 'create' as const,
    target_id: null,
    target_name: name,
    existing_version: null,
    existing_updated_at: null,
    existing_draft_fingerprint: null,
    existing_content_fingerprint: null,
    versions: [{ source_version: 1, target_version: 1, creates_version: true }],
    problems: [],
  }
}

export const packageResult: PackageImportResult = {
  assets: packagePreview.assets.map((asset, index) => ({
    kind: asset.kind,
    source_id: asset.source_id,
    target_id: `imported-${index}`,
    action: asset.action,
    versions: asset.versions,
  })),
}

export function packageFile(content: string = JSON.stringify(nativePackage)): File {
  const file = new File([content], 'flowtest-assets.json', { type: 'application/json' })
  // JSDOM's File does not implement the browser's text method.
  Object.defineProperty(file, 'text', { value: () => Promise.resolve(content) })
  return file
}
