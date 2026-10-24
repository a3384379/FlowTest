import { useLayoutEffect, useMemo, useRef } from 'react'
import { Alert, Button, Card, Descriptions, Empty, Space, Tag, Typography } from 'antd'
import { Link } from 'react-router-dom'
import { useRouteScopedState } from '../../lib/use-route-scoped-state'
import { apiErrorWithTrace, type ReportExecutionDetail } from '../../lib/api'
import type {
  SelfTestArtifact,
  SelfTestBatch,
  SelfTestScenario,
  SelfTestSource,
} from './self-test-contract'
import { selfTestProposalPath } from './self-test-navigation'
import { selfTestReasonLabel } from './self-test-labels'
import SelfTestSourceBindings from './SelfTestSourceBindings'
import SelfTestVerificationComparison from './SelfTestVerificationComparison'
import { RawExecutionStatus, VerificationStatusTag } from './SelfTestStatus'
import { readSelfTestArtifact } from './self-test-service'
import { selfTestIdentityIsCurrent, useSelfTestIdentity } from './self-test-query-keys'
import { scenarioHasCompleteEvidence } from './self-test-verdict'

export function SelfTestReasons({ reasons }: { reasons: string[] }) {
  return reasons.length ? (
    <Typography.Paragraph type="secondary">
      原因：{reasons.map(selfTestReasonLabel).join(' · ')}
    </Typography.Paragraph>
  ) : null
}
export function SelfTestSourceEvidence({
  projectId,
  batchId,
  source,
}: {
  projectId: string
  batchId: string
  source: SelfTestSource | null
}) {
  if (!source)
    return (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description="尚无已发布且核验完成的生成来源；设计和草稿不计为正式用例。"
      />
    )
  return (
    <>
      <Descriptions
        size="small"
        column={1}
        bordered
        items={[
          {
            key: 'scenario',
            label: '固定场景',
            children: `${source.scenario_id} / ${source.variant_key}`,
          },
          {
            key: 'workflow',
            label: 'Workflow 固定版本',
            children: `${source.workflow.id}@${source.workflow.version}`,
          },
          {
            key: 'case',
            label: 'Case 固定版本',
            children: `${source.case.id}@${source.case.version}`,
          },
          {
            key: 'design',
            label: '设计指纹',
            children: <Typography.Text code>{source.design_fingerprint}</Typography.Text>,
          },
          {
            key: 'compile',
            label: '编译指纹',
            children: <Typography.Text code>{source.compilation_fingerprint}</Typography.Text>,
          },
          {
            key: 'oracle',
            label: 'Oracle 映射摘要',
            children: <Typography.Text code>{source.oracle_mapping_digest}</Typography.Text>,
          },
          {
            key: 'api',
            label: 'API 来源摘要',
            children: <Typography.Text code>{source.api_sources_digest}</Typography.Text>,
          },
          {
            key: 'protocol',
            label: 'MCP 协议回执摘要',
            children: <Typography.Text code>{source.protocol_receipts_digest}</Typography.Text>,
          },
          {
            key: 'proposals',
            label: '人工审核',
            children: (
              <Space wrap>
                {[source.workflow_proposal, source.case_proposal].map((proposal, index) => (
                  <Link
                    key={`${proposal.change_set_id}:${proposal.item_id}`}
                    to={selfTestProposalPath(
                      projectId,
                      proposal.route === 'flow_spec_visual' ? 'flow_spec' : 'controlled_write',
                      proposal.change_set_id,
                      { batchId, scenarioId: source.scenario_id },
                    )}
                  >
                    {index === 0 ? '查看流程提案' : '查看用例提案'}
                  </Link>
                ))}
              </Space>
            ),
          },
        ]}
      />
      <SelfTestSourceBindings source={source} projectId={projectId} />
    </>
  )
}
const artifactLabels = {
  manifest: '批次清单',
  generation: '生成清单',
  evidence: '执行证据',
  verification: '独立核验结果',
  junit: 'JUnit 证据（未标注类型）',
  execution_junit: '原始执行 JUnit',
  verification_junit: '独立核验 JUnit',
  cleanup: '清理记录',
} as const
export function SelfTestArtifacts({
  projectId,
  batchId,
  artifacts,
}: {
  projectId: string
  batchId: string
  artifacts: SelfTestArtifact[]
}) {
  const identity = useSelfTestIdentity(projectId)
  const routeKey = `${identity.userId}:${identity.organizationId}:${identity.epoch}:${batchId}`
  const [error, setError] = useRouteScopedState<unknown>(projectId, routeKey, null)
  const [downloading, setDownloading] = useRouteScopedState<string | null>(
    projectId,
    routeKey,
    null,
  )
  const context = useMemo(() => ({ identity, projectId, batchId }), [identity, projectId, batchId])
  const current = useRef<typeof context | null>(context)
  useLayoutEffect(() => {
    current.current = context
    return () => {
      current.current = null
    }
  }, [context])
  const isCurrent = () => current.current === context && selfTestIdentityIsCurrent(identity)
  async function download(artifact: SelfTestArtifact) {
    if (downloading) return
    setDownloading(artifact.id)
    setError(null)
    try {
      const blob = await readSelfTestArtifact(projectId, batchId, artifact)
      if (!isCurrent()) return
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = `selftest-${artifact.kind}-${artifact.id}.${artifact.kind.includes('junit') ? 'xml' : 'json'}`
      anchor.click()
      URL.revokeObjectURL(url)
    } catch (failure) {
      if (isCurrent()) setError(failure)
    } finally {
      if (isCurrent()) setDownloading(null)
    }
  }
  return (
    <Space orientation="vertical" style={{ width: '100%' }}>
      {Boolean(error) && <Alert type="error" showIcon title={apiErrorWithTrace(error)} />}
      {!artifacts.length && (
        <Typography.Text type="secondary">尚无可下载的服务端证据。</Typography.Text>
      )}
      {artifacts.map((artifact) => (
        <div key={artifact.id}>
          <Button
            loading={downloading === artifact.id}
            disabled={Boolean(downloading && downloading !== artifact.id)}
            onClick={() => void download(artifact)}
          >
            {artifactLabels[artifact.kind]}
          </Button>{' '}
          <Typography.Text type="secondary" copyable>
            {artifact.sha256}
          </Typography.Text>
        </div>
      ))}
    </Space>
  )
}
export function SelfTestVerificationEvidence({
  projectId,
  batch,
  scenario,
  detail,
}: {
  projectId: string
  batch: SelfTestBatch
  scenario: SelfTestScenario
  detail?: ReportExecutionDetail
}) {
  const trustedEvidence = scenarioHasCompleteEvidence(batch, scenario)
  return (
    <div className="self-test-evidence">
      <Space wrap>
        <RawExecutionStatus status={scenario.observed_status} />
        <VerificationStatusTag
          status={trustedEvidence ? scenario.verification_status : 'incomplete'}
        />
        <Tag color={batch.provenance === 'trusted_ci' ? 'blue' : 'warning'}>
          {batch.provenance === 'trusted_ci' ? '受信 CI 来源' : '本地未受信来源'}
        </Tag>
      </Space>
      {!trustedEvidence && (
        <Alert type="warning" showIcon title="证据尚未完整封存，不能认定验收通过。" />
      )}
      <Typography.Text type="secondary">
        服务端场景回执：{scenario.verification_status}；批次证据完整性：{batch.evidence_integrity}
      </Typography.Text>
      <VerificationIdentity batch={batch} scenario={scenario} />
      <SelfTestVerificationComparison
        batch={batch}
        scenario={scenario}
        trusted={trustedEvidence}
        detail={detail}
      />
      <SelfTestReasons reasons={scenario.reason_codes} />
      <Card size="small" title="执行与核验证据">
        <SelfTestArtifacts
          projectId={projectId}
          batchId={batch.id}
          artifacts={scenario.evidence_refs}
        />
      </Card>
    </div>
  )
}

function VerificationIdentity({
  batch,
  scenario,
}: {
  batch: SelfTestBatch
  scenario: SelfTestScenario
}) {
  return (
    <>
      <Descriptions
        column={1}
        size="small"
        bordered
        items={[
          {
            key: 'expected',
            label: '冻结预期',
            children: `${scenario.expected.status}${scenario.expected.error_code ? ` · ${scenario.expected.error_code}` : ''}${scenario.expected.phase ? ` · ${scenario.expected.phase}` : ''}`,
          },
          {
            key: 'scope',
            label: '核验范围',
            children:
              batch.verification_scope === 'full_pack'
                ? '当前固定包全部场景'
                : batch.verification_scope === 'selected_suites'
                  ? '选定套件（不代表全量）'
                  : '诊断子集（不代表全量）',
          },
          { key: 'integrity', label: '证据完整性', children: batch.evidence_integrity },
          {
            key: 'attempts',
            label: '执行尝试',
            children: scenario.attempts_complete ? '全部尝试已归集' : '尝试证据未完整',
          },
          { key: 'cleanup', label: '清理状态', children: batch.cleanup_status },
          {
            key: 'digest',
            label: '批次清单摘要',
            children: <Typography.Text code>{batch.manifest_digest}</Typography.Text>,
          },
          { key: 'runner-build', label: 'Runner 构建', children: batch.builds.runner },
          { key: 'target-build', label: 'Target 构建', children: batch.builds.target },
          { key: 'fixture-build', label: 'Fixture 构建', children: batch.builds.fixture },
          { key: 'build', label: 'Verifier 构建', children: batch.builds.verifier },
          { key: 'sealed', label: '证据封存时间', children: batch.sealed_at ?? '未封存' },
        ]}
      />
    </>
  )
}
