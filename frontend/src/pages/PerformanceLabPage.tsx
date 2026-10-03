import {
  CheckCircleOutlined,
  ExperimentOutlined,
  PlusOutlined,
  RocketOutlined,
} from '@ant-design/icons'
import {
  Alert,
  Button,
  Descriptions,
  Empty,
  Spin,
  Tabs,
  Card,
  Col,
  Form,
  Input,
  InputNumber,
  Modal,
  Radio,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
} from 'antd'
import { useState } from 'react'

import type {
  LoadExecutor,
  PerformanceRun,
  PerformanceScenarioInput,
  PerformanceScenario,
  PerformanceDefinition,
} from '../features/performance/performance-service'
import { apiErrorMessage } from '../lib/api'
import { downloadPerformanceMetrics } from '../features/performance/performance-service'
import ResponseCodeReader from '../features/api-console/ResponseCodeReader'
import { usePerformanceLab } from '../features/performance/use-performance-lab'

type ScenarioForm = {
  name: string
  description?: string
  step_name: string
  method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  url: string
  expected_status: number
  executor: LoadExecutor
  vus: number
  duration_seconds: number
  start_vus: number
  ramp_target_vus: number
  ramp_duration_seconds: number
  p95_limit_ms: number
  failed_rate_limit: number
}

export default function PerformanceLabPage() {
  const state = usePerformanceLab()
  const [createOpen, setCreateOpen] = useState(false)
  const [versionBase, setVersionBase] = useState<PerformanceScenario | null>(null)
  const scenarios = state.scenarios.data?.items ?? []
  const runs = state.runs.data?.items ?? []
  const latest = runs.at(0)
  return (
    <>
      <div className="page-heading">
        <div>
          <Typography.Title level={2}>性能实验室</Typography.Title>
          <Typography.Text type="secondary">
            使用声明式场景生成平台内部 k6 程序，统一管理负载、阈值、基线与发布门禁。
          </Typography.Text>
        </div>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          disabled={!state.canEdit}
          onClick={() => setCreateOpen(true)}
        >
          新建性能场景
        </Button>
      </div>
      <PerformanceOverview
        scenarios={state.scenarios.data?.total}
        runs={state.runs.data?.total}
        latest={latest}
      />
      <LabReadErrors state={state} />
      <div className="lab-workspace">
        <div className="lab-catalogs">
          <Card title="性能场景" className="performance-card" loading={state.scenarios.isLoading}>
            <Table
              rowKey="id"
              size="small"
              pagination={{
                current: state.scenarioPage,
                pageSize: 20,
                total: state.scenarios.data?.total,
                showSizeChanger: false,
                onChange: state.setScenarioPage,
              }}
              dataSource={scenarios}
              locale={{ emptyText: '暂无性能场景' }}
              columns={[
                {
                  title: '名称',
                  render: (_, row) => (
                    <Button type="link" onClick={() => state.selectObject('scenario', row.id)}>
                      {row.name}
                    </Button>
                  ),
                },
                { title: '版本', dataIndex: 'version', width: 80, render: (value) => `v${value}` },
                {
                  title: '目标',
                  dataIndex: 'target_type',
                  render: (value) => (value === 'rest' ? 'REST' : '纯 HTTP Workflow'),
                },
                {
                  title: '负载',
                  render: (_, row) => loadDescription(row.definition),
                },
                {
                  title: '状态',
                  dataIndex: 'status',
                  render: (value) => (
                    <Tag color={value === 'published' ? 'success' : 'default'}>
                      {value === 'published' ? '已发布' : '草稿'}
                    </Tag>
                  ),
                },
                {
                  title: '操作',
                  width: 180,
                  render: (_, row) => (
                    <Space>
                      <Button
                        type="link"
                        disabled={!state.canEdit}
                        onClick={() => setVersionBase(row)}
                      >
                        新建版本
                      </Button>
                      {row.status === 'draft' ? (
                        <Button
                          type="link"
                          loading={state.publishing}
                          disabled={!state.canEdit}
                          onClick={() => void state.publishScenario(row.id)}
                        >
                          发布
                        </Button>
                      ) : (
                        <Button
                          type="link"
                          icon={<RocketOutlined />}
                          loading={state.starting}
                          disabled={!state.canEdit}
                          onClick={() => void state.startRun(row.id)}
                        >
                          运行
                        </Button>
                      )}
                    </Space>
                  ),
                },
              ]}
            />
          </Card>
          <Card title="运行与基线" className="performance-card" loading={state.runs.isLoading}>
            <Table
              rowKey="id"
              size="small"
              pagination={{
                current: state.runPage,
                pageSize: 20,
                total: state.runs.data?.total,
                showSizeChanger: false,
                onChange: state.setRunPage,
              }}
              dataSource={runs}
              locale={{ emptyText: '暂无性能运行' }}
              expandable={{ expandedRowRender: (run) => <RunEvidence run={run} /> }}
              columns={[
                {
                  title: '运行 ID',
                  render: (_, row) => (
                    <Button type="link" onClick={() => state.selectObject('run', row.id)}>
                      {row.id.slice(0, 8)}
                    </Button>
                  ),
                },
                {
                  title: '状态',
                  dataIndex: 'status',
                  render: (value) => <RunStatus status={value} />,
                },
                {
                  title: 'P95',
                  render: (_, run) => metric(run.summary.http_req_duration_p95_ms, ' ms'),
                },
                {
                  title: '请求速率',
                  render: (_, run) => metric(run.summary.http_reqs_rate, ' req/s'),
                },
                {
                  title: '基线回归',
                  render: (_, run) => regression(run.summary.p95_regression_percent),
                },
                {
                  title: '门禁',
                  render: (_, run) => gateStatus(run),
                },
              ]}
            />
          </Card>
        </div>
        <PerformanceDetail state={state} />
      </div>
      <VersionScenarioDialog
        key={versionBase ? versionBase.id : 'none'}
        base={versionBase}
        submitting={state.versioning}
        onClose={() => setVersionBase(null)}
        onCreate={async (description, definition) => {
          if (versionBase && (await state.addVersion(versionBase.id, description, definition)))
            setVersionBase(null)
        }}
      />
      <CreateScenarioDialog
        open={createOpen}
        submitting={state.creating}
        onClose={() => setCreateOpen(false)}
        onCreate={async (input) => {
          if (await state.addScenario(input)) setCreateOpen(false)
        }}
      />
    </>
  )
}

function PerformanceOverview({
  scenarios,
  runs,
  latest,
}: {
  scenarios: number | undefined
  runs: number | undefined
  latest: PerformanceRun | undefined
}) {
  return (
    <Row gutter={16} className="performance-overview">
      <Col span={6}>
        <Card>
          <Statistic
            title="场景版本"
            value={scenarios ?? '未提供'}
            prefix={<ExperimentOutlined />}
          />
        </Card>
      </Col>
      <Col span={6}>
        <Card>
          <Statistic title="运行总数" value={runs ?? '未提供'} />
        </Card>
      </Col>
      <Col span={6}>
        <Card>
          <Statistic
            title="本页最近 P95"
            value={latest?.summary.http_req_duration_p95_ms ?? '未提供'}
            suffix="ms"
          />
        </Card>
      </Col>
      <Col span={6}>
        <Card>
          <Statistic
            title="基线回归"
            value={latest?.summary.p95_regression_percent ?? '未提供'}
            suffix="%"
          />
        </Card>
      </Col>
    </Row>
  )
}

function CreateScenarioDialog({
  open,
  submitting,
  onClose,
  onCreate,
}: {
  open: boolean
  submitting: boolean
  onClose: () => void
  onCreate: (input: PerformanceScenarioInput) => Promise<void>
}) {
  const [form] = Form.useForm<ScenarioForm>()
  const executor = Form.useWatch('executor', form) ?? 'constant_vus'
  return (
    <Modal
      title="新建声明式性能场景"
      open={open}
      width={760}
      confirmLoading={submitting}
      onCancel={onClose}
      onOk={() => form.submit()}
      destroyOnHidden
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={defaultFormValues}
        onFinish={(value) => void onCreate(toScenarioInput(value))}
      >
        <Row gutter={16}>
          <Col span={12}>
            <Form.Item name="name" label="场景名称" rules={[{ required: true }]}>
              <Input maxLength={160} />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="description" label="说明">
              <Input maxLength={500} />
            </Form.Item>
          </Col>
        </Row>
        <Typography.Title level={5}>HTTP 步骤</Typography.Title>
        <Row gutter={16}>
          <Col span={8}>
            <Form.Item name="step_name" label="步骤名称" rules={[{ required: true }]}>
              <Input />
            </Form.Item>
          </Col>
          <Col span={5}>
            <Form.Item name="method" label="方法">
              <Select
                options={['GET', 'POST', 'PUT', 'PATCH', 'DELETE'].map((value) => ({ value }))}
              />
            </Form.Item>
          </Col>
          <Col span={11}>
            <Form.Item
              name="url"
              label="目标 URL"
              rules={[{ required: true }, { validator: validateHttpTarget }]}
            >
              <Input placeholder="https://api.example.com/orders" />
            </Form.Item>
          </Col>
        </Row>
        <Row gutter={16}>
          <Col span={8}>
            <Form.Item name="expected_status" label="期望状态码">
              <InputNumber min={100} max={599} />
            </Form.Item>
          </Col>
          <Col span={16}>
            <Form.Item name="executor" label="负载模型">
              <Radio.Group
                options={[
                  { label: '固定 VU', value: 'constant_vus' },
                  { label: '阶梯升压', value: 'ramping_vus' },
                ]}
              />
            </Form.Item>
          </Col>
        </Row>
        {executor === 'constant_vus' ? (
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item name="vus" label="VU">
                <InputNumber min={1} max={1000} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="duration_seconds" label="持续时间（秒）">
                <InputNumber min={1} max={3600} />
              </Form.Item>
            </Col>
          </Row>
        ) : (
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item name="start_vus" label="起始 VU">
                <InputNumber min={0} max={1000} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="ramp_target_vus" label="目标 VU">
                <InputNumber min={1} max={1000} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="ramp_duration_seconds" label="升压时间（秒）">
                <InputNumber min={1} max={3600} />
              </Form.Item>
            </Col>
          </Row>
        )}
        <Typography.Title level={5}>质量阈值</Typography.Title>
        <Row gutter={16}>
          <Col span={8}>
            <Form.Item name="p95_limit_ms" label="P95 上限（ms）">
              <InputNumber min={1} />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="failed_rate_limit" label="失败率上限（0~1）">
              <InputNumber min={0} max={1} step={0.001} />
            </Form.Item>
          </Col>
        </Row>
        <Typography.Text type="secondary">
          平台仅接受结构化配置，不允许上传 JavaScript；运行时固定禁止重定向并丢弃响应体。
        </Typography.Text>
      </Form>
    </Modal>
  )
}

const defaultFormValues: ScenarioForm = {
  name: '',
  description: '',
  step_name: '接口请求',
  method: 'GET',
  url: '',
  expected_status: 200,
  executor: 'constant_vus',
  vus: 5,
  duration_seconds: 30,
  start_vus: 0,
  ramp_target_vus: 20,
  ramp_duration_seconds: 60,
  p95_limit_ms: 500,
  failed_rate_limit: 0.01,
}

async function validateHttpTarget(_: unknown, value?: string): Promise<void> {
  if (!value) return
  try {
    const target = new URL(value)
    if (!['http:', 'https:'].includes(target.protocol)) throw new Error('unsupported protocol')
  } catch {
    throw new Error('请输入有效的 HTTP 或 HTTPS URL')
  }
}

function toScenarioInput(value: ScenarioForm): PerformanceScenarioInput {
  const constant = value.executor === 'constant_vus'
  return {
    name: value.name,
    description: value.description ?? '',
    definition: {
      executor: value.executor,
      steps: [
        {
          name: value.step_name,
          method: value.method,
          url: value.url,
          headers: {},
          body: null,
          expected_statuses: [value.expected_status],
          pause_seconds: 0,
        },
      ],
      thresholds: [
        {
          metric: 'http_req_duration',
          aggregation: 'p(95)',
          operator: '<',
          value: value.p95_limit_ms,
          abort_on_fail: false,
          delay_abort_seconds: 0,
        },
        {
          metric: 'http_req_failed',
          aggregation: 'rate',
          operator: '<=',
          value: value.failed_rate_limit,
          abort_on_fail: false,
          delay_abort_seconds: 0,
        },
      ],
      vus: constant ? value.vus : null,
      duration_seconds: constant ? value.duration_seconds : null,
      start_vus: constant ? null : value.start_vus,
      stages: constant
        ? []
        : [{ duration_seconds: value.ramp_duration_seconds, target_vus: value.ramp_target_vus }],
      graceful_stop_seconds: 30,
    },
  }
}

function loadDescription(definition: PerformanceRun['definition_snapshot']): string {
  if (definition.executor === 'constant_vus') {
    return `${definition.vus} VU / ${definition.duration_seconds}s`
  }
  const target = Math.max(...definition.stages.map((stage) => stage.target_vus))
  const duration = definition.stages.reduce((total, stage) => total + stage.duration_seconds, 0)
  return `${definition.start_vus} → ${target} VU / ${duration}s`
}

function RunStatus({ status }: { status: PerformanceRun['status'] }) {
  const colors = {
    queued: 'default',
    running: 'processing',
    passed: 'success',
    failed: 'error',
    cancelled: 'warning',
  }
  const labels = {
    queued: '排队中',
    running: '运行中',
    passed: '通过',
    failed: '失败',
    cancelled: '已取消',
  }
  return <Tag color={colors[status]}>{labels[status]}</Tag>
}

function RunEvidence({ run }: { run: PerformanceRun }) {
  return (
    <div className="performance-evidence">
      <Typography.Text strong>阈值证据</Typography.Text>
      <Space wrap>
        {run.threshold_results.map((item) => (
          <Tag key={`${item.metric}-${item.expression}`} color={item.passed ? 'success' : 'error'}>
            {item.metric} {item.expression}
          </Tag>
        ))}
      </Space>
      {run.gate_evaluations
        .flatMap((evaluation) => evaluation.violations)
        .map((violation) => (
          <Typography.Text key={violation} type="danger">
            {violation}
          </Typography.Text>
        ))}
      {run.raw_metrics_artifact_id ? (
        <Tag icon={<CheckCircleOutlined />} color="blue">
          原始指标已保存至 MinIO
        </Tag>
      ) : null}
      {run.error_message ? (
        <Typography.Text type="danger">{run.error_message}</Typography.Text>
      ) : null}
    </div>
  )
}

function metric(value: number | null | undefined, suffix: string): string {
  return typeof value === 'number' ? `${value.toFixed(2)}${suffix}` : '—'
}

function regression(value: number | null | undefined) {
  if (typeof value !== 'number') return <Typography.Text type="secondary">无基线</Typography.Text>
  return (
    <Tag>
      {value > 0 ? '+' : ''}
      {value.toFixed(2)}%
    </Tag>
  )
}

function gateStatus(run: PerformanceRun) {
  if (!run.gate_evaluations.length)
    return <Typography.Text type="secondary">未配置</Typography.Text>
  const failed = run.gate_evaluations.some((item) => item.status === 'failed')
  return <Tag color={failed ? 'error' : 'success'}>{failed ? '阻断' : '通过'}</Tag>
}

function LabReadErrors({ state }: { state: ReturnType<typeof usePerformanceLab> }) {
  const reads = [
    { query: state.scenarios, name: '场景目录' },
    { query: state.runs, name: '运行目录' },
    { query: state.permissions, name: '项目权限' },
  ]
  return (
    <>
      {reads
        .filter((read) => read.query.isError)
        .map((read) => (
          <Alert
            key={read.name}
            type="error"
            showIcon
            title={`${read.name}读取失败`}
            description={apiErrorMessage(read.query.error)}
            action={<Button onClick={() => void read.query.refetch()}>重试</Button>}
          />
        ))}
    </>
  )
}

function PerformanceDetail({ state }: { state: ReturnType<typeof usePerformanceLab> }) {
  if (!state.runId && !state.scenarioId)
    return (
      <Card className="lab-detail" title="配置与冻结结果">
        <Empty description="选择场景审阅配置，或选择运行查看冻结证据" />
      </Card>
    )
  const query = state.runId ? state.runDetail : state.scenario
  if (query.isError)
    return (
      <Card className="lab-detail">
        <Alert
          showIcon
          type="error"
          title="所选对象读取失败"
          description={apiErrorMessage(query.error)}
          action={<Button onClick={() => void query.refetch()}>重试</Button>}
        />
      </Card>
    )
  if (query.isPending)
    return (
      <Card className="lab-detail">
        <Spin aria-label="正在读取所选对象" />
      </Card>
    )
  if (state.runId)
    return <RunWorkspaceInProject run={state.runDetail.data} projectId={state.projectId} />
  return <ScenarioWorkspace scenario={state.scenario.data} projectId={state.projectId} />
}

function RunWorkspaceInProject({
  run,
  projectId,
}: {
  run: PerformanceRun | undefined
  projectId: string | null
}) {
  if (!run || run.project_id !== projectId)
    return (
      <Card className="lab-detail">
        <Alert type="error" title="所选对象不属于当前项目" />
      </Card>
    )
  return <PerformanceRunWorkspace key={run.id} run={run} />
}

function ScenarioWorkspace({
  scenario,
  projectId,
}: {
  scenario: PerformanceScenario | undefined
  projectId: string | null
}) {
  if (!scenario || scenario.project_id !== projectId)
    return (
      <Card className="lab-detail">
        <Alert type="error" title="所选对象不属于当前项目" />
      </Card>
    )
  return (
    <Card className="lab-detail" title={`${scenario.name} · v${scenario.version}`}>
      <Descriptions column={1} size="small">
        <Descriptions.Item label="版本 ID">{scenario.id}</Descriptions.Item>
        <Descriptions.Item label="发布状态">
          {scenario.status === 'published' ? '已发布' : '草稿'}
        </Descriptions.Item>
        <Descriptions.Item label="发布于">{scenario.published_at ?? '尚未发布'}</Descriptions.Item>
        <Descriptions.Item label="编译摘要">{scenario.compiled_sha256}</Descriptions.Item>
      </Descriptions>
      <PerformanceConfiguration definition={scenario.definition} title="此版本声明式配置" />
    </Card>
  )
}

function PerformanceRunWorkspace({ run }: { run: PerformanceRun }) {
  const [downloadError, setDownloadError] = useState<string | null>(null)
  const [downloading, setDownloading] = useState(false)
  async function download() {
    setDownloading(true)
    setDownloadError(null)
    try {
      await downloadPerformanceMetrics(run.project_id, run)
    } catch (error) {
      setDownloadError(apiErrorMessage(error))
    } finally {
      setDownloading(false)
    }
  }
  return (
    <Card className="lab-detail" title="性能运行 · 冻结证据">
      <Alert
        type={run.status === 'failed' ? 'error' : 'info'}
        showIcon
        title={
          <Space>
            <RunStatus status={run.status} />
            场景 v{run.scenario_version}
          </Space>
        }
        description={
          run.error_message ??
          '以下配置与指标来自此运行，不随场景新版本更新。尚未完成的运行不代表通过。'
        }
      />
      <PerformanceRunIdentity run={run} />
      <Tabs
        items={[
          {
            key: 'results',
            label: '指标与阈值',
            children: (
              <>
                <Descriptions column={2} size="small" bordered>
                  <Descriptions.Item label="请求样本">
                    {run.summary.http_reqs_count ?? '未提供'}
                  </Descriptions.Item>
                  <Descriptions.Item label="失败率">
                    {metric(run.summary.http_req_failed_rate, '')}
                  </Descriptions.Item>
                  <Descriptions.Item label="P95">
                    {metric(run.summary.http_req_duration_p95_ms, ' ms')}
                  </Descriptions.Item>
                  <Descriptions.Item label="请求速率">
                    {metric(run.summary.http_reqs_rate, ' req/s')}
                  </Descriptions.Item>
                  <Descriptions.Item label="基线运行">
                    {run.baseline_run_id ?? '无基线'}
                  </Descriptions.Item>
                  <Descriptions.Item label="基线 P95">
                    {metric(run.summary.baseline_p95_ms, ' ms')}
                  </Descriptions.Item>
                  <Descriptions.Item label="回归差值">
                    {regression(run.summary.p95_regression_percent)}
                  </Descriptions.Item>
                  <Descriptions.Item label="样本稳定性">未提供稳定性判定</Descriptions.Item>
                </Descriptions>
                <RunEvidence run={run} />
                {!run.threshold_results.length && (
                  <Typography.Text type="secondary">尚无阈值评估结果</Typography.Text>
                )}
                <Space wrap>
                  <Button
                    disabled={!run.raw_metrics_artifact_id}
                    loading={downloading}
                    onClick={() => void download()}
                  >
                    下载原始指标
                  </Button>
                  <Typography.Text type="secondary">
                    {run.raw_metrics_artifact_id ?? '未生成原始指标文件'}
                  </Typography.Text>
                </Space>
                {downloadError && <Alert type="error" title={downloadError} />}
              </>
            ),
          },
          {
            key: 'configuration',
            label: '冻结负载与请求',
            children: (
              <PerformanceConfiguration
                definition={run.definition_snapshot}
                title="运行时声明式配置"
              />
            ),
          },
          {
            key: 'gates',
            label: '门禁证据',
            children: run.gate_evaluations.length ? (
              run.gate_evaluations.map((evaluation) => (
                <Card
                  size="small"
                  key={evaluation.id}
                  title={`${evaluation.status === 'passed' ? '通过' : '阻断'} · ${evaluation.quality_gate_id}`}
                >
                  <Typography.Text>{evaluation.evaluated_at}</Typography.Text>
                  {evaluation.violations.map((reason, index) => (
                    <Alert type="error" key={index} title={reason} />
                  ))}
                  <ResponseCodeReader value={evaluation.metrics} title="门禁实际指标" />
                </Card>
              ))
            ) : (
              <Empty description="此运行没有门禁评估证据" />
            ),
          },
        ]}
      />
    </Card>
  )
}

function PerformanceConfiguration({
  definition,
  title,
}: {
  definition: PerformanceDefinition
  title: string
}) {
  return (
    <>
      <Typography.Paragraph>
        {loadDescription(definition)} · {definition.steps.length} 个 HTTP 步骤 ·{' '}
        {definition.thresholds.length} 项阈值 · 优雅停止 {definition.graceful_stop_seconds}s
      </Typography.Paragraph>
      <ResponseCodeReader value={definition} title={title} />
    </>
  )
}

function VersionScenarioDialog({
  base,
  submitting,
  onClose,
  onCreate,
}: {
  base: PerformanceScenario | null
  submitting: boolean
  onClose: () => void
  onCreate: (description: string, definition: PerformanceDefinition) => Promise<void>
}) {
  const [form] = Form.useForm<{ description: string; definition: string }>()
  return (
    <Modal
      title={base ? `${base.name} · 从 v${base.version} 创建新版本` : '创建新版本'}
      open={Boolean(base)}
      width={900}
      confirmLoading={submitting}
      onCancel={onClose}
      onOk={() => form.submit()}
      destroyOnHidden
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={{
          description: base?.description ?? '',
          definition: JSON.stringify(base?.definition ?? {}, null, 2),
        }}
        onFinish={(value) =>
          void onCreate(value.description, parsePerformanceDefinition(value.definition))
        }
      >
        <Alert type="info" title="创建独立草稿版本，原版本和历史运行不变；审阅发布后才能运行。" />
        <Form.Item label="版本说明" name="description">
          <Input />
        </Form.Item>
        <Form.Item
          label="完整声明式配置"
          name="definition"
          rules={[
            { required: true },
            {
              validator: async (_, value: string) => {
                parsePerformanceDefinition(value)
              },
            },
          ]}
          extra="支持完整 HTTP 步骤、阶梯负载、请求头与请求体和阈值；服务端验证全部配置。"
        >
          <Input.TextArea rows={18} className="code-input" />
        </Form.Item>
      </Form>
    </Modal>
  )
}

function parsePerformanceDefinition(text: string): PerformanceDefinition {
  let value: PerformanceDefinition
  try {
    value = JSON.parse(text) as PerformanceDefinition
  } catch {
    throw new Error('请输入有效的声明式 JSON 配置')
  }
  if (
    !value ||
    !['constant_vus', 'ramping_vus'].includes(value.executor) ||
    !Array.isArray(value.steps) ||
    !value.steps.length ||
    !Array.isArray(value.thresholds) ||
    !Array.isArray(value.stages)
  )
    throw new Error('配置需包含负载模型、HTTP 步骤、阈值和阶段')
  return value
}

function PerformanceRunIdentity({ run }: { run: PerformanceRun }) {
  return (
    <Descriptions column={1} size="small" className="lab-identity">
      <Descriptions.Item label="运行 ID">{run.id}</Descriptions.Item>
      <Descriptions.Item label="场景 ID">{run.scenario_id}</Descriptions.Item>
      <Descriptions.Item label="排队 / 开始 / 完成">
        {run.created_at} / {run.started_at ?? '未开始'} / {run.completed_at ?? '未完成'}
      </Descriptions.Item>
      <Descriptions.Item label="冻结摘要">{run.compiled_sha256}</Descriptions.Item>
      <Descriptions.Item label="失败代码">{run.error_code ?? '未提供'}</Descriptions.Item>
    </Descriptions>
  )
}
