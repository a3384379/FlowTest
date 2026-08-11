import { DownloadOutlined, PlusOutlined, SafetyCertificateOutlined } from '@ant-design/icons'
import {
  Button,
  Card,
  Col,
  Form,
  Input,
  InputNumber,
  Modal,
  Row,
  Space,
  Statistic,
  Switch,
  Table,
  Tag,
  Typography,
} from 'antd'
import { useState } from 'react'

import type { QualityGateInput } from '../features/quality/quality-service'
import { useQualityCenter } from '../features/quality/use-quality-center'
import type { TestPlanRun } from '../lib/api'

export default function QualityCenterPage() {
  const state = useQualityCenter()
  const [createOpen, setCreateOpen] = useState(false)
  const records = state.flaky.data?.items ?? []
  const latest = state.runs.data?.items.at(0)
  return (
    <>
      <div className="page-heading">
        <div>
          <Typography.Title level={2}>质量中心</Typography.Title>
          <Typography.Text type="secondary">
            统一管理 CI 质量门禁、Flaky 隔离、基线对比与 JUnit 产物。
          </Typography.Text>
        </div>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          disabled={!state.projectId}
          onClick={() => setCreateOpen(true)}
        >
          新建门禁
        </Button>
      </div>
      <QualityOverview
        gateCount={state.gates.data?.length ?? 0}
        flakyCount={records.filter((item) => item.flaky_score > 0).length}
        quarantinedCount={records.filter((item) => item.quarantined).length}
        latest={latest}
      />
      <div className="quality-grid">
        <Card title="质量门禁" loading={state.gates.isLoading}>
          <Table
            rowKey="id"
            size="small"
            pagination={false}
            dataSource={state.gates.data ?? []}
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
          dataSource={state.runs.data?.items ?? []}
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
    </>
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

function qualitySummary(value: Record<string, unknown>): string {
  if (typeof value.pass_rate !== 'number') return '待生成'
  return `通过率 ${value.pass_rate}% · 失败 ${String(value.failed ?? 0)} · Flaky ${String(value.flaky ?? 0)}`
}
