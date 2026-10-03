import { apiClient } from '../../lib/api'
import type { AssetKind } from './asset-workspace-service'

export type AssetDeleteTarget = {
  id: string
  expected_name: string
  expected_draft_fingerprint: string
  expected_version: number | null
  expected_updated_at: string
}
export type AssetReference = {
  kind: 'test_plan' | 'test_suite' | 'execution'
  id: string
  name: string | null
  version: number | null
}
export type AssetDeletionPreview = {
  targets: Array<{ asset: AssetDeleteTarget; archived: boolean; references: AssetReference[] }>
}
export type AssetDeletionResult = { archived_ids: string[]; historical_data_retained: true }

export async function previewAssetDeletion(
  projectId: string,
  kind: AssetKind,
  ids: string[],
): Promise<AssetDeletionPreview> {
  const resource = kind === 'case' ? 'test-cases' : 'test-suites'
  return (
    await apiClient.post<AssetDeletionPreview>(
      `/projects/${projectId}/${resource}/deletion-preview`,
      { asset_ids: ids },
    )
  ).data
}

export async function deleteTestAssets(
  projectId: string,
  kind: AssetKind,
  targets: AssetDeleteTarget[],
): Promise<AssetDeletionResult> {
  if (!targets.length) throw new Error('请明确选择需要删除的测试资产')
  const resource = kind === 'case' ? 'test-cases' : 'test-suites'
  const url = `/projects/${projectId}/${resource}`
  const response =
    targets.length === 1
      ? await apiClient.delete<AssetDeletionResult>(`${url}/${targets[0].id}`, { data: targets[0] })
      : await apiClient.post<AssetDeletionResult>(`${url}/bulk-delete`, { assets: targets })
  if (
    !deletionScopeMatches(
      targets.map((target) => target.id),
      response.data.archived_ids,
    ) ||
    response.data.historical_data_retained !== true
  ) {
    throw new Error('删除结果与确认范围不一致，请刷新资产列表核对结果')
  }
  return response.data
}

export function deletionScopeMatches(expected: string[], actual: string[]): boolean {
  return (
    expected.length > 0 &&
    expected.length === actual.length &&
    new Set(actual).size === actual.length &&
    expected.every((id) => actual.includes(id))
  )
}
