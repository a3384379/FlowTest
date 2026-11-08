import { useQuery } from '@tanstack/react-query'
import { Alert } from 'antd'
import { Link, useInRouterContext, useSearchParams } from 'react-router-dom'
import QueryFailureNotice from '../../components/QueryFailureNotice'
import { selfTestScope, useSelfTestIdentity } from './self-test-query-keys'
import { getSelfTestBatch, getSelfTestInstallation } from './self-test-service'
import { reportSelfTestReference, selfTestOriginContext } from './self-test-navigation'

type Props = {
  projectId: string
  kind: 'workflow' | 'case' | 'suite'
  id: string
  version?: number | 'draft'
}
export default function SelfTestAssetBacklink(props: Props) {
  const routed = useInRouterContext()
  return routed ? <RoutedAssetBacklink {...props} /> : null
}
function RoutedAssetBacklink({ projectId, kind, id, version }: Props) {
  const [params] = useSearchParams()
  const identity = useSelfTestIdentity(projectId)
  const reference = reportSelfTestReference(params)
  const origin = selfTestOriginContext(params)
  const installation = new URLSearchParams(origin ?? '').get('installation')
  const enabled = Boolean(
    identity.userId && origin && (reference || installation) && typeof version === 'number',
  )
  const query = useQuery({
    queryKey: [
      ...selfTestScope(identity),
      'asset-backlink',
      reference?.batchId,
      installation,
      kind,
      id,
      version,
    ],
    enabled,
    queryFn: async ({ signal }) => {
      const matches = (asset: { id: string; version: number }) =>
        asset.id === id && asset.version === version
      if (reference) {
        const batch = await getSelfTestBatch(projectId, reference.batchId, signal)
        if (kind === 'suite')
          return Boolean(batch.resource_snapshot && matches(batch.resource_snapshot.suite))
        return Boolean(batch.resource_snapshot?.cases.some((row) => matches(row[kind])))
      }
      const installed = await getSelfTestInstallation(projectId, installation!, signal)
      return (
        kind !== 'suite' && Boolean(installed.mapping?.assets.some((row) => matches(row[kind])))
      )
    },
  })
  if (!enabled) return null
  return (
    <>
      <QueryFailureNotice queries={[query]} />
      {query.isSuccess && query.data && (
        <Alert
          type="info"
          title={<Link to={`/projects/${projectId}/quality?${origin}`}>返回已核验的自测范围</Link>}
          description="已核对当前固定资产与批次或原安装映射。"
        />
      )}
    </>
  )
}
