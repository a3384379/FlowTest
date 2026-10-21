import FeatureDisabledNotice from '../components/FeatureDisabledNotice'
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
  Grid,
  Spin,
  Tabs,
  Card,
  Col,
  Row,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
} from 'antd'
import { useState } from 'react'
import { useRouteScopedState } from '../lib/use-route-scoped-state'
import PerformanceScenarioDialog from '../features/performance/PerformanceScenarioDialog'

import type {
  PerformanceRun,
  PerformanceDefinition,
  PerformanceScenario,
} from '../features/performance/performance-service'
import { apiErrorWithTrace } from '../lib/api'
import { downloadPerformanceMetrics } from '../features/performance/performance-service'
import ResponseCodeReader from '../features/api-console/ResponseCodeReader'
import { usePerformanceLab } from '../features/performance/use-performance-lab'

export default function PerformanceLabPage() {
  const state = usePerformanceLab()
  const screens = Grid.useBreakpoint()
  const fixed: { name: 'left' | undefined; actions: 'right' | undefined } = screens.lg
    ? { name: 'left', actions: 'right' }
    : { name: undefined, actions: undefined }
  const [createOpen, setCreateOpen] = useRouteScopedState(state.projectId, null, false)
  const [versionBase, setVersionBase] = useRouteScopedState<PerformanceScenario | null>(
    state.projectId,
    null,
    null,
  )
  const scenarios = state.scenarios.data?.items ?? []
  const runs = state.runs.data?.items ?? []
  const latest = latestPerformanceRun(state.latestRun.data)
  return (
    <>
      <FeatureDisabledNotice
        flags={state.featureFlags.data}
        feature="performance_lab"
        label="性能实验室"
      />
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
              scroll={{ x: 810 }}
              dataSource={scenarios}
              locale={{ emptyText: '暂无性能场景' }}
              columns={[
                {
                  title: '名称',
                  width: 200,
                  fixed: fixed.name,
                  render: (_, row) => (
                    <Button
                      className="performance-scenario-name"
                      type="link"
                      onClick={() => state.selectObject('scenario', row.id)}
                    >
                      {row.name}
                    </Button>
                  ),
                },
                { title: '版本', dataIndex: 'version', width: 70, render: (value) => `v${value}` },
                {
                  title: '目标',
                  width: 140,
                  dataIndex: 'target_type',
                  render: (value) => (value === 'rest' ? 'REST' : '纯 HTTP Workflow'),
                },
                {
                  title: '负载',
                  width: 140,
                  render: (_, row) => loadDescription(row.definition),
                },
                {
                  title: '状态',
                  width: 80,
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
                  fixed: fixed.actions,
                  render: (_, row) => (
                    <Space>
                      <Button
                        type="link"
                        disabled={!state.canEdit || row.status !== 'published'}
                        title="仅已发布场景可创建新版本"
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
              scroll={{ x: 650 }}
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
      <ScenarioEditor
        state={state}
        open={createOpen}
        base={versionBase}
        onClose={() => {
          setCreateOpen(false)
          setVersionBase(null)
        }}
      />
    </>
  )
}

function ScenarioEditor({
  state,
  open,
  base,
  onClose,
}: {
  state: ReturnType<typeof usePerformanceLab>
  open: boolean
  base: PerformanceScenario | null
  onClose: () => void
}) {
  if (!open && !base) return null
  return (
    <PerformanceScenarioDialog
      key={`${state.projectId}:${base?.id ?? 'new'}`}
      base={base ?? undefined}
      submitting={state.creating || state.versioning}
      onClose={onClose}
      onSubmit={(input) =>
        base
          ? state.addVersion(base.id, input.description, input.definition)
          : state.addScenario(input)
      }
    />
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
  const p95 = latest?.summary.http_req_duration_p95_ms
  const change = latest?.summary.p95_regression_percent
  return (
    <Row gutter={[16, 16]} className="performance-overview">
      <Col xs={12} lg={6}>
        <Card>
          <Statistic
            title="场景版本"
            value={scenarios ?? '未提供'}
            prefix={<ExperimentOutlined />}
          />
        </Card>
      </Col>
      <Col xs={12} lg={6}>
        <Card>
          <Statistic title="运行总数" value={runs ?? '未提供'} />
        </Card>
      </Col>
      <Col xs={12} lg={6}>
        <Card>
          <Statistic
            title="最近一次运行 P95"
            value={p95 ?? '未提供'}
            precision={2}
            suffix={p95 == null ? undefined : 'ms'}
          />
        </Card>
      </Col>
      <Col xs={12} lg={6}>
        <Card>
          <Statistic
            title="基线回归"
            value={change ?? '未提供'}
            precision={2}
            suffix={change == null ? undefined : '%'}
          />
        </Card>
      </Col>
    </Row>
  )
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
    { query: state.latestRun, name: '最新运行' },
    { query: state.permissions, name: '项目权限' },
    { query: state.featureFlags, name: '模块能力' },
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
            description={apiErrorWithTrace(read.query.error)}
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
          description={apiErrorWithTrace(query.error)}
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
      setDownloadError(apiErrorWithTrace(error))
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

function latestPerformanceRun(
  data: { items: PerformanceRun[] } | undefined,
): PerformanceRun | undefined {
  return data?.items.at(0)
}
