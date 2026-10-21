import { Link } from 'react-router-dom'
import { projectPath, type ProjectSection } from '../projects/project-routing'
import { Alert, Descriptions, Form, Input, Modal, Select, Tag, Typography } from 'antd'
import QueryFailureNotice from '../../components/QueryFailureNotice'
import ResponseCodeReader from '../api-console/ResponseCodeReader'
import type { V3FeatureFlags } from '../capabilities/capability-service'
import type { ReleaseDecisionInput, ReleasePolicy } from './release-gate-service'
import ReleaseEvidencePicker, { type EvidenceOption } from './ReleaseEvidencePicker'
import { releaseEvidenceLabels, type ReleaseEvidenceKind } from './release-evidence-types'
import type { useReleaseGate } from './use-release-gate'

type State = ReturnType<typeof useReleaseGate>
type Requirement = {
  kind: ReleaseEvidenceKind
  field: keyof ReleaseDecisionInput
  rule: keyof ReleasePolicy
  label: string
  feature: keyof V3FeatureFlags | null
}
const requirements: Requirement[] = [
  {
    kind: 'quality_gate',
    field: 'test_plan_run_id',
    rule: 'require_quality_gate',
    label: 'Quality Gate 运行',
    feature: null,
  },
  {
    kind: 'contract_compatibility',
    field: 'deployment_check_id',
    rule: 'require_contract_compatibility',
    label: '契约兼容判断',
    feature: 'contract_hub',
  },
  {
    kind: 'impact',
    field: 'impact_run_id',
    rule: 'require_impact_evidence',
    label: 'Impact Run',
    feature: 'impact_engine',
  },
  {
    kind: 'release_risk',
    field: 'release_risk_id',
    rule: 'require_release_risk',
    label: 'Release Risk',
    feature: 'quality_intelligence',
  },
  {
    kind: 'performance',
    field: 'performance_run_id',
    rule: 'require_performance_evidence',
    label: '性能运行',
    feature: 'performance_lab',
  },
  {
    kind: 'runner',
    field: 'runner_task_id',
    rule: 'require_runner_evidence',
    label: 'Runner 任务',
    feature: 'runner_fabric',
  },
]

export default function ReleaseDecisionDialog({
  state,
  open,
  onClose,
}: {
  state: State
  open: boolean
  onClose: () => void
}) {
  const [form] = Form.useForm<ReleaseDecisionInput>()
  const values = Form.useWatch([], form) as ReleaseDecisionInput | undefined
  const policy = state.policies.data?.find((item) => item.id === values?.release_policy_id)
  const directories = {
    quality_gate: state.qualityRuns,
    contract_compatibility: state.deploymentChecks,
    impact: state.impactRuns,
    release_risk: state.releaseRisks,
    performance: state.performanceRuns,
    runner: state.runnerTasks,
  }
  const options = evidenceOptions(state)
  return (
    <Modal
      title="生成发布判断"
      style={{ top: 24 }}
      styles={{ body: { maxHeight: 'calc(100dvh - 168px)', overflowY: 'auto' } }}
      open={open}
      width={960}
      confirmLoading={state.evaluating}
      onCancel={onClose}
      onOk={() => form.submit()}
      destroyOnHidden
    >
      <Alert
        type="info"
        showIcon
        title="每次判断都会固定策略和证据快照；缺失策略要求的证据将生成 BLOCK。"
      />
      <QueryFailureNotice queries={[state.featureFlags]} />
      <Form
        form={form}
        layout="vertical"
        onFinish={async (input) => {
          if (await state.evaluate(compact(input))) onClose()
        }}
      >
        <Form.Item name="release_policy_id" label="发布策略" rules={[{ required: true }]}>
          <Select
            options={(state.policies.data ?? [])
              .filter((item) => item.enabled)
              .map((item) => ({ value: item.id, label: item.name }))}
          />
        </Form.Item>
        <Form.Item
          name="candidate_ref"
          label="候选版本"
          rules={[{ required: true, whitespace: true }]}
        >
          <Input placeholder="例如 v3.0.0-rc.1" maxLength={200} />
        </Form.Item>
        <Typography.Paragraph strong>
          {policy
            ? `必需证据：${requirements.filter((item) => policy[item.rule] === true).length} 类`
            : '选择发布策略后查看必需证据'}
        </Typography.Paragraph>
        <Typography.Paragraph type="secondary">
          缺失必需证据仍可评估，结果将由后端按冻结策略判断为 BLOCK
        </Typography.Paragraph>
        <div className="quality-grid">
          {requirements.map((item) => (
            <div key={item.kind}>
              <Tag color={policy?.[item.rule] === true ? 'orange' : 'default'}>
                {policy ? (policy[item.rule] === true ? '必需' : '可选') : '待选择策略'}
              </Tag>
              <Form.Item name={item.field} label={item.label}>
                <ReleaseEvidencePicker
                  key={`${state.projectId}:${item.kind}`}
                  projectId={state.projectId!}
                  kind={item.kind}
                  label={item.label}
                  query={directories[item.kind]}
                  options={options[item.kind]}
                  availability={availability(state, item)}
                  onSearch={searchHandler(state, item.kind)}
                />
              </Form.Item>
              <CollectionLink projectId={state.projectId!} kind={item.kind} />
            </div>
          ))}
        </div>
        <section aria-label="提交前冻结对象摘要">
          <Typography.Title level={5}>提交前核对</Typography.Title>
          <Descriptions
            size="small"
            column={1}
            items={[
              { key: 'candidate', label: '候选版本', children: values?.candidate_ref || '未提供' },
              { key: 'policy', label: '策略', children: policy?.name ?? '未提供' },
              ...requirements.map((item) => ({
                key: item.kind,
                label: releaseEvidenceLabels[item.kind],
                children: values?.[item.field] || '未提供',
              })),
            ]}
          />
          <Typography.Paragraph type="secondary">
            此处为拟提交的对象引用。服务端创建判断时冻结实际策略与证据，界面不会自动补选证据。
          </Typography.Paragraph>
          {policy && <ResponseCodeReader value={policy} title="本次拟采用策略" />}
        </section>
      </Form>
    </Modal>
  )
}

function availability(state: State, requirement: Requirement): string | null {
  if (!requirement.feature) return null
  if (state.featureFlags.isError) return '功能开关读取失败，暂不能核对该类证据可用性'
  if (!state.featureFlags.isSuccess) return '正在读取功能开关'
  return state.featureFlags.data[requirement.feature]
    ? null
    : `${releaseEvidenceLabels[requirement.kind]}能力已关闭`
}

function searchHandler(state: State, kind: ReleaseEvidenceKind) {
  if (kind === 'performance') return state.setPerformanceSearch
  if (kind === 'runner') return state.setRunnerSearch
  return undefined
}

function evidenceOptions(state: State): Record<ReleaseEvidenceKind, EvidenceOption[]> {
  return {
    quality_gate: pageItems(state.qualityRuns).map((item) => ({
      id: item.id,
      label: `${item.id.slice(0, 8)} · ${item.status}`,
      observedAt: item.created_at,
    })),
    contract_compatibility: pageItems(state.deploymentChecks).map((item) => ({
      id: item.id,
      label: `${item.provider_version} · ${item.decision}`,
      observedAt: item.created_at,
    })),
    impact: pageItems(state.impactRuns).map((item) => ({
      id: item.id,
      label: `${item.title} · ${item.status}`,
      observedAt: item.created_at,
    })),
    release_risk: pageItems(state.releaseRisks).map((item) => ({
      id: item.id,
      label: `${item.title} · ${item.score}`,
      observedAt: item.created_at,
    })),
    performance: pageItems(state.performanceRuns).map((item) => ({
      id: item.id,
      label: `v${item.scenario_version} · ${item.status}`,
      observedAt: item.completed_at ?? item.created_at,
    })),
    runner: pageItems(state.runnerTasks).map((item) => ({
      id: item.id,
      label: `${item.id.slice(0, 8)} · ${item.status} · fence ${item.fencing_token}`,
      observedAt: item.completed_at ?? item.created_at,
    })),
  }
}

function compact(input: ReleaseDecisionInput): ReleaseDecisionInput {
  return Object.fromEntries(
    Object.entries(input).filter(([, value]) => value !== undefined && value !== ''),
  ) as ReleaseDecisionInput
}

function pageItems<T>(query: { data?: { items: T[] } }): T[] {
  return query.data?.items ?? []
}

function CollectionLink({ projectId, kind }: { projectId: string; kind: ReleaseEvidenceKind }) {
  const sections: Record<ReleaseEvidenceKind, ProjectSection> = {
    quality_gate: 'tasks',
    contract_compatibility: 'contracts',
    impact: 'impact',
    release_risk: 'quality',
    performance: 'performance',
    runner: 'reports',
  }
  return (
    <Typography.Paragraph>
      <Link to={projectPath(projectId, sections[kind])} target="_blank" rel="noopener noreferrer">
        打开{releaseEvidenceLabels[kind]}收集入口（新标签页保留本表单）
      </Link>
    </Typography.Paragraph>
  )
}
