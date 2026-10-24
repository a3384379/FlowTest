import { useQuery } from '@tanstack/react-query'
import { Alert, Card, Tabs, Typography } from 'antd'
import { Link, useSearchParams } from 'react-router-dom'
import QueryFailureNotice from '../../components/QueryFailureNotice'
import { reportSelfTestReference, selfTestPath } from './self-test-navigation'
import { selfTestKeys, useSelfTestIdentity } from './self-test-query-keys'
import { getSelfTestExecutionRelation } from './self-test-service'
import { SelfTestSourceEvidence, SelfTestVerificationEvidence } from './SelfTestEvidence'
import SelfTestSourceChain from './SelfTestSourceChain'
import type { ReportExecutionDetail } from '../../lib/api'
import type { SelfTestRelation } from './self-test-contract'
import './self-test.css'

function useReportRelation(projectId: string, executionId: string) {
  const [params, setParams] = useSearchParams()
  const identity = useSelfTestIdentity(projectId)
  const reference = reportSelfTestReference(params)
  const relation = useQuery({
    queryKey: selfTestKeys.relation(
      identity,
      reference?.batchId ?? '',
      reference?.scenarioId,
      executionId,
    ),
    queryFn: ({ signal }) =>
      getSelfTestExecutionRelation(
        projectId,
        reference!.batchId,
        reference!.scenarioId!,
        executionId,
        signal,
      ),
    enabled: Boolean(reference?.scenarioId && identity.userId),
  })
  return { projectId, params, setParams, reference, relation }
}
type ReportState = ReturnType<typeof useReportRelation>
export default function SelfTestReportPanels({
  projectId,
  executionId,
  detail,
}: {
  projectId: string
  executionId: string
  detail?: ReportExecutionDetail
}) {
  const state = useReportRelation(projectId, executionId)
  if (!state.params.has('selfTestBatch') && !state.params.has('selfTestScenario')) return null
  if (!state.reference?.scenarioId)
    return (
      <Alert
        type="warning"
        showIcon
        title="自测来源链接无效或缺少场景，未核验关联。原生执行报告仍可查看。"
      />
    )
  return (
    <Card
      className="self-test-report-card"
      title="本次执行的自测来源与独立核验"
      loading={state.relation.isLoading}
    >
      <QueryFailureNotice queries={[state.relation]} />
      {state.relation.isSuccess ? (
        <ConfirmedReportPanels state={state} detail={detail} />
      ) : (
        !state.relation.isLoading && (
          <Typography.Paragraph type="secondary">
            未能确认当前项目、批次、场景与执行的关系，不能展示自测验收结论。
          </Typography.Paragraph>
        )
      )}
    </Card>
  )
}
function ConfirmedReportPanels({
  state,
  detail,
}: {
  state: ReportState
  detail?: ReportExecutionDetail
}) {
  const { projectId, params, setParams } = state
  const result = state.relation.data!
  const confirmedDetail = confirmedNativeDetail(result, detail)
  return (
    <>
      <Link
        to={selfTestPath(
          projectId,
          state.reference!,
          result.batch.batch_kind === 'fixed_baseline' ? 'native' : 'mcp_generation',
        )}
      >
        返回已核验自测批次
      </Link>
      <Alert
        className="self-test-report-scope"
        type={result.batch.verification_scope === 'full_pack' ? 'info' : 'warning'}
        showIcon
        title={`范围：${result.batch.verification_scope === 'full_pack' ? '当前冻结包' : '所选子集'} · ${result.batch.expected_count} 个场景`}
        description="此处展示当前批次与当次执行的关联；所选子集不代表全部验收场景通过。"
      />
      <div className="self-test-report-layout">
        <SelfTestSourceChain relation={result} />
        <div>
          <Tabs
            activeKey={params.get('panel') === 'provenance' ? 'provenance' : 'verification'}
            onChange={(panel) => {
              const next = new URLSearchParams(params)
              next.set('panel', panel)
              setParams(next, { replace: true })
            }}
            items={[
              {
                key: 'provenance',
                label: '生成来源',
                children:
                  result.batch.batch_kind === 'fixed_baseline' ? (
                    <Typography.Paragraph>
                      固定基准来源，固定版本与冻结预期绑定于当前批次；不属于 MCP 生成链。
                    </Typography.Paragraph>
                  ) : (
                    <SelfTestSourceEvidence
                      projectId={projectId}
                      batchId={result.batch.id}
                      source={result.scenario.source}
                    />
                  ),
              },
              {
                key: 'verification',
                label: '独立核验',
                children: (
                  <SelfTestVerificationEvidence
                    projectId={projectId}
                    batch={result.batch}
                    scenario={result.scenario}
                    detail={confirmedDetail}
                  />
                ),
              },
            ]}
          />
        </div>
      </div>
    </>
  )
}

function confirmedNativeDetail(
  relation: SelfTestRelation,
  detail: ReportExecutionDetail | undefined,
) {
  if (!detail) return undefined
  const asset = relation.scenario.source ?? relation.scenario.published_assets
  const matches = [
    detail.summary.id === relation.execution_id,
    detail.summary.workflow_id === asset?.workflow.id,
    detail.summary.workflow_version === asset?.workflow.version,
  ].every(Boolean)
  return matches ? detail : undefined
}
