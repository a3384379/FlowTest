import { CheckCircleOutlined, CloseCircleOutlined, PlusOutlined } from '@ant-design/icons'
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Form,
  Input,
  InputNumber,
  Modal,
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
  ReleaseDecision,
  ReleaseDecisionInput,
  ReleasePolicyInput,
} from '../features/release-gate/release-gate-service'
import { useReleaseGate } from '../features/release-gate/use-release-gate'

export default function ReleaseGatePage() {
  const state = useReleaseGate()
  const [policyOpen, setPolicyOpen] = useState(false)
  const [decisionOpen, setDecisionOpen] = useState(false)
  const [selected, setSelected] = useState<ReleaseDecision | null>(null)
  return (
    <>
      <ReleaseGateHeader
        projectSelected={Boolean(state.projectId)}
        hasPolicies={Boolean(state.policies.data?.length)}
        onCreatePolicy={() => setPolicyOpen(true)}
        onEvaluate={() => setDecisionOpen(true)}
      />
      <Space orientation="vertical" size="large" style={{ width: '100%' }}>
        <ReleaseOverview
          policyCount={state.policies.data?.length}
          decisionCount={state.decisions.data?.total}
          latest={state.decisions.data?.items.at(0)}
        />
        <PoliciesCard policies={state.policies.data} loading={state.policies.isLoading} />
        <DecisionsCard
          decisions={state.decisions.data?.items}
          loading={state.decisions.isLoading}
          onSelect={setSelected}
        />
      </Space>
      <PolicyDialogContainer state={state} open={policyOpen} onClose={() => setPolicyOpen(false)} />
      <DecisionDialogContainer
        state={state}
        open={decisionOpen}
        onClose={() => setDecisionOpen(false)}
      />
      <DecisionDetail decision={selected} onClose={() => setSelected(null)} />
    </>
  )
}

type ReleaseGateState = ReturnType<typeof useReleaseGate>

function ReleaseGateHeader({
  projectSelected,
  hasPolicies,
  onCreatePolicy,
  onEvaluate,
}: {
  projectSelected: boolean
  hasPolicies: boolean
  onCreatePolicy: () => void
  onEvaluate: () => void
}) {
  return (
    <div className="page-heading">
      <div>
        <Typography.Title level={2}>发布门禁</Typography.Title>
        <Typography.Text type="secondary">
          以不可变快照聚合质量、契约、影响、风险、性能与 Runner 证据，输出可解释的 PASS/BLOCK。
        </Typography.Text>
      </div>
      <Space>
        <Button icon={<PlusOutlined />} disabled={!projectSelected} onClick={onCreatePolicy}>
          新建策略
        </Button>
        <Button type="primary" disabled={!projectSelected || !hasPolicies} onClick={onEvaluate}>
          生成发布判断
        </Button>
      </Space>
    </div>
  )
}

function ReleaseOverview({
  policyCount,
  decisionCount,
  latest,
}: {
  policyCount: number | undefined
  decisionCount: number | undefined
  latest: ReleaseDecision | undefined
}) {
  return (
    <Card>
      <Space size="large">
        <Statistic title="发布策略" value={policyCount ?? 0} />
        <Statistic title="历史判断" value={decisionCount ?? 0} />
        <Statistic
          title="最新结果"
          value={latest ? latest.status.toUpperCase() : '—'}
          styles={{ content: { color: latest?.status === 'pass' ? '#389e0d' : '#cf1322' } }}
        />
      </Space>
    </Card>
  )
}

function PoliciesCard({
  policies,
  loading,
}: {
  policies: ReleaseGateState['policies']['data']
  loading: boolean
}) {
  return (
    <Card title="发布策略" loading={loading}>
      <Table
        rowKey="id"
        size="small"
        pagination={false}
        dataSource={policies ?? []}
        locale={{ emptyText: '暂无发布策略' }}
        columns={[
          { title: '名称', dataIndex: 'name' },
          {
            title: 'Impact 覆盖率',
            dataIndex: 'min_impact_coverage_percent',
            render: (value: number) => `≥ ${value}%`,
          },
          {
            title: '风险上限',
            dataIndex: 'max_release_risk_score',
            render: (value: number) => `≤ ${value}`,
          },
          { title: '附加证据', render: (_, row) => <AdditionalEvidence policy={row} /> },
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
  )
}

function AdditionalEvidence({ policy }: { policy: ReleasePolicyInput }) {
  if (!policy.require_performance_evidence && !policy.require_runner_evidence) return '—'
  return (
    <Space>
      {policy.require_performance_evidence && <Tag>性能</Tag>}
      {policy.require_runner_evidence && <Tag>Runner</Tag>}
    </Space>
  )
}

function DecisionsCard({
  decisions,
  loading,
  onSelect,
}: {
  decisions: ReleaseDecision[] | undefined
  loading: boolean
  onSelect: (decision: ReleaseDecision) => void
}) {
  return (
    <Card title="不可变发布判断" loading={loading}>
      <Table
        rowKey="id"
        size="small"
        pagination={{ pageSize: 10 }}
        dataSource={decisions ?? []}
        locale={{ emptyText: '暂无发布判断' }}
        columns={[
          { title: '候选版本', dataIndex: 'candidate_ref' },
          {
            title: '结果',
            dataIndex: 'status',
            render: (value: ReleaseDecision['status']) => <DecisionTag status={value} />,
          },
          {
            title: '阻断项',
            render: (_, row) => row.reasons.filter((item) => item.status === 'blocked').length,
          },
          {
            title: '证据指纹',
            dataIndex: 'fingerprint',
            render: (value: string) => <Typography.Text code>{value.slice(0, 12)}</Typography.Text>,
          },
          {
            title: '判断时间',
            dataIndex: 'created_at',
            render: (value: string) => new Date(value).toLocaleString('zh-CN', { hour12: false }),
          },
          {
            title: '操作',
            render: (_, row) => (
              <Button type="link" onClick={() => onSelect(row)}>
                查看证据
              </Button>
            ),
          },
        ]}
      />
    </Card>
  )
}

function PolicyDialogContainer({
  state,
  open,
  onClose,
}: {
  state: ReleaseGateState
  open: boolean
  onClose: () => void
}) {
  return (
    <PolicyDialog
      open={open}
      qualityGates={state.qualityGates.data ?? []}
      submitting={state.creatingPolicy}
      onClose={onClose}
      onCreate={async (input) => {
        if (await state.addPolicy(input)) onClose()
      }}
    />
  )
}

function DecisionDialogContainer({
  state,
  open,
  onClose,
}: {
  state: ReleaseGateState
  open: boolean
  onClose: () => void
}) {
  return (
    <DecisionDialog
      open={open}
      submitting={state.evaluating}
      policies={arrayOrEmpty(state.policies.data)}
      qualityRuns={pageItems(state.qualityRuns.data)}
      deploymentChecks={pageItems(state.deploymentChecks.data)}
      impactRuns={pageItems(state.impactRuns.data)}
      releaseRisks={pageItems(state.releaseRisks.data)}
      performanceRuns={pageItems(state.performanceRuns.data)}
      runnerTasks={pageItems(state.runnerTasks.data).filter(
        (item) => item.project_id === state.projectId,
      )}
      onClose={onClose}
      onCreate={async (input) => {
        if (await state.evaluate(input)) onClose()
      }}
    />
  )
}

function PolicyDialog({
  open,
  qualityGates,
  submitting,
  onClose,
  onCreate,
}: {
  open: boolean
  qualityGates: Array<{ id: string; name: string }>
  submitting: boolean
  onClose: () => void
  onCreate: (input: ReleasePolicyInput) => Promise<void>
}) {
  const [form] = Form.useForm<ReleasePolicyInput>()
  return (
    <Modal
      title="新建发布策略"
      open={open}
      confirmLoading={submitting}
      onCancel={onClose}
      onOk={() => form.submit()}
      destroyOnHidden
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={defaultPolicy()}
        onFinish={(values) => void onCreate(values)}
      >
        <Form.Item name="name" label="策略名称" rules={[{ required: true }]}>
          <Input />
        </Form.Item>
        <Form.Item noStyle dependencies={['require_quality_gate']}>
          {({ getFieldValue }) => (
            <Form.Item
              name="quality_gate_id"
              label="Quality Gate"
              rules={[
                {
                  required: Boolean(getFieldValue('require_quality_gate')),
                  message: '要求质量门禁证据时必须选择 Quality Gate',
                },
              ]}
            >
              <Select
                allowClear
                options={qualityGates.map((item) => ({ value: item.id, label: item.name }))}
              />
            </Form.Item>
          )}
        </Form.Item>
        <Space size="large">
          <Form.Item name="min_impact_coverage_percent" label="Impact 最低覆盖率">
            <InputNumber min={0} max={100} />
          </Form.Item>
          <Form.Item name="max_release_risk_score" label="Release Risk 上限">
            <InputNumber min={0} max={100} />
          </Form.Item>
        </Space>
        <Space orientation="vertical">
          <SwitchField name="require_quality_gate" label="要求 Quality Gate" />
          <SwitchField name="require_contract_compatibility" label="要求契约兼容证据" />
          <SwitchField name="require_impact_evidence" label="要求 Impact 证据" />
          <SwitchField name="require_release_risk" label="要求 Release Risk 证据" />
          <SwitchField name="require_performance_evidence" label="要求性能证据" />
          <SwitchField name="require_runner_evidence" label="要求 Runner Fence 证据" />
        </Space>
        <Form.Item name="enabled" valuePropName="checked" hidden>
          <Switch />
        </Form.Item>
      </Form>
    </Modal>
  )
}

function SwitchField({ name, label }: { name: keyof ReleasePolicyInput; label: string }) {
  return (
    <Form.Item name={name} valuePropName="checked" label={label} layout="horizontal">
      <Switch />
    </Form.Item>
  )
}

type EvidenceOption = { id: string; label: string }

function DecisionDialog({
  open,
  submitting,
  policies,
  qualityRuns,
  deploymentChecks,
  impactRuns,
  releaseRisks,
  performanceRuns,
  runnerTasks,
  onClose,
  onCreate,
}: {
  open: boolean
  submitting: boolean
  policies: Array<{ id: string; name: string; enabled: boolean }>
  qualityRuns: Array<{ id: string; status: string }>
  deploymentChecks: Array<{ id: string; provider_version: string; decision: string }>
  impactRuns: Array<{ id: string; title: string; status: string }>
  releaseRisks: Array<{ id: string; title: string; score: number }>
  performanceRuns: Array<{ id: string; status: string; scenario_version: number }>
  runnerTasks: Array<{ id: string; status: string; fencing_token: number }>
  onClose: () => void
  onCreate: (input: ReleaseDecisionInput) => Promise<void>
}) {
  const [form] = Form.useForm<ReleaseDecisionInput>()
  return (
    <Modal
      title="生成发布判断"
      open={open}
      width={720}
      confirmLoading={submitting}
      onCancel={onClose}
      onOk={() => form.submit()}
      destroyOnHidden
    >
      <Alert
        type="info"
        showIcon
        title="每次判断都会固定策略和证据快照；缺失策略要求的证据将生成 BLOCK。"
      />
      <Form form={form} layout="vertical" onFinish={(values) => void onCreate(compact(values))}>
        <Form.Item name="release_policy_id" label="发布策略" rules={[{ required: true }]}>
          <Select
            options={policies
              .filter((item) => item.enabled)
              .map((item) => ({ value: item.id, label: item.name }))}
          />
        </Form.Item>
        <Form.Item name="candidate_ref" label="候选版本" rules={[{ required: true }]}>
          <Input placeholder="例如 v3.0.0-rc.1" />
        </Form.Item>
        <div className="quality-grid">
          <EvidenceSelect
            name="test_plan_run_id"
            label="Quality Gate 运行"
            items={qualityRuns.map((item) => ({
              id: item.id,
              label: `${short(item.id)} · ${item.status}`,
            }))}
          />
          <EvidenceSelect
            name="deployment_check_id"
            label="契约兼容判断"
            items={deploymentChecks.map((item) => ({
              id: item.id,
              label: `${item.provider_version} · ${item.decision}`,
            }))}
          />
          <EvidenceSelect
            name="impact_run_id"
            label="Impact Run"
            items={impactRuns.map((item) => ({
              id: item.id,
              label: `${item.title} · ${item.status}`,
            }))}
          />
          <EvidenceSelect
            name="release_risk_id"
            label="Release Risk"
            items={releaseRisks.map((item) => ({
              id: item.id,
              label: `${item.title} · ${item.score}`,
            }))}
          />
          <EvidenceSelect
            name="performance_run_id"
            label="性能运行"
            items={performanceRuns.map((item) => ({
              id: item.id,
              label: `v${item.scenario_version} · ${item.status}`,
            }))}
          />
          <EvidenceSelect
            name="runner_task_id"
            label="Runner 任务"
            items={runnerTasks.map((item) => ({
              id: item.id,
              label: `${short(item.id)} · ${item.status} · fence ${item.fencing_token}`,
            }))}
          />
        </div>
      </Form>
    </Modal>
  )
}

function EvidenceSelect({
  name,
  label,
  items,
}: {
  name: keyof ReleaseDecisionInput
  label: string
  items: EvidenceOption[]
}) {
  return (
    <Form.Item name={name} label={label}>
      <Select
        allowClear
        showSearch
        optionFilterProp="label"
        placeholder="未选择"
        options={items.map((item) => ({ value: item.id, label: item.label }))}
      />
    </Form.Item>
  )
}

function DecisionDetail({
  decision,
  onClose,
}: {
  decision: ReleaseDecision | null
  onClose: () => void
}) {
  return (
    <Modal
      title="发布判断证据"
      open={Boolean(decision)}
      footer={null}
      onCancel={onClose}
      width={800}
    >
      {decision && (
        <Space orientation="vertical" size="large" style={{ width: '100%' }}>
          <Descriptions bordered size="small" column={2}>
            <Descriptions.Item label="候选版本">{decision.candidate_ref}</Descriptions.Item>
            <Descriptions.Item label="结果">
              <DecisionTag status={decision.status} />
            </Descriptions.Item>
            <Descriptions.Item label="证据指纹" span={2}>
              <Typography.Text code copyable>
                {decision.fingerprint}
              </Typography.Text>
            </Descriptions.Item>
          </Descriptions>
          <Table
            rowKey="code"
            size="small"
            pagination={false}
            dataSource={decision.reasons}
            columns={[
              {
                title: '状态',
                dataIndex: 'status',
                render: (value: string) => (
                  <Tag color={value === 'passed' ? 'success' : 'error'}>
                    {value === 'passed' ? '通过' : '阻断'}
                  </Tag>
                ),
              },
              { title: '证据', dataIndex: 'evidence_type' },
              { title: '原因', dataIndex: 'message' },
              { title: '代码', dataIndex: 'code' },
            ]}
          />
          <Typography.Text type="secondary">
            历史判断只读；策略后续修改不会改变本次策略快照与证据指纹。
          </Typography.Text>
        </Space>
      )}
    </Modal>
  )
}

function DecisionTag({ status }: { status: ReleaseDecision['status'] }) {
  return status === 'pass' ? (
    <Tag color="success" icon={<CheckCircleOutlined />}>
      PASS
    </Tag>
  ) : (
    <Tag color="error" icon={<CloseCircleOutlined />}>
      BLOCK
    </Tag>
  )
}

function defaultPolicy(): ReleasePolicyInput {
  return {
    name: '',
    enabled: true,
    quality_gate_id: null,
    require_quality_gate: true,
    require_contract_compatibility: true,
    require_impact_evidence: true,
    min_impact_coverage_percent: 80,
    require_release_risk: true,
    max_release_risk_score: 50,
    require_performance_evidence: false,
    require_runner_evidence: false,
  }
}

function compact(input: ReleaseDecisionInput): ReleaseDecisionInput {
  return Object.fromEntries(
    Object.entries(input).filter(([, value]) => value !== undefined && value !== ''),
  ) as ReleaseDecisionInput
}

function short(value: string): string {
  return value.slice(0, 8)
}

function arrayOrEmpty<T>(items: T[] | undefined): T[] {
  return items ? items : []
}

function pageItems<T>(page: { items: T[] } | undefined): T[] {
  return page ? page.items : []
}
