import { useQuery } from '@tanstack/react-query'
import { Alert } from 'antd'
import { Link, useSearchParams, useInRouterContext } from 'react-router-dom'
import { getSelfTestGeneration } from './self-test-service'
import {
  reportSelfTestReference,
  selfTestPath,
  type SelfTestReference,
} from './self-test-navigation'
import { selfTestKeys, useSelfTestIdentity } from './self-test-query-keys'
import type { SelfTestGeneration, SelfTestProposal } from './self-test-contract'

type Props = { projectId: string; proposalId: string | undefined; route: SelfTestProposal['route'] }
function verifiedProposal(
  data: SelfTestGeneration | undefined,
  reference: SelfTestReference,
  props: Props,
) {
  if (!data) return false
  const matches = (proposal: SelfTestProposal) =>
    proposal.change_set_id === props.proposalId && proposal.route === props.route
  if (reference.scenarioId)
    return data.sources.some(
      (source) =>
        source.scenario_id === reference.scenarioId &&
        [source.workflow_proposal, source.case_proposal].some(matches),
    )
  return [
    ...data.proposals,
    ...data.sources.flatMap((source) => [source.workflow_proposal, source.case_proposal]),
  ].some(matches)
}
export default function SelfTestProposalBacklink(props: Props) {
  const routed = useInRouterContext()
  return routed ? <RoutedProposalBacklink {...props} /> : null
}
function RoutedProposalBacklink(props: Props) {
  const [params] = useSearchParams()
  const identity = useSelfTestIdentity(props.projectId)
  const reference = reportSelfTestReference(params)
  const generation = useQuery({
    queryKey: selfTestKeys.generation(identity, reference?.batchId ?? null),
    queryFn: ({ signal }) => getSelfTestGeneration(props.projectId, reference!.batchId, signal),
    enabled: [reference, props.proposalId, identity.userId].every(Boolean),
  })
  if (!params.has('selfTestBatch')) return null
  if (!reference) return <Alert type="warning" title="自测来源链接无效，未建立回链。" />
  if (!props.proposalId || generation.isLoading) return null
  const verified = verifiedProposal(
    generation.isSuccess ? generation.data : undefined,
    reference,
    props,
  )
  return verified ? (
    <Alert
      type="info"
      showIcon
      title={
        <Link to={selfTestPath(props.projectId, reference)}>返回已核验的 MCP 自测生成批次</Link>
      }
      description="此处继续使用原有人工审核流程；生成来源不授予批准、发布或运行权限。"
    />
  ) : (
    <Alert type="warning" showIcon title="当前提案与自测来源尚未核验，未建立回链。" />
  )
}
