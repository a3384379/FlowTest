import { useQuery } from '@tanstack/react-query'
import { Alert, Drawer, Typography } from 'antd'
import { useSearchParams } from 'react-router-dom'
import { listWorkflowVersions } from '../workflows/workflow-service'
import QueryFailureNotice from '../../components/QueryFailureNotice'
import { selfTestScope, useSelfTestIdentity } from './self-test-query-keys'
import SelfTestProposalBacklink from './SelfTestProposalBacklink'
import SelfTestAssetBacklink from './SelfTestAssetBacklink'

export function SelfTestWorkflowContext({ projectId }: { projectId: string | null }) {
  const [params] = useSearchParams()
  if (!projectId) return null
  return (
    <>
      <SelfTestProposalBacklink
        projectId={projectId}
        proposalId={params.get('proposal') ?? params.get('selfTestProposal') ?? undefined}
        route="flow_spec_visual"
      />
      <SelfTestFixedWorkflow projectId={projectId} />
    </>
  )
}

/** A version deep link always opens its published definition; never substitute the draft. */
export default function SelfTestFixedWorkflow({ projectId }: { projectId: string }) {
  const [params, setParams] = useSearchParams()
  const identity = useSelfTestIdentity(projectId)
  const id = params.get('focus')
  const version = Number(params.get('version'))
  const enabled = Boolean(identity.userId && id && Number.isSafeInteger(version) && version > 0)
  const query = useQuery({
    queryKey: [...selfTestScope(identity), 'fixed-workflow', id, version],
    enabled,
    queryFn: async () => {
      const versions = await listWorkflowVersions(projectId, id!)
      const fixed = versions.find((item) => item.version === version && item.workflow_id === id)
      if (!fixed) throw new Error('固定流程版本不存在或已不可用，请核对来源。')
      return fixed
    },
  })
  return (
    <Drawer
      open={enabled}
      title={`Workflow 固定发布版本 v${version}`}
      size={800}
      onClose={() => {
        const next = new URLSearchParams(params)
        next.delete('version')
        setParams(next, { replace: true })
      }}
    >
      <QueryFailureNotice queries={[query]} />
      <SelfTestProposalBacklink
        projectId={projectId}
        proposalId={params.get('proposal') ?? params.get('selfTestProposal') ?? undefined}
        route="flow_spec_visual"
      />
      {id && (
        <SelfTestAssetBacklink projectId={projectId} kind="workflow" id={id} version={version} />
      )}
      <Alert
        type="info"
        title="正在查看冻结发布定义"
        description="关闭详情后可进入原有流程编辑与历史功能。"
      />
      {query.data && (
        <>
          <Typography.Text code>{query.data.fingerprint}</Typography.Text>
          <pre className="self-test-evidence-summary">
            {JSON.stringify(query.data.definition, null, 2)}
          </pre>
        </>
      )}
    </Drawer>
  )
}
