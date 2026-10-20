import { Space, Typography } from 'antd'
import { Link, useSearchParams } from 'react-router-dom'
import type { AssetCatalogRun } from '../../lib/api'
import { projectPath } from '../projects/project-routing'
import { reportExecutionPath } from '../workflows/execution-navigation'
import { AssetResultTag } from './AssetRunEvidence'

export default function CaseCatalogResult({
  projectId,
  caseId,
  run,
}: {
  projectId: string
  caseId: string
  run: AssetCatalogRun | null
}) {
  const [params] = useSearchParams()
  if (!run) return <Typography.Text type="secondary">未运行</Typography.Text>
  return (
    <Space size={4} wrap>
      <AssetResultTag status={run.status} />
      {run.asset_version === null ? (
        <Typography.Text type="secondary">版本未提供</Typography.Text>
      ) : (
        <Link
          title={new Date(run.occurred_at).toLocaleString('zh-CN')}
          to={versionPath(projectId, caseId, run.asset_version, params)}
        >
          用例 v{run.asset_version}
        </Link>
      )}
      <Typography.Text type="secondary">
        {run.source === 'direct' ? '直接运行' : '测试计划'}
      </Typography.Text>
      {run.execution_id ? (
        <Link to={reportExecutionPath(projectId, { executionId: run.execution_id })}>报告 →</Link>
      ) : (
        run.plan_id && (
          <Link to={`${projectPath(projectId, 'tasks')}?focus=${run.plan_id}`}>查看计划</Link>
        )
      )}
    </Space>
  )
}

function versionPath(projectId: string, caseId: string, version: number, params: URLSearchParams) {
  const next = new URLSearchParams(params)
  next.set('type', 'case')
  next.set('focus', caseId)
  next.set('version', String(version))
  return `${projectPath(projectId, 'assets')}?${next}`
}
