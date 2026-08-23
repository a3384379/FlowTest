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
import type {
  ChangeRegressionRun,
  ChangeRegressionStatus,
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
              extra="缺失覆盖会生成 Test Design 草案，不会自动发布或执行。"
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
      <CoverageDimensionsPanel run={run} />
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
          <Button type="primary" loading={state.acting} onClick={() => void state.approve(run.id)}>
            人工批准
          </Button>
        )}
        {run.status === 'approved' && (
          <Button type="primary" loading={state.acting} onClick={() => void state.execute(run.id)}>
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

function CoverageDimensionsPanel({ run }: { run: ChangeRegressionRun }) {
  const scopes = run.selection_summary.semantic_coverage_scopes ?? []
  const assetGapCount = run.selection_summary.asset_coverage_gap_count
  const coverageStatus = (dimension: 'project_known_coverage' | 'current_test_plan_coverage') => {
    if (!scopes.length) return '无语义变更目标'
    return scopes.every((scope) => scope[dimension] === 'covered') ? 'covered' : 'missing'
  }
  return (
    <Card size="small" title="Coverage Scope / 位置化语义缺口">
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
              title: 'Operation',
              render: (_: unknown, scope: SemanticCoverageScope) =>
                scope.operation
                  ? `${scope.operation.service_key} · ${scope.operation.method} ${scope.operation.normalized_path}`
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
          ]}
        />
      ) : null}
    </Card>
  )
}

function CoverageStatus({ value }: { value: string }) {
  const color = value === 'covered' ? 'green' : value === 'missing' ? 'red' : 'default'
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
