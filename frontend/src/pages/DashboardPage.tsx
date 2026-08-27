import {
  ApiOutlined,
  ApartmentOutlined,
  CheckCircleOutlined,
  ExclamationCircleOutlined,
  FolderOpenOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons'
import { Alert, Button, Card, Empty, Progress, Space, Table, Tag, Typography } from 'antd'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'

import { DashboardTrendChart } from '../features/dashboard/DashboardTrendChart'
import { useDashboard } from '../features/dashboard/use-dashboard'
import type { ImpactRunSummary } from '../features/impact/impact-service'
import { projectPath } from '../features/projects/project-routing'
import ProjectEmptyState from '../features/projects/ProjectEmptyState'
import type { ReleaseDecision } from '../features/release-gate/release-gate-service'
import type {
  FlakyRecord,
  ReleaseRiskDetail,
  ReleaseRiskSummary,
} from '../features/quality/quality-service'
import { apiErrorMessage, type DashboardSummary, type Page, type RecentExecution } from '../lib/api'

const statusLabels: Record<string, string> = {
  queued: '排队中',
  running: '运行中',
  passed: '通过',
  failed: '失败',
  error: '异常',
  cancelled: '已取消',
}

const statusColors: Record<string, string> = {
  queued: 'default',
  running: 'processing',
  passed: 'success',
  failed: 'error',
  error: 'error',
  cancelled: 'default',
}

const riskLabels: Record<ReleaseRiskSummary['risk_level'], string> = {
  low: '低风险',
  medium: '中风险',
  high: '高风险',
  critical: '严重风险',
}

const riskColors: Record<ReleaseRiskSummary['risk_level'], string> = {
  low: 'success',
  medium: 'warning',
  high: 'error',
  critical: 'error',
}

const emptySummary: DashboardSummary = {
  project_count: 0,
  api_count: 0,
  workflow_count: 0,
  today_total: 0,
  today_passed: 0,
  today_failed: 0,
  pass_rate: 0,
  trend: [],
}

type DashboardState = ReturnType<typeof useDashboard>

export default function DashboardPage() {
  const dashboard = useDashboard()
  const baseError = dashboard.summary.error ?? dashboard.recent.error
  const description = dashboard.currentProject
    ? `当前查看：${dashboard.currentProject.name}`
    : '汇总所有可访问项目的接口资产与执行质量。'
  return (
    <>
      <DashboardHeading projectId={dashboard.projectId} description={description} />
      {baseError && (
        <Alert
          type="error"
          showIcon
          title="质量总览加载失败"
          description={apiErrorMessage(baseError)}
        />
      )}
      {dashboard.projectId && dashboard.insightError && (
        <Alert
          type="error"
          showIcon
          title="质量证据加载失败"
          description={apiErrorMessage(dashboard.insightError)}
        />
      )}
      {dashboard.projectId ? (
        <ProjectQualityCommandCenter dashboard={dashboard} />
      ) : (
        <GlobalQualityOverview dashboard={dashboard} />
      )}
    </>
  )
}

function DashboardHeading({
  projectId,
  description,
}: {
  projectId: string | null
  description: string
}) {
  return (
    <div className="page-heading">
      <div>
        <Typography.Title level={2}>质量指挥中心</Typography.Title>
        <Typography.Text type="secondary">{description}</Typography.Text>
      </div>
      {projectId && (
        <Space>
          <Button href={projectPath(projectId, 'impact')}>查看影响分析</Button>
          <Button type="primary" href={projectPath(projectId, 'release')}>
            发布门禁
          </Button>
        </Space>
      )}
    </div>
  )
}

function ProjectQualityCommandCenter({ dashboard }: { dashboard: DashboardState }) {
  const summary = valueOr(dashboard.summary.data, emptySummary)
  const risk = firstItem(dashboard.risks.data)
  const impact = firstItem(dashboard.impactRuns.data)
  const flaky = pageItems(dashboard.flaky.data)
  const decision = firstItem(dashboard.decisions.data)
  const projectId = required(dashboard.projectId)
  return (
    <>
      <ProjectQualityStats
        summary={summary}
        risk={risk}
        impact={impact}
        flaky={flaky}
        decision={decision}
        qualityEnabled={dashboard.qualityEnabled}
        impactEnabled={dashboard.impactEnabled}
        loading={anyLoading(dashboard.flags.isLoading, dashboard.summary.isLoading)}
      />
      <div className="quality-command-primary-grid">
        <TrendCard summary={dashboard.summary.data} loading={dashboard.summary.isLoading} />
        <div className="quality-command-evidence-stack">
          <RiskEvidenceCard
            projectId={projectId}
            enabled={dashboard.qualityEnabled}
            risk={dashboard.risk.data}
            loading={anyLoading(dashboard.risks.isLoading, dashboard.risk.isLoading)}
          />
          <ImpactEvidenceCard
            projectId={projectId}
            enabled={dashboard.impactEnabled}
            impact={impact}
            loading={dashboard.impactRuns.isLoading}
          />
        </div>
      </div>
      <div className="quality-command-secondary-grid">
        <Card title="最近运行" loading={dashboard.recent.isLoading}>
          <RecentExecutionTable items={dashboard.recent.data?.items ?? []} />
        </Card>
        <ReleaseDecisionCard
          projectId={projectId}
          decision={decision}
          loading={dashboard.decisions.isLoading}
        />
      </div>
    </>
  )
}

function GlobalQualityOverview({ dashboard }: { dashboard: DashboardState }) {
  if (dashboard.projects.data?.items.length === 0) return <ProjectEmptyState />
  const summary = dashboard.summary.data ?? emptySummary
  return (
    <>
      <div className="quality-command-stats">
        <QualityMetric
          title="可访问项目"
          value={`${summary.project_count} 个`}
          detail="当前账号授权范围"
          icon={<FolderOpenOutlined />}
          loading={dashboard.summary.isLoading}
        />
        <QualityMetric
          title="接口资产"
          value={`${summary.api_count} 个`}
          detail="已启用接口定义"
          icon={<ApiOutlined />}
          loading={dashboard.summary.isLoading}
        />
        <QualityMetric
          title="流程资产"
          value={`${summary.workflow_count} 个`}
          detail="可访问工作流"
          icon={<ApartmentOutlined />}
          loading={dashboard.summary.isLoading}
        />
        <QualityMetric
          title="今日执行"
          value={`${summary.today_total} 次`}
          detail={`失败或异常 ${summary.today_failed} 次`}
          icon={<ExclamationCircleOutlined />}
          loading={dashboard.summary.isLoading}
        />
        <QualityMetric
          title="今日终态通过率"
          value={`${summary.pass_rate}%`}
          detail={`${summary.today_passed} 个终态通过`}
          icon={<CheckCircleOutlined />}
          loading={dashboard.summary.isLoading}
        />
      </div>
      <div className="dashboard-grid">
        <TrendCard summary={dashboard.summary.data} loading={dashboard.summary.isLoading} />
        <Card title="最近运行" loading={dashboard.recent.isLoading}>
          <RecentExecutionTable items={dashboard.recent.data?.items ?? []} />
        </Card>
      </div>
    </>
  )
}

function ProjectQualityStats({
  summary,
  risk,
  impact,
  flaky,
  decision,
  qualityEnabled,
  impactEnabled,
  loading,
}: {
  summary: DashboardSummary
  risk?: ReleaseRiskSummary
  impact?: ImpactRunSummary
  flaky: FlakyRecord[]
  decision?: ReleaseDecision
  qualityEnabled: boolean
  impactEnabled: boolean
  loading: boolean
}) {
  const quarantined = flaky.filter((item) => item.quarantined).length
  const riskState = riskMetric(risk, qualityEnabled)
  const impactState = impactMetric(impact, impactEnabled)
  const decisionState = decisionMetric(decision)
  return (
    <div className="quality-command-stats">
      <QualityMetric
        title="发布风险"
        value={riskState.value}
        detail={riskState.detail}
        tone={riskState.tone}
        icon={<SafetyCertificateOutlined />}
        loading={loading}
      />
      <QualityMetric
        title="受影响变更"
        value={impactState.value}
        detail={impactState.detail}
        tone={impactState.tone}
        icon={<ExclamationCircleOutlined />}
        loading={loading}
      />
      <QualityMetric
        title="今日终态通过率"
        value={`${summary.pass_rate}%`}
        detail={`今日 ${summary.today_passed} / ${summary.today_passed + summary.today_failed} 通过`}
        tone={executionTone(summary.today_failed)}
        icon={<CheckCircleOutlined />}
        loading={loading}
      />
      <QualityMetric
        title="Flaky 资产"
        value={`${flaky.length} 项`}
        detail={`其中隔离 ${quarantined} 项`}
        tone={countTone(flaky.length)}
        icon={<ApartmentOutlined />}
        loading={loading}
      />
      <QualityMetric
        title="最新门禁"
        value={decisionState.value}
        detail={decisionState.detail}
        tone={decisionState.tone}
        icon={<SafetyCertificateOutlined />}
        loading={loading}
      />
    </div>
  )
}

function QualityMetric({
  title,
  value,
  detail,
  tone = 'default',
  icon,
  loading,
}: {
  title: string
  value: string
  detail: string
  tone?: string
  icon: ReactNode
  loading: boolean
}) {
  return (
    <Card loading={loading} className={`quality-command-metric quality-command-metric-${tone}`}>
      <Typography.Text type="secondary">{title}</Typography.Text>
      <div className="quality-command-metric-value">
        {icon}
        <span>{value}</span>
      </div>
      <Typography.Text type={tone === 'error' ? 'danger' : 'secondary'}>{detail}</Typography.Text>
    </Card>
  )
}

function TrendCard({ summary, loading }: { summary?: DashboardSummary; loading: boolean }) {
  return (
    <Card title="最近 7 日执行趋势" className="trend-card" loading={loading}>
      <DashboardTrendChart points={summary?.trend ?? []} />
      <div className="dashboard-pass-rate">
        <Typography.Text type="secondary">今日终态通过率</Typography.Text>
        <Progress percent={summary?.pass_rate ?? 0} status="active" />
      </div>
    </Card>
  )
}

function RiskEvidenceCard({
  projectId,
  enabled,
  risk,
  loading,
}: {
  projectId: string
  enabled: boolean
  risk?: ReleaseRiskDetail
  loading: boolean
}) {
  return (
    <Card
      title="失败根因与推荐测试"
      loading={loading}
      extra={<Link to={projectPath(projectId, 'quality')}>质量洞察</Link>}
    >
      {!enabled ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="质量智能能力未启用" />
      ) : !risk ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无发布风险分析" />
      ) : (
        <div className="quality-evidence-list">
          <Space wrap>
            <Typography.Text strong>{risk.title}</Typography.Text>
            <Tag color={riskColors[risk.risk_level]}>{riskLabels[risk.risk_level]}</Tag>
            <Typography.Text type="secondary">
              推荐 {risk.recommended_tests.length} 项
            </Typography.Text>
          </Space>
          {risk.failure_clusters.slice(0, 3).map((cluster) => (
            <div className="quality-evidence-item" key={cluster.id}>
              <div>
                <Typography.Text strong>{cluster.title}</Typography.Text>
                <Typography.Text type="secondary">
                  影响 {cluster.occurrence_count} 次 · 置信度 {Math.round(cluster.confidence * 100)}
                  %
                </Typography.Text>
              </div>
              <Tag color="error">{cluster.failure_category}</Tag>
            </div>
          ))}
          {risk.recommended_tests.slice(0, 3).map((item) => (
            <div className="quality-evidence-item" key={`${item.target_type}:${item.target_id}`}>
              <div>
                <Typography.Text strong>{item.name}</Typography.Text>
                <Typography.Text type="secondary">{item.reasons.join('；')}</Typography.Text>
              </div>
              <Tag color={item.priority === 'high' ? 'error' : 'warning'}>{item.priority}</Tag>
            </div>
          ))}
        </div>
      )}
    </Card>
  )
}

function ImpactEvidenceCard({
  projectId,
  enabled,
  impact,
  loading,
}: {
  projectId: string
  enabled: boolean
  impact?: ImpactRunSummary
  loading: boolean
}) {
  return (
    <Card
      title="最近变更影响"
      loading={loading}
      extra={<Link to={projectPath(projectId, 'impact')}>查看详情</Link>}
    >
      {!enabled ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="影响分析能力未启用" />
      ) : !impact ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无影响分析" />
      ) : (
        <div className="quality-impact-summary">
          <Space wrap>
            <Typography.Text strong>{impact.title}</Typography.Text>
            <Tag color={impact.summary.breaking_change_count ? 'error' : 'success'}>
              Breaking {impact.summary.breaking_change_count}
            </Tag>
          </Space>
          <Typography.Text type="secondary">来源：{impact.source_ref}</Typography.Text>
          <Progress percent={impact.summary.coverage_percent} />
          <Typography.Text type="secondary">
            {impact.change_count} 项变更 · 推荐 {impact.summary.selected_asset_count} 项测试 · 缺口{' '}
            {impact.summary.gap_count}
          </Typography.Text>
        </div>
      )}
    </Card>
  )
}

function ReleaseDecisionCard({
  projectId,
  decision,
  loading,
}: {
  projectId: string
  decision?: ReleaseDecision
  loading: boolean
}) {
  const blockedReasons = decision?.reasons.filter((reason) => reason.status === 'blocked') ?? []
  return (
    <Card
      title="最新发布判断"
      loading={loading}
      extra={<Link to={projectPath(projectId, 'release')}>发布门禁</Link>}
    >
      {!decision ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无历史发布判断" />
      ) : (
        <div className="release-decision-summary">
          <Space wrap>
            <Tag color={decision.status === 'pass' ? 'success' : 'error'}>
              {decision.status.toUpperCase()}
            </Tag>
            <Typography.Text strong>{decision.candidate_ref}</Typography.Text>
          </Space>
          <Typography.Text type="secondary">
            不可变证据 {decision.fingerprint.slice(0, 12)}… · 阻断原因 {blockedReasons.length} 项
          </Typography.Text>
          {blockedReasons.slice(0, 3).map((reason) => (
            <Alert key={reason.code} type="error" showIcon title={reason.message} />
          ))}
        </div>
      )}
    </Card>
  )
}

function RecentExecutionTable({ items }: { items: RecentExecution[] }) {
  if (!items.length) return <Empty description="暂无执行记录" />
  return (
    <Table
      rowKey={(record) => `${record.kind}:${record.id}`}
      size="small"
      pagination={false}
      dataSource={items}
      columns={[
        {
          title: '类型',
          dataIndex: 'kind',
          width: 76,
          render: (kind: RecentExecution['kind']) => (kind === 'api' ? '接口' : '工作流'),
        },
        { title: '名称', dataIndex: 'target_name', ellipsis: true },
        { title: '项目', dataIndex: 'project_name', ellipsis: true },
        {
          title: '状态',
          dataIndex: 'status',
          width: 82,
          render: (status: string) => (
            <Tag color={statusColors[status] ?? 'default'}>{statusLabels[status] ?? status}</Tag>
          ),
        },
        {
          title: '开始时间',
          dataIndex: 'started_at',
          width: 150,
          render: (value: string) => formatShanghaiTime(value),
        },
      ]}
    />
  )
}

function formatShanghaiTime(value: string): string {
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(new Date(value))
}

function required(value: string | null): string {
  if (!value) throw new Error('请选择项目')
  return value
}

type MetricState = { value: string; detail: string; tone?: string }

function riskMetric(risk: ReleaseRiskSummary | undefined, enabled: boolean): MetricState {
  if (!enabled) return { value: '—', detail: '质量智能能力未启用' }
  if (!risk) return { value: '—', detail: '暂无风险证据' }
  return {
    value: `${risk.score} / 100`,
    detail: riskLabels[risk.risk_level],
    tone: riskColors[risk.risk_level],
  }
}

function impactMetric(impact: ImpactRunSummary | undefined, enabled: boolean): MetricState {
  if (!enabled) return { value: '—', detail: '影响分析能力未启用' }
  if (!impact) return { value: '—', detail: '暂无影响分析证据' }
  return {
    value: `${impact.change_count} 项`,
    detail: `覆盖 ${impact.summary.coverage_percent}% · 缺口 ${impact.summary.gap_count}`,
    tone: impact.summary.gap_count > 0 ? 'warning' : 'success',
  }
}

function decisionMetric(decision: ReleaseDecision | undefined): MetricState {
  if (!decision) return { value: '—', detail: '暂无历史判断' }
  return {
    value: decision.status.toUpperCase(),
    detail: decision.candidate_ref,
    tone: decision.status === 'pass' ? 'success' : 'error',
  }
}

function executionTone(failed: number): string {
  return failed > 0 ? 'warning' : 'success'
}

function countTone(count: number): string {
  return count > 0 ? 'warning' : 'success'
}

function firstItem<T>(page: Page<T> | undefined): T | undefined {
  return page?.items.at(0)
}

function pageItems<T>(page: Page<T> | undefined): T[] {
  return page?.items ?? []
}

function valueOr<T>(value: T | undefined, fallback: T): T {
  return value ?? fallback
}

function anyLoading(...values: boolean[]): boolean {
  return values.some(Boolean)
}
