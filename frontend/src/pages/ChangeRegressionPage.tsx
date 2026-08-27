import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Divider,
  Form,
  Input,
  Layout,
  Row,
  Select,
  Space,
  Steps,
  Switch,
  Table,
  Tag,
  Typography,
} from 'antd'
import { useState } from 'react'
import type {
  ChangeRegressionRun,
  ChangeRegressionStatus,
  CurrentPlanGap,
  FailureTriageResult,
  MissingTestProposal,
  SemanticCoverageScope,
} from '../features/change-regression/change-regression-service'
import { useChangeRegression } from '../features/change-regression/use-change-regression'

const { TextArea } = Input

export default function ChangeRegressionPage() {
  const state = useChangeRegression()
  const [form] = Form.useForm()
  const detail = state.detail.data
  const plans = state.plans.data?.items ?? []
  const policies = state.policies.data ?? []
  const runItems = state.runs.data?.items ?? []
  const sourceDiff = Form.useWatch('git_diff', form)

  const planOptions = plans.map((plan) => ({
    value: plan.id,
    label: plan.name + ' · ' + plan.items.length + ' 项',
  }))

  async function submit(values: Record<string, unknown>) {
    await state.createRun({
      title: String(values.title ?? ''),
      source_ref: String(values.source_ref ?? ''),
      candidate_ref: String(values.candidate_ref ?? ''),
      git_diff: sourceDiff ? String(sourceDiff) : undefined,
      openapi_diffs: [],
      schema_diffs: [],
      test_plan_id: String(values.test_plan_id ?? ''),
      release_policy_id: String(values.release_policy_id ?? ''),
      generate_missing_tests: Boolean(values.generate_missing_tests),
    })
  }

  return (
    <Layout className="page-layout">
      <Space direction="vertical" size={20} style={{ width: '100%' }}>
        <div className="page-heading">
          <div>
            <Typography.Title level={2}>变更驱动回归</Typography.Title>
            <Typography.Paragraph type="secondary">
              将 Change、Impact、测试选择、缺失测试审核、执行证据与 Release Gate
              串成一条可追溯链路。
            </Typography.Paragraph>
          </div>
          <Tag color="blue">S45</Tag>
        </div>
        <Alert
          type="info"
          showIcon
          message="低置信度缺失测试只生成 Draft；必须完成逐项 Review 和人工批准后才能执行。"
        />
        <Card title="创建变更回归链路">
          <Form
            form={form}
            layout="vertical"
            onFinish={submit}
            initialValues={{ generate_missing_tests: true }}
          >
            <Row gutter={16}>
              <Col xs={24} md={8}>
                <Form.Item name="title" label="链路名称" rules={[{ required: true }]}>
                  <Input placeholder="订单服务变更回归" />
                </Form.Item>
              </Col>
              <Col xs={24} md={8}>
                <Form.Item name="candidate_ref" label="候选版本" rules={[{ required: true }]}>
                  <Input placeholder="commit:abc123" />
                </Form.Item>
              </Col>
              <Col xs={24} md={8}>
                <Form.Item name="source_ref" label="变更来源">
                  <Input placeholder="github://org/repo/commit/abc123" />
                </Form.Item>
              </Col>
            </Row>
            <Row gutter={16}>
              <Col xs={24} md={12}>
                <Form.Item name="test_plan_id" label="回归测试计划" rules={[{ required: true }]}>
                  <Select options={planOptions} placeholder="选择已有测试计划" />
                </Form.Item>
              </Col>
              <Col xs={24} md={12}>
                <Form.Item
                  name="release_policy_id"
                  label="Release Policy"
                  rules={[{ required: true }]}
                >
                  <Select
                    options={policies.map((policy) => ({
                      value: policy.id,
                      label: policy.name,
                    }))}
                    placeholder="选择发布门禁策略"
                  />
                </Form.Item>
              </Col>
            </Row>
            <Form.Item name="git_diff" label="Git Diff" rules={[{ required: true }]}>
              <TextArea rows={7} placeholder="粘贴受限的标准 diff --git 内容" />
            </Form.Item>
            <Form.Item
              name="generate_missing_tests"
              label="生成缺失测试 Draft"
              valuePropName="checked"
              extra="仅控制 Test Design 草案创建；语义覆盖分析与 Approve/Execute/Release 门禁始终执行。"
            >
              <Switch />
            </Form.Item>
            <Button type="primary" htmlType="submit" loading={state.creating}>
              分析并创建链路
            </Button>
          </Form>
        </Card>
        <Row gutter={16}>
          <Col xs={24} lg={9}>
            <Card title="链路记录" loading={state.runs.isLoading}>
              <Table
                rowKey="id"
                size="small"
                pagination={false}
                dataSource={runItems}
                onRow={(record) => ({
                  onClick: () => state.setSelectedRunId(record.id),
                })}
                rowClassName={(record) =>
                  record.id === state.selectedRunId ? 'table-row-selected' : ''
                }
                columns={[
                  { title: '候选版本', dataIndex: 'candidate_ref', ellipsis: true },
                  {
                    title: '状态',
                    dataIndex: 'status',
                    render: (value: ChangeRegressionStatus) => <StatusTag status={value} />,
                  },
                  { title: '缺失', dataIndex: 'missing_test_count', width: 56 },
                ]}
              />
            </Card>
          </Col>
          <Col xs={24} lg={15}>
            <Card title="端到端证据" loading={state.detail.isLoading}>
              {detail ? (
                <RunDetail run={detail} state={state} />
              ) : (
                <Typography.Text type="secondary">请选择或创建一条链路。</Typography.Text>
              )}
            </Card>
          </Col>
        </Row>
      </Space>
    </Layout>
  )
}

function RunDetail({
  run,
  state,
}: {
  run: ChangeRegressionRun
  state: ReturnType<typeof useChangeRegression>
}) {
  const stageItems = run.stages.map((stage) => ({
    title: stageLabel(stage.stage),
    description: stage.status,
  }))
  const pending = run.missing_tests.filter((item) => item.review_status === 'pending')
  const planGateOpen = Boolean(run.selection_summary.unresolved_current_plan_gap_count)
  return (
    <Space direction="vertical" style={{ width: '100%' }} size={16}>
      <Descriptions size="small" column={2} bordered>
        <Descriptions.Item label="链路">{run.title}</Descriptions.Item>
        <Descriptions.Item label="状态">
          <StatusTag status={run.status} />
        </Descriptions.Item>
        <Descriptions.Item label="来源">{run.source_ref || '未填写'}</Descriptions.Item>
        <Descriptions.Item label="Impact Run">{run.impact_run_id}</Descriptions.Item>
        <Descriptions.Item label="Test Plan Run">
          {run.test_plan_run_id ?? '尚未执行'}
        </Descriptions.Item>
        <Descriptions.Item label="Release Decision">
          {run.release_decision_id ?? '尚未评估'}
        </Descriptions.Item>
      </Descriptions>
      <CoverageDimensionsPanel run={run} state={state} />
      <SemanticPlanGatePanel run={run} state={state} />
      <Steps size="small" current={Math.max(run.stages.length - 1, 0)} items={stageItems} />
      {run.missing_tests.length > 0 && (
        <>
          <Divider titlePlacement="left">Missing Test / ChangeSet Review</Divider>
          <Table
            rowKey="item_id"
            size="small"
            pagination={false}
            dataSource={run.missing_tests}
            columns={[
              { title: '草案', dataIndex: 'title' },
              {
                title: '审核',
                dataIndex: 'review_status',
                render: (value: MissingTestProposal['review_status']) => (
                  <Tag
                    color={
                      value === 'accepted' ? 'green' : value === 'rejected' ? 'default' : 'orange'
                    }
                  >
                    {value}
                  </Tag>
                ),
              },
              {
                title: '操作',
                render: (_: unknown, item: MissingTestProposal) =>
                  item.review_status === 'pending' ? (
                    <Space>
                      <Button
                        size="small"
                        onClick={() =>
                          void state.reviewItem({
                            runId: run.id,
                            itemId: item.item_id,
                            decision: 'accept',
                          })
                        }
                      >
                        接受
                      </Button>
                      <Button
                        size="small"
                        danger
                        onClick={() =>
                          void state.reviewItem({
                            runId: run.id,
                            itemId: item.item_id,
                            decision: 'reject',
                          })
                        }
                      >
                        拒绝
                      </Button>
                    </Space>
                  ) : null,
              },
            ]}
          />
        </>
      )}
      <Space wrap>
        {run.status === 'review_required' && pending.length === 0 && (
          <Button
            type="primary"
            loading={state.acting}
            disabled={planGateOpen}
            onClick={() => void state.approve(run.id)}
          >
            人工批准
          </Button>
        )}
        {run.status === 'approved' && (
          <Button
            type="primary"
            loading={state.acting}
            disabled={planGateOpen}
            onClick={() => void state.execute(run.id)}
          >
            执行回归
          </Button>
        )}
        {run.status === 'evidence_ready' && (
          <Button
            type="primary"
            loading={state.acting}
            onClick={() => void state.evaluateRelease(run.id)}
          >
            评估 Release Gate
          </Button>
        )}
      </Space>
      {Object.keys(run.failure_triage).length > 0 && (
        <FailureTriagePanel value={run.failure_triage} />
      )}
    </Space>
  )
}

function CoverageDimensionsPanel({
  run,
  state,
}: {
  run: ChangeRegressionRun
  state: ReturnType<typeof useChangeRegression>
}) {
  const scopes = run.selection_summary.semantic_coverage_scopes ?? []
  const regenerations = run.selection_summary.operation_regenerations ?? []
  const assetGapCount = run.selection_summary.asset_coverage_gap_count
  const [operationInputs, setOperationInputs] = useState<
    Record<string, { apiDefinitionId?: string; apiVersion?: string }>
  >({})
  const coverageStatus = (dimension: 'project_known_coverage' | 'current_test_plan_coverage') => {
    if (!scopes.length) return '无语义变更目标'
    return scopes.every((scope) => scope[dimension] === 'covered') ? 'covered' : 'missing'
  }
  return (
    <Card size="small" title="Coverage Scope / 位置化语义缺口">
      {regenerations.map((item) => (
        <Alert
          key={item.change_key}
          type={item.status === 'regenerated' ? 'success' : 'info'}
          showIcon
          title={item.status === 'regenerated' ? 'Proposal 已重新生成' : '旧 Proposal 已失效'}
          description={`Contract ${item.contract_fingerprint.slice(0, 12)} · Design ${item.design_fingerprint.slice(0, 12)} · ${item.scenario_count} Scenario / ${item.oracle_count} Oracle`}
          style={{ marginBottom: 12 }}
        />
      ))}
      <Descriptions size="small" bordered column={3}>
        <Descriptions.Item label="Asset Mapping Coverage">
          <CoverageStatus
            value={assetGapCount === undefined ? 'unknown' : assetGapCount ? 'missing' : 'covered'}
          />
        </Descriptions.Item>
        <Descriptions.Item label="Project Known Semantic Coverage">
          <CoverageStatus value={coverageStatus('project_known_coverage')} />
        </Descriptions.Item>
        <Descriptions.Item label="Current Test Plan Semantic Coverage">
          <CoverageStatus value={coverageStatus('current_test_plan_coverage')} />
        </Descriptions.Item>
      </Descriptions>
      {scopes.length ? (
        <Table
          rowKey="change_key"
          size="small"
          pagination={false}
          dataSource={scopes}
          columns={[
            {
              title: 'Service / Operation',
              render: (_: unknown, scope: SemanticCoverageScope) =>
                scope.operation
                  ? `${scope.operation.service_key} · ${scope.operation.method} ${scope.operation.normalized_path}`
                  : 'unresolved',
            },
            {
              title: 'API / Version',
              render: (_: unknown, scope: SemanticCoverageScope) =>
                scope.operation
                  ? `${scope.operation.api_definition_id ?? 'portable'} · v${scope.operation.api_version ?? '?'}`
                  : 'unresolved',
            },
            {
              title: 'Contract / Portable Ref',
              render: (_: unknown, scope: SemanticCoverageScope) =>
                scope.operation
                  ? `${scope.operation.contract_fingerprint.slice(0, 12)} · ${scope.operation.portable_operation_ref}`
                  : 'unresolved',
            },
            {
              title: 'Location',
              render: (_: unknown, scope: SemanticCoverageScope) =>
                scope.target?.location ?? 'unresolved',
            },
            {
              title: 'Field',
              render: (_: unknown, scope: SemanticCoverageScope) =>
                scope.target?.field_path.join('.') ?? 'unresolved',
            },
            {
              title: 'Constraint',
              render: (_: unknown, scope: SemanticCoverageScope) =>
                scope.target?.constraint ?? 'unresolved',
            },
            {
              title: 'Before → After',
              render: (_: unknown, scope: SemanticCoverageScope) =>
                scope.target
                  ? `${JSON.stringify(scope.target.before)} → ${JSON.stringify(scope.target.after)}`
                  : '-',
            },
            {
              title: 'Existing Values',
              render: (_: unknown, scope: SemanticCoverageScope) =>
                scope.project_known_values.join(', ') || '无',
            },
            {
              title: 'Missing Values',
              render: (_: unknown, scope: SemanticCoverageScope) =>
                scope.current_test_plan_missing_values.join(', ') || '无',
            },
            {
              title: 'Oracle Source',
              render: (_: unknown, scope: SemanticCoverageScope) =>
                scope.oracle_sources
                  .map((source) => `${source.source_type}:${source.source_ref}`)
                  .join(', ') || '待审核',
            },
            {
              title: 'Operation Selection',
              render: (_: unknown, scope: SemanticCoverageScope) => {
                if (!scope.requires_review) return <Tag color="green">Frozen</Tag>
                const input = operationInputs[scope.change_key] ?? {}
                const version = Number(input.apiVersion)
                return (
                  <Space orientation="vertical" size={4}>
                    <Input
                      size="small"
                      aria-label={`API Definition ${scope.change_key}`}
                      placeholder="API Definition UUID"
                      value={input.apiDefinitionId}
                      onChange={(event) =>
                        setOperationInputs((current) => ({
                          ...current,
                          [scope.change_key]: {
                            ...current[scope.change_key],
                            apiDefinitionId: event.target.value,
                          },
                        }))
                      }
                    />
                    <Input
                      size="small"
                      type="number"
                      min={1}
                      aria-label={`API Version ${scope.change_key}`}
                      placeholder="Pinned API Version"
                      value={input.apiVersion}
                      onChange={(event) =>
                        setOperationInputs((current) => ({
                          ...current,
                          [scope.change_key]: {
                            ...current[scope.change_key],
                            apiVersion: event.target.value,
                          },
                        }))
                      }
                    />
                    <Button
                      size="small"
                      loading={state.acting}
                      disabled={!input.apiDefinitionId || !Number.isInteger(version) || version < 1}
                      onClick={() =>
                        void state.selectOperation({
                          runId: run.id,
                          changeKey: scope.change_key,
                          apiDefinitionId: input.apiDefinitionId ?? '',
                          apiVersion: version,
                        })
                      }
                    >
                      冻结并重新生成 Proposal
                    </Button>
                  </Space>
                )
              },
            },
          ]}
        />
      ) : null}
    </Card>
  )
}

function SemanticPlanGatePanel({
  run,
  state,
}: {
  run: ChangeRegressionRun
  state: ReturnType<typeof useChangeRegression>
}) {
  const gaps = currentPlanGaps(run)
  const unresolved = Number(run.selection_summary.unresolved_current_plan_gap_count)
  const [reasons, setReasons] = useState<Record<string, string>>({})
  const [expiries, setExpiries] = useState<Record<string, string>>({})
  const environmentId = currentPlanEnvironmentId(run, state)

  if (!gaps.length) return null
  return (
    <Card
      size="small"
      title="Current TestPlan Semantic Gate"
      extra={<CoverageStatus value={unresolved > 0 ? 'MISSING' : 'COVERED'} />}
    >
      {unresolved > 0 ? (
        <Alert
          type="error"
          showIcon
          title={`${unresolved} 个当前计划语义缺口尚未解决`}
          description="Approve、Execute 和 Release Gate 均由后端重新计算并阻断；请加入精确覆盖的已有测试，或逐 Gap 创建人工豁免。"
          style={{ marginBottom: 12 }}
        />
      ) : null}
      <Descriptions size="small" bordered column={5} style={{ marginBottom: 12 }}>
        <Descriptions.Item label="Asset Mapping">
          {run.selection_summary.asset_mapping_gap_count ?? 0}
        </Descriptions.Item>
        <Descriptions.Item label="Project Gap">
          {run.selection_summary.project_semantic_gap_count ?? 0}
        </Descriptions.Item>
        <Descriptions.Item label="Current Plan Gap">
          {run.selection_summary.current_test_plan_semantic_gap_count ?? 0}
        </Descriptions.Item>
        <Descriptions.Item label="Waived">
          {run.selection_summary.waived_current_plan_gap_count ?? 0}
        </Descriptions.Item>
        <Descriptions.Item label="Unresolved">{unresolved}</Descriptions.Item>
      </Descriptions>
      <SemanticCoverageBasis run={run} />
      <Space orientation="vertical" style={{ width: '100%' }} size={12}>
        {gaps.map((gap) => (
          <SemanticGapCard
            key={gap.gap_key}
            gap={gap}
            run={run}
            state={state}
            environmentId={environmentId}
            reason={reasons[gap.gap_key] ?? ''}
            expiry={expiries[gap.gap_key]}
            latestWaiver={latestGapWaiver(run, gap.gap_key)}
            onReason={(value) => setReasons((current) => ({ ...current, [gap.gap_key]: value }))}
            onExpiry={(value) => setExpiries((current) => ({ ...current, [gap.gap_key]: value }))}
          />
        ))}
      </Space>
      {run.semantic_gap_waivers.length > 0 ? (
        <>
          <Divider titlePlacement="left">Waiver Revision History</Divider>
          <Table
            rowKey="id"
            size="small"
            pagination={false}
            dataSource={run.semantic_gap_waivers}
            columns={[
              { title: 'Gap', dataIndex: 'gap_key', ellipsis: true },
              { title: 'Revision', dataIndex: 'revision', width: 82 },
              {
                title: 'Supersedes',
                dataIndex: 'supersedes_waiver_id',
                render: (value: string | null) => value?.slice(0, 12) ?? '-',
              },
              { title: 'Approved By', dataIndex: 'approved_by_id', ellipsis: true },
              { title: 'Approved At', dataIndex: 'approved_at' },
              {
                title: 'Expires At',
                dataIndex: 'expires_at',
                render: (value: string | null) => value ?? '不过期',
              },
              {
                title: 'State',
                dataIndex: 'active',
                render: (active: boolean) => (
                  <Tag color={active ? 'green' : 'default'}>{active ? 'Active' : 'Expired'}</Tag>
                ),
              },
            ]}
          />
        </>
      ) : null}
    </Card>
  )
}

function SemanticCoverageBasis({ run }: { run: ChangeRegressionRun }) {
  const executionRunId = run.selection_summary.semantic_coverage_test_plan_run_id
  const basis = coverageBasisLabel(run.selection_summary.semantic_coverage_basis, executionRunId)
  const generatedCount = run.selection_summary.generated_assets?.length ?? 0
  const runtime = run.selection_summary.runtime_coverage
  return (
    <>
      <Typography.Paragraph type="secondary">Coverage Basis: {basis}</Typography.Paragraph>
      {runtime ? (
        <Typography.Paragraph type="secondary">
          Runtime Match: {runtime.matched_semantic_fact_count} facts ·{' '}
          {runtime.passed_api_node_count} passed API nodes · {runtime.workflow_execution_count}{' '}
          workflow executions
        </Typography.Paragraph>
      ) : null}
      {generatedCount > 0 ? (
        <Alert
          type="info"
          showIcon
          title={`Generated Assets · ${generatedCount}`}
          description="物化资产必须先由人工发布，再按推荐的固定版本显式加入当前计划；系统不会自动发布或执行。"
          style={{ marginBottom: 12 }}
        />
      ) : null}
    </>
  )
}

function coverageBasisLabel(
  basis: ChangeRegressionRun['selection_summary']['semantic_coverage_basis'],
  executionRunId?: string | null,
): string {
  if (basis === 'runtime_node_evidence') {
    return `实际节点证据 · ${executionRunId?.slice(0, 12) ?? '-'}`
  }
  if (basis === 'test_plan_run') {
    return `历史执行快照 · ${executionRunId?.slice(0, 12) ?? '-'}`
  }
  return '当前计划固定版本'
}

function SemanticGapCard({
  gap,
  run,
  state,
  environmentId,
  reason,
  expiry,
  latestWaiver,
  onReason,
  onExpiry,
}: {
  gap: CurrentPlanGap
  run: ChangeRegressionRun
  state: ReturnType<typeof useChangeRegression>
  environmentId?: string
  reason: string
  expiry?: string
  latestWaiver?: ChangeRegressionRun['semantic_gap_waivers'][number]
  onReason: (value: string) => void
  onExpiry: (value: string) => void
}) {
  return (
    <Card
      size="small"
      type="inner"
      title={semanticGapOperationLabel(gap)}
      extra={<CoverageStatus value={gap.coverage_status} />}
    >
      <Descriptions size="small" column={3} bordered>
        <Descriptions.Item label="Field">{semanticGapFieldLabel(gap)}</Descriptions.Item>
        <Descriptions.Item label="Value / Category">
          {gap.semantic_requirement.semantic_value ?? '?'} ·{' '}
          {gap.semantic_requirement.expected_category ?? 'unknown'}
        </Descriptions.Item>
        <Descriptions.Item label="Oracle Set">
          {gap.semantic_requirement.oracle_set_fingerprint?.slice(0, 12) ?? 'unknown'}
        </Descriptions.Item>
        <Descriptions.Item label="Oracle Reachability">
          <OracleReachability values={gap.oracle_reachability} />
        </Descriptions.Item>
        <Descriptions.Item label="Existing Asset">
          <SemanticGapExistingAsset
            gap={gap}
            run={run}
            state={state}
            environmentId={environmentId}
          />
        </Descriptions.Item>
        <Descriptions.Item label="Waiver Reason">
          <SemanticGapReason gap={gap} reason={reason} onReason={onReason} />
        </Descriptions.Item>
        <Descriptions.Item label="Waiver Expiry">
          <SemanticGapExpiry gap={gap} onExpiry={onExpiry} />
        </Descriptions.Item>
      </Descriptions>
      <SemanticGapWaiverAction gap={gap} run={run} state={state} reason={reason} expiry={expiry} />
      {!gap.waiver && latestWaiver ? (
        <Typography.Text type="secondary" style={{ marginLeft: 8 }}>
          Revision {latestWaiver.revision} 已失效；新豁免会创建下一 Revision，并保留历史记录。
        </Typography.Text>
      ) : null}
    </Card>
  )
}

function semanticGapOperationLabel(gap: CurrentPlanGap): string {
  if (!gap.operation) return 'AMBIGUOUS / UNKNOWN'
  return `${gap.operation.service_key} · ${gap.operation.method} ${gap.operation.normalized_path} · v${gap.operation.api_version ?? '?'}`
}

function semanticGapFieldLabel(gap: CurrentPlanGap): string {
  return gap.target ? `${gap.target.location}.${gap.target.field_path.join('.')}` : 'unresolved'
}

function SemanticGapExistingAsset({
  gap,
  run,
  state,
  environmentId,
}: {
  gap: CurrentPlanGap
  run: ChangeRegressionRun
  state: ReturnType<typeof useChangeRegression>
  environmentId?: string
}) {
  const asset = gap.recommended_existing_assets[0]
  if (!asset) return <>无精确匹配资产</>
  const replacing = ['VERSION_MISMATCH', 'CONTRACT_MISMATCH'].includes(gap.coverage_status)
  return (
    <Button
      size="small"
      disabled={gap.coverage_status === 'COVERED' || gap.coverage_status === 'WAIVED'}
      onClick={() =>
        void state.addToPlan({
          runId: run.id,
          gapKey: gap.gap_key,
          targetType: asset.target_type,
          targetId: asset.target_id,
          targetVersion: asset.target_version,
          workflowVersion: asset.workflow_version,
          environmentId,
        })
      }
    >
      {replacing ? 'Replace Plan Version' : 'Add to Plan'} · {asset.target_type} v
      {asset.target_version}
    </Button>
  )
}

function SemanticGapReason({
  gap,
  reason,
  onReason,
}: {
  gap: CurrentPlanGap
  reason: string
  onReason: (value: string) => void
}) {
  if (!gap.waiver) {
    return (
      <Input
        value={reason}
        maxLength={1000}
        placeholder="至少 10 字，说明发布风险与补偿措施"
        onChange={(event) => onReason(event.target.value)}
      />
    )
  }
  return (
    <Space orientation="vertical" size={0}>
      <Typography.Text>{gap.waiver.reason}</Typography.Text>
      <Typography.Text type="secondary">
        Revision {gap.waiver.revision} · Approver: {gap.waiver.approved_by}
      </Typography.Text>
      <Typography.Text type="secondary">
        Supersedes: {gap.waiver.supersedes_waiver_id?.slice(0, 12) ?? '-'}
      </Typography.Text>
    </Space>
  )
}

function SemanticGapExpiry({
  gap,
  onExpiry,
}: {
  gap: CurrentPlanGap
  onExpiry: (value: string) => void
}) {
  if (gap.waiver) return <>{gap.waiver.expires_at ?? '不过期'}</>
  return (
    <Input
      type="datetime-local"
      aria-label={`Waiver Expiry ${gap.gap_key}`}
      onChange={(event) =>
        onExpiry(event.target.value ? new Date(event.target.value).toISOString() : '')
      }
    />
  )
}

function SemanticGapWaiverAction({
  gap,
  run,
  state,
  reason,
  expiry,
}: {
  gap: CurrentPlanGap
  run: ChangeRegressionRun
  state: ReturnType<typeof useChangeRegression>
  reason: string
  expiry?: string
}) {
  if (gap.waiver || gap.coverage_status === 'COVERED') return null
  return (
    <Button
      size="small"
      danger
      style={{ marginTop: 12 }}
      disabled={reason.trim().length < 10}
      onClick={() =>
        void state.waiveGap({
          runId: run.id,
          gapKey: gap.gap_key,
          reason: reason.trim(),
          expiresAt: expiry || undefined,
        })
      }
    >
      {latestGapWaiver(run, gap.gap_key) ? 'Renew Waiver' : '人工豁免'}
    </Button>
  )
}

function latestGapWaiver(run: ChangeRegressionRun, gapKey: string) {
  return run.semantic_gap_waivers
    .filter((waiver) => waiver.gap_key === gapKey)
    .sort((left, right) => right.revision - left.revision)[0]
}

function OracleReachability({ values }: { values: CurrentPlanGap['oracle_reachability'] }) {
  if (!values.length) return <Tag>Unknown Graph</Tag>
  const labels: Record<(typeof values)[number], string> = {
    direct_oracle: 'Direct Oracle',
    unconditional_assert: 'Unconditional Assert',
    conditional_assert: 'Conditional Assert',
    disconnected_assert: 'Disconnected Assert',
    unknown_graph: 'Unknown Graph',
  }
  return (
    <Space wrap>
      {values.map((value) => (
        <Tag
          key={value}
          color={value === 'direct_oracle' || value === 'unconditional_assert' ? 'green' : 'orange'}
        >
          {labels[value]}
        </Tag>
      ))}
    </Space>
  )
}

function currentPlanGaps(run: ChangeRegressionRun): CurrentPlanGap[] {
  const value = run.selection_summary.current_plan_gaps
  return Array.isArray(value) ? value : []
}

function currentPlanEnvironmentId(
  run: ChangeRegressionRun,
  state: ReturnType<typeof useChangeRegression>,
): string | undefined {
  const plans = state.plans.data ? state.plans.data.items : []
  const plan = plans.find((item) => item.id === run.test_plan_id)
  if (!plan) return undefined
  const item = plan.items.find((candidate) => candidate.environment_id)
  return item && item.environment_id ? item.environment_id : undefined
}

function CoverageStatus({ value }: { value: string }) {
  const normalized = value.toUpperCase()
  const color =
    normalized === 'COVERED'
      ? 'green'
      : normalized === 'WAIVED'
        ? 'gold'
        : normalized === 'PARTIAL'
          ? 'orange'
          : normalized === 'MISSING'
            ? 'red'
            : normalized === 'VERSION_MISMATCH'
              ? 'magenta'
              : normalized === 'CONTRACT_MISMATCH'
                ? 'volcano'
                : 'default'
  return <Tag color={color}>{value}</Tag>
}

function FailureTriagePanel({ value }: { value: ChangeRegressionRun['failure_triage'] }) {
  if (!isFailureTriageV2(value)) {
    return (
      <Alert
        type="warning"
        showIcon
        title="历史 Failure Triage 证据不含 S47 结构化分类"
        description="请重新执行回归以生成 classification、confidence、evidence refs 和建议动作。"
      />
    )
  }
  return (
    <Card
      size="small"
      title="Failure Triage v2"
      extra={<Tag color="red">{value.primary_classification}</Tag>}
    >
      <Space orientation="vertical" style={{ width: '100%' }}>
        <Descriptions size="small" bordered column={2}>
          <Descriptions.Item label="Confidence">
            {(value.confidence * 100).toFixed(0)}%
          </Descriptions.Item>
          <Descriptions.Item label="Retry Signal">
            {value.retry_signal ? '是' : '否'}
          </Descriptions.Item>
          <Descriptions.Item label="Affected Service">
            {value.affected_service ?? '未定位'}
          </Descriptions.Item>
          <Descriptions.Item label="Endpoint Variant">
            {value.endpoint_variant ?? '未定位'}
          </Descriptions.Item>
          <Descriptions.Item label="Affected Operation">
            {value.affected_operation ?? '未定位'}
          </Descriptions.Item>
          <Descriptions.Item label="Evidence Refs">{value.evidence_refs.length}</Descriptions.Item>
          <Descriptions.Item label="Secondary">
            {value.secondary_candidates.join(', ') || '无'}
          </Descriptions.Item>
        </Descriptions>
        <Alert
          showIcon
          type="warning"
          title="执行失败已生成 Failure Triage 证据"
          description={value.recommended_action}
        />
        <Space wrap>
          {value.reason_codes.map((reason) => (
            <Tag key={reason}>{reason}</Tag>
          ))}
        </Space>
        {value.recommended_regression.length ? (
          <Typography.Text>建议回归：{value.recommended_regression.join('、')}</Typography.Text>
        ) : null}
      </Space>
    </Card>
  )
}

function isFailureTriageV2(
  value: ChangeRegressionRun['failure_triage'],
): value is FailureTriageResult {
  return (
    value.algorithm_version === 's47-failure-triage-v2' &&
    typeof value.primary_classification === 'string' &&
    Array.isArray(value.evidence_refs)
  )
}

function StatusTag({ status }: { status: ChangeRegressionStatus }) {
  const color: Record<ChangeRegressionStatus, string> = {
    review_required: 'orange',
    approved: 'blue',
    queued: 'cyan',
    running: 'processing',
    evidence_ready: 'purple',
    passed: 'green',
    blocked: 'red',
    failed: 'red',
  }
  return <Tag color={color[status]}>{status}</Tag>
}

function stageLabel(stage: string): string {
  const labels: Record<string, string> = {
    change: 'Change',
    impact: 'Impact',
    regression_selection: 'Regression Selection',
    missing_test: 'Missing Test',
    review: 'Review',
    execution: 'Execution',
    evidence: 'Evidence',
    release_gate: 'Release Gate',
    failure_triage: 'Failure Triage',
  }
  return labels[stage] ?? stage
}
