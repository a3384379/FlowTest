import { DownloadOutlined, PlusOutlined, SafetyCertificateOutlined } from '@ant-design/icons'
import {
  Button,
  Card,
  Col,
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
import { useState } from 'react'

import type {
  QualityGateInput,
  ReleaseRiskDetail,
  ReleaseRiskInput,
} from '../features/quality/quality-service'
import type { ImpactRunSummary } from '../features/impact/impact-service'
import { useQualityCenter } from '../features/quality/use-quality-center'
import type { TestPlanRun } from '../lib/api'

export default function QualityCenterPage() {
  const state = useQualityCenter()
  const [createOpen, setCreateOpen] = useState(false)
  const [riskOpen, setRiskOpen] = useState(false)
  const records = pageItems(state.flaky.data)
  const latest = firstPageItem(state.runs.data)
  return (
    <>
      <div className="page-heading">
        <div>
          <Typography.Title level={2}>质量中心</Typography.Title>
          <Typography.Text type="secondary">
            统一管理 CI 质量门禁、Flaky 隔离、基线对比与 JUnit 产物。
          </Typography.Text>
        </div>
        <Space>
          <Button disabled={!state.projectId} onClick={() => setRiskOpen(true)}>
            分析发布风险
          </Button>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            disabled={!state.projectId}
            onClick={() => setCreateOpen(true)}
          >
            新建门禁
          </Button>
        </Space>
      </div>
      <QualityOverview
        gateCount={listItems(state.gates.data).length}
        flakyCount={records.filter((item) => item.flaky_score > 0).length}
        quarantinedCount={records.filter((item) => item.quarantined).length}
        latest={latest}
      />
      <QualityInsights risk={state.risk.data} loading={state.risk.isLoading} />
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
          <Table
            rowKey="id"
            size="small"
            pagination={{ pageSize: 8 }}
            dataSource={records}
            locale={{ emptyText: '暂无 Flaky 记录' }}
            columns={[
              {
                title: '资产',
                render: (_, row) =>
                  `${row.target_type}:${row.target_id.slice(0, 8)}@${row.target_version}`,
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
                    aria-label={`隔离 ${row.target_id}`}
                    checked={value}
                    loading={state.toggling}
                    onChange={(checked) => void state.toggleQuarantine(row.id, checked)}
                  />
                ),
              },
            ]}
          />
        </Card>
      </div>
      <Card title="最近运行与基线" className="quality-runs-card" loading={state.runs.isLoading}>
        <Table
          rowKey="id"
          size="small"
          pagination={false}
          dataSource={pageItems(state.runs.data)}
          locale={{ emptyText: '暂无运行数据' }}
          columns={[
            { title: '运行 ID', dataIndex: 'id', render: (value: string) => value.slice(0, 8) },
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
                <Button
                  type="link"
                  icon={<DownloadOutlined />}
                  disabled={!['passed', 'failed', 'cancelled'].includes(run.status)}
                  onClick={() => void state.exportJunit(run.id)}
                >
                  JUnit
                </Button>
              ),
            },
          ]}
        />
      </Card>
      <CreateGateDialog
        open={createOpen}
        submitting={state.creating}
        onClose={() => setCreateOpen(false)}
        onCreate={async (input) => {
          if (await state.addGate(input)) setCreateOpen(false)
        }}
      />
      <CreateRiskDialog
        open={riskOpen}
        submitting={state.analyzingRisk}
        impactRuns={pageItems(state.impactRuns.data)}
        onClose={() => setRiskOpen(false)}
        onCreate={async (input) => {
          if (await state.addRisk(input)) setRiskOpen(false)
        }}
      />
    </>
  )
}

function QualityInsights({
  risk,
  loading,
}: {
  risk: ReleaseRiskDetail | undefined
  loading: boolean
}) {
  return (
    <Card title="质量洞察与可解释发布风险" loading={loading} className="quality-runs-card">
      {!risk ? (
        <Typography.Text type="secondary">
          选择一条影响分析生成发布风险快照，失败聚类与风险因子将固定保存。
        </Typography.Text>
      ) : (
        <Space orientation="vertical" size="large" style={{ width: '100%' }}>
          <Row gutter={16}>
            <Col span={6}>
              <Statistic title="质量评分" value={risk.quality_score} suffix="/ 100" />
            </Col>
            <Col span={6}>
              <Statistic
                title="发布风险"
                value={risk.score}
                suffix={<Tag color={riskColor(risk.risk_level)}>{riskLabel(risk.risk_level)}</Tag>}
              />
            </Col>
            <Col span={6}>
              <Statistic
                title="覆盖缺口"
                value={nestedNumber(risk.evidence_snapshot, 'impact', 'coverage_gap_count')}
              />
            </Col>
            <Col span={6}>
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
                dataSource={risk.recommended_tests}
                locale={{ emptyText: '暂无有证据的测试建议' }}
                columns={[
                  { title: '资产', dataIndex: 'name' },
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
                ]}
              />
            </Card>
          </div>
          <Table
            rowKey="id"
            size="small"
            pagination={false}
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
  gateCount,
  flakyCount,
  quarantinedCount,
  latest,
}: {
  gateCount: number
  flakyCount: number
  quarantinedCount: number
  latest: TestPlanRun | undefined
}) {
  const passRate = latest?.quality_summary.pass_rate
  return (
    <Row gutter={16} className="quality-overview">
      <Col span={6}>
        <Card>
          <Statistic title="启用门禁" value={gateCount} prefix={<SafetyCertificateOutlined />} />
        </Card>
      </Col>
      <Col span={6}>
        <Card>
          <Statistic title="Flaky 资产" value={flakyCount} />
        </Card>
      </Col>
      <Col span={6}>
        <Card>
          <Statistic title="已隔离" value={quarantinedCount} />
        </Card>
      </Col>
      <Col span={6}>
        <Card>
          <Statistic
            title="最近通过率"
            value={typeof passRate === 'number' ? passRate : 0}
            suffix="%"
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

function nestedNumber(value: Record<string, unknown>, parent: string, child: string): number {
  const nested = value[parent]
  if (!nested || typeof nested !== 'object') return 0
  const result = (nested as Record<string, unknown>)[child]
  return typeof result === 'number' ? result : 0
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
  return `通过率 ${value.pass_rate}% · 失败 ${String(value.failed ?? 0)} · Flaky ${String(value.flaky ?? 0)}`
}
