import QueryFailureNotice from '../components/QueryFailureNotice'
import CatalogPagination from '../components/CatalogPagination'
import { DownloadOutlined, PlusOutlined, SafetyCertificateOutlined } from '@ant-design/icons'
import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Form,
  Input,
  InputNumber,
  Modal,
  Progress,
  Row,
  Select,
  Space,
  Statistic,
  Switch,
  Table,
  Tag,
  Typography,
} from 'antd'
import { useRouteScopedState } from '../lib/use-route-scoped-state'
import { Link } from 'react-router-dom'

import type {
  QualityGateInput,
  ReleaseRiskDetail,
  ReleaseRiskInput,
} from '../features/quality/quality-service'
import type { ImpactRunSummary } from '../features/impact/impact-service'
import { useQualityCenter } from '../features/quality/use-quality-center'
import { qualityRunPath } from '../features/quality/quality-navigation'
import { qualityGateCounts } from '../features/quality/quality-metrics'
import {
  QualityAssetEvidence,
  QualityFlakyEvidence,
  QualityRiskHistory,
} from '../features/quality/QualityEvidence'
import { reportExecutionPath } from '../features/workflows/execution-navigation'
import { apiErrorMessage } from '../lib/api'
import type { TestPlanRun } from '../lib/api'
import '../features/quality/quality-center.css'

export default function QualityCenterPage() {
  const state = useQualityCenter()
  const [createOpen, setCreateOpen] = useRouteScopedState(state.projectId, null, false)
  const [riskOpen, setRiskOpen] = useRouteScopedState(state.projectId, null, false)
  const records = pageItems(state.flaky.data)
  const latest = firstPageItem(state.latestRun.data)
  return (
    <div className="quality-center-page">
      <div className="page-heading">
        <div>
          <Typography.Title level={2}>质量中心</Typography.Title>
          <Typography.Text type="secondary">
            统一管理 CI 质量门禁、Flaky 隔离、基线对比与 JUnit 产物。
          </Typography.Text>
        </div>
        <Space>
          <Button disabled={!state.canEdit || !state.riskEnabled} onClick={() => setRiskOpen(true)}>
            分析发布风险
          </Button>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            disabled={!state.canEdit}
            onClick={() => setCreateOpen(true)}
          >
            新建门禁
          </Button>
        </Space>
      </div>
      <QueryFailureNotice
        queries={[state.gates, state.latestRun, state.permissions, state.featureFlags]}
      />
      <QualityOverview
        gateCounts={qualityGateCounts(state.gates.isSuccess ? state.gates.data : undefined)}
        flakyCount={
          state.flaky.isSuccess ? records.filter((item) => item.flaky_score > 0).length : undefined
        }
        quarantinedCount={
          state.flaky.isSuccess ? records.filter((item) => item.quarantined).length : undefined
        }
        latest={latest}
      />
      <div className="catalog-controls">
        <CatalogPagination query={state.impactRuns} label="影响证据" />
      </div>
      <QualityRiskHistory state={state} />
      <QualityRiskReadState state={state} />
      <QualityFlakyEvidence state={state} />
      <div className="quality-grid">
        <Card title="质量门禁" loading={state.gates.isLoading}>
          <Table
            rowKey="id"
            size="small"
            pagination={false}
            dataSource={listItems(state.gates.data)}
            locale={{ emptyText: '暂无质量门禁' }}
            columns={[
              { title: '名称', dataIndex: 'name' },
              {
                title: '通过率',
                dataIndex: 'min_pass_rate',
                render: (value: number) => `${value}%`,
              },
              { title: '失败上限', dataIndex: 'max_failed', width: 100 },
              { title: 'Flaky 上限', dataIndex: 'max_flaky', width: 110 },
              {
                title: '状态',
                dataIndex: 'enabled',
                render: (value: boolean) => (
                  <Tag color={value ? 'success' : 'default'}>{value ? '启用' : '停用'}</Tag>
                ),
              },
            ]}
          />
        </Card>
        <Card title="Flaky 检测与隔离" loading={state.flaky.isLoading}>
          <CatalogPagination query={state.flaky} label="Flaky 目录" />
          <Table
            rowKey="id"
            size="small"
            pagination={false}
            scroll={{ x: 720, y: 360 }}
            rowClassName={(row) =>
              row.id === state.linkedRecordId ? 'quality-selected-evidence' : ''
            }
            dataSource={records}
            locale={{ emptyText: '暂无 Flaky 记录' }}
            columns={[
              {
                title: '资产',
                render: (_, row) => (
                  <Button
                    type="link"
                    className="quality-asset-name"
                    onClick={() => state.selectEvidence('record', row.id)}
                  >{`${row.target_type}:${row.target_id}@${row.target_version}`}</Button>
                ),
              },
              {
                title: '得分',
                dataIndex: 'flaky_score',
                render: (value: number) => (
                  <Tag color={value > 0 ? 'warning' : 'success'}>{value}</Tag>
                ),
              },
              {
                title: '通过/失败',
                render: (_, row) => `${row.passed_runs}/${row.failed_runs}`,
              },
              {
                title: '隔离',
                dataIndex: 'quarantined',
                render: (value: boolean, row) => (
                  <Switch
                    aria-label={`隔离 ${row.target_id}@${row.target_version}`}
                    checked={value}
                    loading={state.toggling}
                    disabled={!state.canEdit}
                    onChange={(checked) => void state.toggleQuarantine(row.id, checked)}
                  />
                ),
              },
            ]}
          />
        </Card>
      </div>
      <Card title="最近运行与基线" className="quality-runs-card" loading={state.runs.isLoading}>
        <CatalogPagination query={state.runs} label="计划运行／基线" />
        <Table
          rowKey="id"
          size="small"
          pagination={false}
          scroll={{ x: 760 }}
          dataSource={pageItems(state.runs.data)}
          locale={{ emptyText: '暂无运行数据' }}
          columns={[
            {
              title: '运行 ID',
              render: (_, run) =>
                state.projectId && (
                  <Link to={qualityRunPath(state.projectId, run.id, run.test_plan_id)}>
                    {run.id}
                  </Link>
                ),
            },
            { title: '队列', dataIndex: 'queue_name' },
            { title: '优先级', dataIndex: 'queue_priority' },
            {
              title: '门禁摘要',
              dataIndex: 'quality_summary',
              render: (value: Record<string, unknown>) => qualitySummary(value),
            },
            {
              title: '操作',
              render: (_, run) => (
                <Space wrap>
                  {state.projectId && run.baseline_run_id && (
                    <Link to={qualityRunPath(state.projectId, run.baseline_run_id)}>
                      查看基线运行
                    </Link>
                  )}
                  <Button
                    type="link"
                    icon={<DownloadOutlined />}
                    disabled={!['passed', 'failed', 'cancelled'].includes(run.status)}
                    onClick={() => void state.exportJunit(run.id)}
                  >
                    JUnit
                  </Button>
                </Space>
              ),
            },
          ]}
        />
      </Card>
      <CreateGateDialog
        key={`${state.projectId}:gate`}
        open={createOpen}
        submitting={state.creating}
        onClose={() => setCreateOpen(false)}
        onCreate={async (input) => {
          if (await state.addGate(input)) setCreateOpen(false)
        }}
      />
      <CreateRiskDialog
        key={`${state.projectId}:risk`}
        open={riskOpen}
        submitting={state.analyzingRisk}
        impactRuns={pageItems(state.impactRuns.data)}
        onClose={() => setRiskOpen(false)}
        onCreate={async (input) => {
          if (await state.addRisk(input)) setRiskOpen(false)
        }}
      />
    </div>
  )
}

function QualityInsights({
  risk,
  loading,
  projectId,
}: {
  risk: ReleaseRiskDetail | undefined
  loading: boolean
  projectId: string
}) {
  return (
    <Card title="质量洞察与可解释发布风险" loading={loading} className="quality-runs-card">
      {!risk ? (
        <Typography.Text type="secondary">
          选择一条影响分析生成发布风险快照，失败聚类与风险因子将固定保存。
        </Typography.Text>
      ) : (
        <Space orientation="vertical" size="large" style={{ width: '100%' }}>
          <Descriptions column={{ xs: 1, sm: 2 }} size="small" bordered>
            <Descriptions.Item label="风险快照">{risk.id}</Descriptions.Item>
            <Descriptions.Item label="冻结于">{risk.created_at}</Descriptions.Item>
            <Descriptions.Item label="证据窗口">
              {risk.window_started_at} 至 {risk.window_ended_at}
            </Descriptions.Item>
            <Descriptions.Item label="算法版本">{risk.algorithm_version}</Descriptions.Item>
            <Descriptions.Item label="来源影响分析">{risk.impact_run_id}</Descriptions.Item>
          </Descriptions>
          <Row gutter={[16, 16]}>
            <Col xs={12} lg={6}>
              <Statistic title="质量评分" value={risk.quality_score} suffix="/ 100" />
            </Col>
            <Col xs={12} lg={6}>
              <Statistic
                title="发布风险"
                value={risk.score}
                suffix={<Tag color={riskColor(risk.risk_level)}>{riskLabel(risk.risk_level)}</Tag>}
              />
            </Col>
            <Col xs={12} lg={6}>
              <Statistic
                title="覆盖缺口"
                value={nestedNumber(risk.evidence_snapshot, 'impact', 'coverage_gap_count')}
              />
            </Col>
            <Col xs={12} lg={6}>
              <Statistic title="失败根因" value={risk.failure_clusters.length} />
            </Col>
          </Row>
          <div className="quality-grid">
            <Card size="small" title="风险因子（总分等于发布风险）">
              {risk.factors.map((factor) => (
                <div key={factor.code} style={{ marginBottom: 12 }}>
                  <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                    <Typography.Text>{factor.label}</Typography.Text>
                    <Typography.Text code>
                      {factor.score} / {factor.max_score}
                    </Typography.Text>
                  </Space>
                  <Progress
                    percent={Math.round((factor.score / factor.max_score) * 100)}
                    showInfo={false}
                    size="small"
                  />
                </div>
              ))}
            </Card>
            <Card size="small" title="智能测试选择建议">
              <Table
                rowKey={(row) => `${row.target_type}:${row.target_id}`}
                size="small"
                pagination={false}
                scroll={{ x: 650 }}
                dataSource={risk.recommended_tests}
                locale={{ emptyText: '暂无有证据的测试建议' }}
                columns={[
                  { title: '资产', dataIndex: 'name' },
                  {
                    title: '版本',
                    dataIndex: 'version',
                    render: (value) => (value == null ? '未提供' : `v${value}`),
                  },
                  {
                    title: '优先级',
                    dataIndex: 'priority',
                    render: (value: string) => (
                      <Tag color={value === 'high' ? 'error' : 'warning'}>
                        {value === 'high' ? '高' : '中'}
                      </Tag>
                    ),
                  },
                  {
                    title: '证据',
                    dataIndex: 'reasons',
                    render: (value: string[]) => value.join('；'),
                  },
                  {
                    title: '固定资产',
                    render: (_, row) => (
                      <QualityAssetEvidence
                        projectId={projectId}
                        type={row.target_type}
                        id={row.target_id}
                        version={row.version}
                      />
                    ),
                  },
                ]}
              />
            </Card>
          </div>
          <Table
            rowKey="id"
            size="small"
            pagination={false}
            scroll={{ x: 900 }}
            dataSource={risk.failure_clusters}
            locale={{ emptyText: '当前窗口没有失败聚类' }}
            columns={[
              { title: '失败聚类', dataIndex: 'title' },
              {
                title: '当前/基线',
                render: (_, row) => `${row.occurrence_count}/${row.baseline_count}`,
              },
              {
                title: '影响流程',
                dataIndex: 'affected_workflow_names',
                render: (value: string[]) => value.join('、') || '—',
              },
              {
                title: '置信度',
                dataIndex: 'confidence',
                render: (value: number) => `${Math.round(value * 100)}%`,
              },
              { title: '建议', dataIndex: 'recommendation' },
              {
                title: '样本报告',
                render: (_, row) => (
                  <Space orientation="vertical">
                    {row.sample_execution_ids.map((id, index) => (
                      <Link key={id} to={reportExecutionPath(projectId, { executionId: id })}>
                        查看样本 {index + 1}
                      </Link>
                    ))}
                  </Space>
                ),
              },
            ]}
          />
          <Typography.Text type="secondary">
            算法 {risk.algorithm_version} · 证据指纹 {risk.fingerprint.slice(0, 12)} ·
            当前窗口与等长基线均为 {risk.window_days} 天
          </Typography.Text>
        </Space>
      )}
    </Card>
  )
}

function QualityOverview({
  gateCounts,
  flakyCount,
  quarantinedCount,
  latest,
}: {
  gateCounts: { enabled: number; total: number } | undefined
  flakyCount: number | undefined
  quarantinedCount: number | undefined
  latest: TestPlanRun | undefined
}) {
  const passRate = latest?.quality_summary.pass_rate
  return (
    <Row gutter={[16, 16]} className="quality-overview">
      <Col xs={12} lg={6}>
        <Card>
          <Statistic
            title="启用门禁"
            value={gateCounts?.enabled ?? '未提供'}
            prefix={<SafetyCertificateOutlined />}
          />
          {gateCounts && (
            <Typography.Text type="secondary">共 {gateCounts.total} 项门禁</Typography.Text>
          )}
        </Card>
      </Col>
      <Col xs={12} lg={6}>
        <Card>
          <Statistic title="已载入 Flaky 资产" value={flakyCount ?? '未提供'} />
        </Card>
      </Col>
      <Col xs={12} lg={6}>
        <Card>
          <Statistic title="已载入隔离资产" value={quarantinedCount ?? '未提供'} />
        </Card>
      </Col>
      <Col xs={12} lg={6}>
        <Card>
          <Statistic
            title="最近通过率"
            value={typeof passRate === 'number' ? passRate : '未提供'}
            suffix={typeof passRate === 'number' ? '%' : undefined}
          />
        </Card>
      </Col>
    </Row>
  )
}

function CreateGateDialog({
  open,
  submitting,
  onClose,
  onCreate,
}: {
  open: boolean
  submitting: boolean
  onClose: () => void
  onCreate: (input: QualityGateInput) => Promise<void>
}) {
  const [form] = Form.useForm<QualityGateInput>()
  return (
    <Modal
      title="新建质量门禁"
      open={open}
      confirmLoading={submitting}
      onCancel={onClose}
      onOk={() => form.submit()}
      destroyOnHidden
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={{
          enabled: true,
          min_pass_rate: 100,
          max_failed: 0,
          max_flaky: 0,
          max_duration_regression_percent: 20,
          require_no_breaking_changes: true,
        }}
        onFinish={(value) => void onCreate(value)}
      >
        <Form.Item name="name" label="门禁名称" rules={[{ required: true }]}>
          <Input maxLength={160} />
        </Form.Item>
        <Space size="large" wrap>
          <Form.Item name="min_pass_rate" label="最低通过率">
            <InputNumber min={0} max={100} suffix="%" />
          </Form.Item>
          <Form.Item name="max_failed" label="失败上限">
            <InputNumber min={0} />
          </Form.Item>
          <Form.Item name="max_flaky" label="Flaky 上限">
            <InputNumber min={0} />
          </Form.Item>
          <Form.Item name="max_duration_regression_percent" label="耗时回归上限">
            <InputNumber min={0} suffix="%" />
          </Form.Item>
        </Space>
        <Form.Item
          name="require_no_breaking_changes"
          label="阻断破坏性契约变更"
          valuePropName="checked"
        >
          <Switch />
        </Form.Item>
      </Form>
    </Modal>
  )
}

function CreateRiskDialog({
  open,
  submitting,
  impactRuns,
  onClose,
  onCreate,
}: {
  open: boolean
  submitting: boolean
  impactRuns: ImpactRunSummary[]
  onClose: () => void
  onCreate: (input: ReleaseRiskInput) => Promise<void>
}) {
  const [form] = Form.useForm<ReleaseRiskInput>()
  return (
    <Modal
      title="分析发布风险"
      open={open}
      confirmLoading={submitting}
      onCancel={onClose}
      onOk={() => form.submit()}
      destroyOnHidden
    >
      <Typography.Paragraph type="secondary">
        风险结果会固定影响覆盖、等长回归基线、失败聚类、契约、性能和 Flaky 证据。
      </Typography.Paragraph>
      <Form
        form={form}
        layout="vertical"
        initialValues={{ window_days: 30 }}
        onFinish={(value) => void onCreate(value)}
      >
        <Form.Item name="title" label="候选版本" rules={[{ required: true }]}>
          <Input maxLength={200} placeholder="例如 v3.0.0-rc.1 候选" />
        </Form.Item>
        <Form.Item name="impact_run_id" label="影响分析" rules={[{ required: true }]}>
          <Select
            placeholder="选择已持久化的影响分析"
            options={impactRuns.map((run) => ({
              value: run.id,
              label: `${run.title} · ${run.change_count} 项变更`,
            }))}
          />
        </Form.Item>
        <Form.Item name="window_days" label="分析窗口" rules={[{ required: true }]}>
          <Select
            options={[
              { value: 7, label: '7 天' },
              { value: 14, label: '14 天' },
              { value: 30, label: '30 天' },
              { value: 90, label: '90 天' },
            ]}
          />
        </Form.Item>
      </Form>
    </Modal>
  )
}

function nestedNumber(
  value: Record<string, unknown>,
  parent: string,
  child: string,
): number | '未提供' {
  const nested = value[parent]
  if (!nested || typeof nested !== 'object') return '未提供'
  const result = (nested as Record<string, unknown>)[child]
  return typeof result === 'number' ? result : '未提供'
}

function riskLabel(value: ReleaseRiskDetail['risk_level']): string {
  return { low: '低风险', medium: '中风险', high: '高风险', critical: '严重风险' }[value]
}

function riskColor(value: ReleaseRiskDetail['risk_level']): string {
  return { low: 'success', medium: 'warning', high: 'error', critical: 'error' }[value]
}

function listItems<T>(value: T[] | undefined): T[] {
  return value ?? []
}

function pageItems<T>(value: { items: T[] } | undefined): T[] {
  return value?.items ?? []
}

function firstPageItem<T>(value: { items: T[] } | undefined): T | undefined {
  return value?.items.at(0)
}

function qualitySummary(value: Record<string, unknown>): string {
  if (typeof value.pass_rate !== 'number') return '待生成'
  return `通过率 ${value.pass_rate}% · 失败 ${String(value.failed ?? '未提供')} · Flaky ${String(value.flaky ?? '未提供')}`
}

function QualityRiskReadState({ state }: { state: ReturnType<typeof useQualityCenter> }) {
  if (state.featureFlags.isError)
    return (
      <Alert
        type="error"
        title="功能状态读取失败"
        description={apiErrorMessage(state.featureFlags.error)}
        action={<Button onClick={() => void state.featureFlags.refetch()}>重试</Button>}
      />
    )
  if (!state.riskEnabled)
    return (
      <Alert
        type="info"
        title={state.featureFlags.isPending ? '正在读取风险分析功能状态' : '发布风险分析尚未开放'}
      />
    )
  return (
    <>
      {state.linkedRiskId && <Alert type="info" title={`冻结风险快照 ${state.linkedRiskId}`} />}
      {state.risk.isError ? (
        <Alert
          showIcon
          type="error"
          title="风险快照读取失败"
          description={apiErrorMessage(state.risk.error)}
          action={<Button onClick={() => void state.risk.refetch()}>重试</Button>}
        />
      ) : (
        <QualityInsights
          key={`${state.projectId}:${state.activeRiskId}`}
          projectId={state.projectId ?? ''}
          risk={state.risk.data}
          loading={state.risk.isLoading}
        />
      )}
    </>
  )
}
