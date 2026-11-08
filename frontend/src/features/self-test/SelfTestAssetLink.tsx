import { Link, useSearchParams } from 'react-router-dom'
import { carrySelfTestContext, selfTestReferenceWithContext } from './self-test-navigation'

export default function SelfTestAssetLink({
  projectId,
  kind,
  asset,
  batchId,
}: {
  projectId?: string
  kind: 'workflow' | 'case' | 'suite'
  asset: { id: string; version: number }
  batchId?: string
}) {
  const [params] = useSearchParams()
  const label = `${asset.id}@${asset.version}`
  if (!projectId) return <>{label}</>
  const reference = batchId ? selfTestReferenceWithContext({ batchId }, params) : undefined
  const context = new URLSearchParams(params)
  if (reference) {
    context.set('selfTestBatch', reference.batchId)
    if (reference.returnContext) context.set('selfTestReturn', reference.returnContext)
  }
  const path =
    kind === 'workflow'
      ? `workflows?focus=${asset.id}&version=${asset.version}`
      : `assets?type=${kind}&focus=${asset.id}&version=${asset.version}`
  return <Link to={carrySelfTestContext(`/projects/${projectId}/${path}`, context)}>{label}</Link>
}
