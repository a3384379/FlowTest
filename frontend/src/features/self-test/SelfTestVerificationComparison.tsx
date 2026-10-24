import { Alert, Table, Tag, Typography } from 'antd'
import type { ReportExecutionDetail } from '../../lib/api'
import type { SelfTestBatch, SelfTestScenario } from './self-test-contract'

type ComparisonProps = {
  batch: SelfTestBatch
  scenario: SelfTestScenario
  trusted: boolean
  detail?: ReportExecutionDetail
}
type ComparisonRow = {
  key: string
  item: string
  expected: string
  observed: string
  comparison: string
}
type FailureEvidence = { codes: string[]; locations: string[] }

export default function SelfTestVerificationComparison({
  batch,
  scenario,
  trusted,
  detail,
}: ComparisonProps) {
  const native = failureEvidence(detail)
  const observed = detail?.summary.status ?? scenario.observed_status
  const matched = trusted && scenario.verification_status === 'matched'
  const summary = {
    expected_status: scenario.expected.status,
    observed_status: observed,
    expected_error_code: scenario.expected.error_code,
    observed_error_codes: detail ? native.codes : null,
    verification_status: trusted ? scenario.verification_status : 'incomplete',
    evidence_integrity: batch.evidence_integrity,
    scope: batch.verification_scope,
  }
  return (
    <>
      <MetricCards scenario={scenario} observed={observed} matched={matched} trusted={trusted} />
      {scenario.expected.error_code && (
        <Tag color="error">冻结错误码：{scenario.expected.error_code}</Tag>
      )}
      {native.locations.length > 0 && (
        <Alert
          type="info"
          showIcon
          title="实际失败位置与错误码"
          description={native.locations.join('；')}
        />
      )}
      <Table
        rowKey="key"
        size="small"
        pagination={false}
        scroll={{ x: 600 }}
        dataSource={[
          statusRow(scenario, observed),
          errorRow(scenario, native, Boolean(detail)),
          {
            key: 'requests',
            item: '请求次数 / 分支 / 迭代',
            expected: '以冻结清单为准',
            observed: '当前摘要未提供，详见执行与核验证据',
            comparison: '以独立核验回执为准',
          },
        ]}
        columns={[
          { title: '核验项', dataIndex: 'item' },
          { title: '固定期望', dataIndex: 'expected' },
          { title: '实际证据', dataIndex: 'observed' },
          { title: '对照', dataIndex: 'comparison' },
        ]}
      />
      <Typography.Text strong>独立核验摘要</Typography.Text>
      <pre className="self-test-evidence-summary">{JSON.stringify(summary, null, 2)}</pre>
      <Typography.Text type="secondary">
        此摘要仅整理当前已授权的回执字段；引擎原始 response 和完整核验证据分别保留。
      </Typography.Text>
    </>
  )
}
function MetricCards({
  scenario,
  observed,
  matched,
  trusted,
}: {
  scenario: SelfTestScenario
  observed: string | null
  matched: boolean
  trusted: boolean
}) {
  return (
    <div className="self-test-verification-cards">
      <div className="self-test-verification-card">
        <Typography.Text>固定期望</Typography.Text>
        <strong>{scenario.expected.status}</strong>
      </div>
      <div className={`self-test-verification-card ${observed === 'failed' ? 'is-failed' : ''}`}>
        <Typography.Text>原始执行</Typography.Text>
        <strong>{observed ?? '未运行'}</strong>
      </div>
      <div className={`self-test-verification-card ${matched ? 'is-matched' : ''}`}>
        <Typography.Text>独立核验</Typography.Text>
        <strong>
          {matched ? '符合预期' : trusted ? scenario.verification_status : '未完整核验'}
        </strong>
      </div>
    </div>
  )
}
function failureEvidence(detail: ReportExecutionDetail | undefined): FailureEvidence {
  if (!detail) return { codes: [], locations: [] }
  const failures = detail.nodes.flatMap((node) => {
    if (node.status !== 'failed' || !node.error_code) return []
    return [{ code: node.error_code, location: `${node.node_id} · ${node.error_code}` }]
  })
  return {
    codes: failures.map((failure) => failure.code),
    locations: failures.map((failure) => failure.location),
  }
}
function statusRow(scenario: SelfTestScenario, observed: string | null): ComparisonRow {
  return {
    key: 'status',
    item: '原始状态',
    expected: scenario.expected.status,
    observed: observed ?? '未提供',
    comparison:
      observed == null
        ? '尚无证据'
        : observed === scenario.expected.status
          ? '状态一致'
          : '状态不一致',
  }
}
function errorRow(
  scenario: SelfTestScenario,
  native: FailureEvidence,
  hasDetail: boolean,
): ComparisonRow {
  let comparison = '待核对原始证据'
  if (hasDetail && scenario.expected.error_code) {
    comparison =
      native.codes.length === 1 && native.codes[0] === scenario.expected.error_code
        ? '错误码一致'
        : '以节点及核验回执为准'
  }
  return {
    key: 'error',
    item: '错误码',
    expected: scenario.expected.error_code ?? '无',
    observed: hasDetail
      ? native.codes.join('；') || '当前执行没有节点错误码'
      : '当前摘要未提供，详见独立核验 JSON',
    comparison,
  }
}
