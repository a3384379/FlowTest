import ReleaseEvidenceSources from '../features/release-gate/ReleaseEvidenceSources'
import ReleaseDecisionDialog from '../features/release-gate/ReleaseDecisionDialog'
import { useProjectContext } from '../features/projects/use-project-context'
import QueryFailureNotice from '../components/QueryFailureNotice'
import CatalogPagination from '../components/CatalogPagination'
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
  Tabs,
  Tag,
  Typography,
} from 'antd'
import { useState } from 'react'
import { apiErrorMessage } from '../lib/api'
import ResponseCodeReader from '../features/api-console/ResponseCodeReader'
import { iceColors } from '../theme/ice-theme'

import type {
  ReleaseDecision,
  ReleasePolicyInput,
  ReleaseReason,
} from '../features/release-gate/release-gate-service'
import { useReleaseGate } from '../features/release-gate/use-release-gate'

export default function ReleaseGatePage() {
  const { projectId } = useProjectContext()
  return <ReleaseGateWorkspace key={projectId ?? 'none'} />
}

function ReleaseGateWorkspace() {
  const state = useReleaseGate()
  const [policyOpen, setPolicyOpen] = useState(false)
  const [decisionOpen, setDecisionOpen] = useState(false)
  return (
    <>
      <QueryFailureNotice queries={[state.policies, state.latestDecision]} />
      <ReleaseGateHeader
        projectSelected={state.canEdit}
        hasPolicies={Boolean(state.policies.data?.length)}
        onCreatePolicy={() => setPolicyOpen(true)}
        onEvaluate={() => setDecisionOpen(true)}
      />
      <div className="catalog-controls">
        <CatalogPagination query={state.decisions} label="门禁判断历史" />
        <CatalogPagination query={state.qualityRuns} label="质量运行证据" />
        <CatalogPagination query={state.deploymentChecks} label="契约判断证据" />
        <CatalogPagination query={state.impactRuns} label="影响证据" />
        <CatalogPagination query={state.releaseRisks} label="风险证据" />
      </div>
      <Space orientation="vertical" size="large" style={{ width: '100%' }}>
        <ReleaseOverview
          policyCount={state.policies.data?.length}
          decisionCount={state.decisions.data?.total}
          latest={state.latestDecision.data?.items.at(0)}
        />
        {state.latestDecision.data?.items[0] && (
          <LatestDecisionEvidence
            decision={state.latestDecision.data.items[0]}
            onOpen={() => state.selectDecision(state.latestDecision.data!.items[0].id)}
          />
        )}
        <PoliciesCard policies={state.policies.data} loading={state.policies.isLoading} />
        <DecisionsCard
          decisions={state.decisions.data?.items}
          loading={state.decisions.isLoading}
          onSelect={(decision) => state.selectDecision(decision.id)}
        />
      </Space>
      <PolicyDialogContainer state={state} open={policyOpen} onClose={() => setPolicyOpen(false)} />
      <ReleaseDecisionDialog
        state={state}
        open={decisionOpen}
        onClose={() => setDecisionOpen(false)}
      />
      <DecisionDetail
        decision={
          state.selectedDecision.data?.project_id === state.projectId
            ? state.selectedDecision.data
            : null
        }
        open={Boolean(state.decisionId)}
        loading={state.selectedDecision.isPending}
        error={state.selectedDecision.error}
        onRetry={() => void state.selectedDecision.refetch()}
        onClose={() => state.selectDecision(null)}
      />
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
      <div className="release-overview-metrics">
        <Statistic title="发布策略" value={policyCount ?? '—'} />
        <Statistic title="历史判断" value={decisionCount ?? '—'} />
        <Statistic
          title="最新结果"
          value={latest ? latest.status.toUpperCase() : '—'}
          styles={{
            content: {
              color: !latest
                ? iceColors.textTertiary
                : latest.status === 'pass'
                  ? iceColors.success
                  : iceColors.danger,
            },
          }}
        />
      </div>
      <Typography.Paragraph type="secondary" className="release-evidence-context">
        {latest
          ? `候选版本 ${latest.candidate_ref} · ${latest.reasons.filter((reason) => reason.status === 'blocked').length} 项阻断 · 判断只读`
          : '尚无发布判断。按策略收集必需证据后，才能生成 PASS/BLOCK。'}
      </Typography.Paragraph>
    </Card>
  )
}

function LatestDecisionEvidence({
  decision,
  onOpen,
}: {
  decision: ReleaseDecision
  onOpen: () => void
}) {
  const reasons = [...decision.reasons].sort(
    (left, right) => Number(left.status !== 'blocked') - Number(right.status !== 'blocked'),
  )
  return (
    <section className="release-decision-workspace" aria-label="最新判断的冻结证据">
      <Card title="逐项证据">
        <Table<ReleaseReason>
          rowKey="code"
          size="small"
          pagination={false}
          scroll={{ x: 540 }}
          dataSource={reasons}
          locale={{ emptyText: '本次判断未提供逐项原因' }}
          columns={[
            {
              title: '结果',
              dataIndex: 'status',
              width: 80,
              render: (status: ReleaseReason['status']) => (
                <Tag color={status === 'blocked' ? 'error' : 'success'}>
                  {status === 'blocked' ? '阻断' : '通过'}
                </Tag>
              ),
            },
            {
              title: '证据',
              dataIndex: 'evidence_type',
              width: 140,
              render: (type: ReleaseReason['evidence_type']) => releaseEvidenceLabels[type],
            },
            { title: '判断依据', dataIndex: 'message' },
          ]}
        />
      </Card>
      <Card title="决策上下文" extra={<Button onClick={onOpen}>打开此判断的证据来源</Button>}>
        <DecisionTag status={decision.status} />
        <Typography.Paragraph strong>候选版本 {decision.candidate_ref}</Typography.Paragraph>
        <Typography.Paragraph>策略：{decision.policy_snapshot.name}</Typography.Paragraph>
        <Typography.Paragraph>
          生成时间：{new Date(decision.created_at).toLocaleString('zh-CN', { hour12: false })}
        </Typography.Paragraph>
        <Typography.Paragraph>
          证据指纹：
          <Typography.Text code copyable>
            {decision.fingerprint}
          </Typography.Text>
        </Typography.Paragraph>
        <Typography.Text type="secondary">
          策略与证据来自本次冻结快照。重新判断会创建新记录；该结论不会触发生产部署。
        </Typography.Text>
      </Card>
    </section>
  )
}

const releaseEvidenceLabels: Readonly<Record<ReleaseReason['evidence_type'], string>> = {
  quality_gate: '质量门禁',
  contract_compatibility: '契约兼容',
  impact: '变更影响',
  release_risk: '发布风险',
  performance: '性能结果',
  runner: 'Runner 执行',
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

function DecisionDetail({
  open,
  loading,
  error,
  onRetry,
  decision,
  onClose,
}: {
  open: boolean
  loading: boolean
  error: unknown
  onRetry: () => void
  decision: ReleaseDecision | null
  onClose: () => void
}) {
  return (
    <Modal
      title="发布判断证据"
      open={open}
      loading={open && loading}
      footer={null}
      onCancel={onClose}
      width={800}
    >
      {error ? (
        <Alert
          type="error"
          showIcon
          title="发布判断读取失败"
          description={apiErrorMessage(error)}
          action={<Button onClick={onRetry}>重试</Button>}
        />
      ) : (
        decision && (
          <Space orientation="vertical" size="large" style={{ width: '100%' }}>
            <Descriptions bordered size="small" column={2}>
              <Descriptions.Item label="判断 ID">{decision.id}</Descriptions.Item>
              <Descriptions.Item label="冻结时间">{decision.created_at}</Descriptions.Item>
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
            <ReleaseEvidenceSources decision={decision} />
            <Tabs
              items={[
                {
                  key: 'policy',
                  label: '冻结策略',
                  children: (
                    <ResponseCodeReader value={decision.policy_snapshot} title="此判断的策略快照" />
                  ),
                },
                {
                  key: 'evidence',
                  label: '冻结证据',
                  children: (
                    <ResponseCodeReader
                      value={decision.evidence_snapshot}
                      title="此判断的证据快照"
                    />
                  ),
                },
              ]}
            />
            <Typography.Text type="secondary">
              历史判断只读；策略后续修改不会改变本次策略快照与证据指纹。
            </Typography.Text>
          </Space>
        )
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
