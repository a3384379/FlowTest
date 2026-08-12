import {
  CheckCircleOutlined,
  ExperimentOutlined,
  PlusOutlined,
  RocketOutlined,
} from '@ant-design/icons'
import {
  Button,
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
} from '../features/performance/performance-service'
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
          disabled={!state.projectId}
          onClick={() => setCreateOpen(true)}
        >
          新建性能场景
        </Button>
      </div>
      <PerformanceOverview scenarios={scenarios.length} runs={runs.length} latest={latest} />
      <Card title="性能场景" className="performance-card" loading={state.scenarios.isLoading}>
        <Table
          rowKey="id"
          size="small"
          pagination={{ pageSize: 8 }}
          dataSource={scenarios}
          locale={{ emptyText: '暂无性能场景' }}
          columns={[
            { title: '名称', dataIndex: 'name' },
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
                  {row.status === 'draft' ? (
                    <Button
                      type="link"
                      loading={state.publishing}
                      onClick={() => void state.publishScenario(row.id)}
                    >
                      发布
                    </Button>
                  ) : (
                    <Button
                      type="link"
                      icon={<RocketOutlined />}
                      loading={state.starting}
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
          pagination={{ pageSize: 8 }}
          dataSource={runs}
          locale={{ emptyText: '暂无性能运行' }}
          expandable={{ expandedRowRender: (run) => <RunEvidence run={run} /> }}
          columns={[
            { title: '运行 ID', dataIndex: 'id', render: (value) => value.slice(0, 8) },
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
  scenarios: number
  runs: number
  latest: PerformanceRun | undefined
}) {
  return (
    <Row gutter={16} className="performance-overview">
      <Col span={6}>
        <Card>
          <Statistic title="场景版本" value={scenarios} prefix={<ExperimentOutlined />} />
        </Card>
      </Col>
      <Col span={6}>
        <Card>
          <Statistic title="运行总数" value={runs} />
        </Card>
      </Col>
      <Col span={6}>
        <Card>
          <Statistic
            title="最近 P95"
            value={latest?.summary.http_req_duration_p95_ms ?? 0}
            suffix="ms"
          />
        </Card>
      </Col>
      <Col span={6}>
        <Card>
          <Statistic
            title="基线回归"
            value={latest?.summary.p95_regression_percent ?? 0}
            suffix="%"
            styles={{
              content: {
                color: (latest?.summary.p95_regression_percent ?? 0) > 20 ? '#cf1322' : '#3f8600',
              },
            }}
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
    <Tag color={value > 20 ? 'error' : 'success'}>
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
