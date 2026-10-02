import type { AssetKind, AssetRunDetail, AssetRunItem } from './asset-workspace-service'

export type AssetRunEntry = {
  run: AssetRunDetail['run']
  items: AssetRunItem[]
  status: AssetRunItem['status']
  versions: number[]
}

export function assetRunHistory(
  details: AssetRunDetail[],
  kind: AssetKind,
  assetId: string,
): AssetRunEntry[] {
  return details
    .flatMap((detail) => {
      const items = detail.items.filter((item) => matchesAsset(item, kind, assetId))
      if (!items.length) return []
      const versions = items.map((item) =>
        kind === 'case' ? item.target_version : item.target_snapshot.source_suite!.version,
      )
      return [
        { run: detail.run, items, status: assetRunStatus(items), versions: [...new Set(versions)] },
      ]
    })
    .sort((a, b) => Date.parse(b.run.created_at) - Date.parse(a.run.created_at))
}

function matchesAsset(item: AssetRunItem, kind: AssetKind, id: string): boolean {
  if (kind === 'case') return item.target_type === 'case' && item.target_id === id
  return item.target_snapshot.source_suite?.id === id
}

export function assetRunStatus(items: AssetRunItem[]): AssetRunItem['status'] {
  const priority: AssetRunItem['status'][] = [
    'failed',
    'running',
    'queued',
    'cancelled',
    'quarantined',
  ]
  return priority.find((status) => items.some((item) => item.status === status)) ?? 'passed'
}

export function reportItem(entry: AssetRunEntry): AssetRunItem | undefined {
  return (
    entry.items.find((item) => item.status === 'failed' && item.workflow_execution_id) ??
    entry.items.find((item) => item.workflow_execution_id)
  )
}

export const assetRunLabels: Record<AssetRunItem['status'], string> = {
  queued: '排队中',
  running: '运行中',
  passed: '通过',
  failed: '失败',
  cancelled: '已取消',
  quarantined: '已隔离',
}
