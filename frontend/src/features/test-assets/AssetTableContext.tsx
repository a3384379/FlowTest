import { useQuery } from '@tanstack/react-query'
import { Typography } from 'antd'
import type { TestCase, Workflow } from '../../lib/api'
import { AssetRecentResult } from './AssetRunEvidence'
import type { AssetKind, PublishedAssetTarget } from './asset-workspace-service'
import { listTestCaseVersions } from './test-asset-service'
import type { useAssetHistory } from './use-asset-history'

export type AssetTableWorkspace = {
  projectId: string
  page: number
  onPage: (page: number) => void
  onFocus: (kind: AssetKind, id: string) => void
  onPlan: (target: PublishedAssetTarget, execute: boolean) => void
  onDelete: (kind: AssetKind, ids: string[]) => void
  workflows: Workflow[]
  history: ReturnType<typeof useAssetHistory>
  canEdit: boolean
  canExecute: boolean
}

export function PublishedCaseBinding({
  item,
  workspace,
}: {
  item: TestCase
  workspace: AssetTableWorkspace
}) {
  const versions = useQuery({
    queryKey: ['test-case-versions', workspace.projectId, item.id],
    queryFn: () => listTestCaseVersions(workspace.projectId, item.id),
    enabled: item.current_version !== null,
  })
  if (!item.current_version) return <Typography.Text type="secondary">草稿尚未发布</Typography.Text>
  if (versions.error) return <Typography.Text type="danger">绑定读取失败</Typography.Text>
  const version = versions.data?.find((candidate) => candidate.version === item.current_version)
  if (!version)
    return (
      <Typography.Text type="secondary">
        {versions.isPending ? '读取绑定中' : '发布版本不存在'}
      </Typography.Text>
    )
  const workflow = workspace.workflows.find(
    (candidate) => candidate.id === version.definition.workflow_id,
  )
  return (
    <span>
      {workflow?.name ?? version.definition.workflow_id} · v{version.definition.workflow_version}
    </span>
  )
}

export function RecentAssetCell({
  kind,
  id,
  workspace,
}: {
  kind: AssetKind
  id: string
  workspace: AssetTableWorkspace
}) {
  if (workspace.history.loading)
    return <Typography.Text type="secondary">读取结果中</Typography.Text>
  if (workspace.history.error)
    return <Typography.Text type="danger">结果未完整加载</Typography.Text>
  return (
    <AssetRecentResult
      projectId={workspace.projectId}
      entry={workspace.history.history(kind, id)[0]}
    />
  )
}
