import { useMutation, useQuery } from '@tanstack/react-query'
import {
  Alert,
  App,
  Button,
  Checkbox,
  Descriptions,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Tag,
} from 'antd'

import { listContexts, type ContextSummary } from '../context-inspector/context-inspector-service'
import {
  apiErrorMessage,
  type FailureDiagnosisResponse,
  type FlowSpecDocument,
  type RepairKind,
  type WorkflowExecution,
} from '../../lib/api'
import { exportFlowSpec } from './flow-spec-service'
import { createRepairProposal, getFailureDiagnosis } from './failure-repair-service'

type Props = {
  open: boolean
  projectId: string
  execution: WorkflowExecution
  onClose: () => void
  onCreated: (proposalId: string) => void
}

export default function FailureRepairDialog(props: Props) {
  const diagnosis = useQuery({
    queryKey: ['failure-diagnosis', props.projectId, props.execution.id],
    queryFn: () => getFailureDiagnosis(props.projectId, props.execution.id),
    enabled: props.open,
  })
  const workflowId = diagnosis.data?.workflow_id
  const exported = useQuery({
    queryKey: ['failure-repair-export', props.projectId, workflowId],
    queryFn: () => exportFlowSpec(props.projectId, required(workflowId)),
    enabled: props.open && Boolean(workflowId),
  })
  const contexts = useQuery({
    queryKey: ['contexts', props.projectId],
    queryFn: () => listContexts(props.projectId),
    enabled: props.open,
  })
  const error = diagnosis.error ?? exported.error ?? contexts.error
  return (
    <Modal
      title="失败诊断与修复 Proposal"
      open={props.open}
      footer={null}
      width={920}
      destroyOnHidden
      onCancel={props.onClose}
    >
      {error && <Alert type="error" showIcon title={apiErrorMessage(error)} />}
      {diagnosis.data && <DiagnosisSummary value={diagnosis.data} />}
      {diagnosis.data && exported.data && contexts.data && (
        <RepairForm
          key={props.execution.id}
          projectId={props.projectId}
          executionId={props.execution.id}
          diagnosis={diagnosis.data}
          spec={exported.data.spec}
          revision={required(exported.data.draft_revision)}
          contexts={contexts.data.items}
          onCreated={props.onCreated}
        />
      )}
    </Modal>
  )
}

function DiagnosisSummary({ value }: { value: FailureDiagnosisResponse }) {
  const diagnosis = value.diagnosis
  return (
    <>
      {diagnosis.repair_policy.product_defect_guard && (
        <Alert
          type="error"
          showIcon
          title="Product Defect Guard 已阻止修改测试"
          description="请修复产品并补充回归，不会创建测试修复 Proposal。"
        />
      )}
      <Descriptions
        size="small"
        column={2}
        items={[
          {
            key: 'classification',
            label: '主分类',
            children: <Tag color="blue">{diagnosis.triage.primary_classification}</Tag>,
          },
          {
            key: 'confidence',
            label: '置信度',
            children: `${Math.round(diagnosis.triage.confidence * 100)}%`,
          },
          { key: 'action', label: '建议', children: diagnosis.triage.recommended_action },
          {
            key: 'evidence',
            label: '证据',
            children: `${diagnosis.triage.evidence_refs.length} 项`,
          },
        ]}
      />
    </>
  )
}

type RepairFormValue = {
  kind: RepairKind
  context_revision_id: string
  rationale: string
  acknowledge_oracle_weakening: boolean
  spec: string
}

function RepairForm({
  projectId,
  executionId,
  diagnosis,
  spec,
  revision,
  contexts,
  onCreated,
}: {
  projectId: string
  executionId: string
  diagnosis: FailureDiagnosisResponse
  spec: FlowSpecDocument
  revision: number
  contexts: ContextSummary[]
  onCreated: (proposalId: string) => void
}) {
  const { message } = App.useApp()
  const [form] = Form.useForm<RepairFormValue>()
  const eligibleContexts = contexts.filter(
    (item) =>
      item.status === 'ready' &&
      item.completeness.complete &&
      new Date(item.expires_at) > new Date(),
  )
  const mutation = useMutation({
    mutationFn: (value: RepairFormValue) =>
      createRepairProposal(projectId, executionId, {
        kind: value.kind,
        proposed_spec: JSON.parse(value.spec) as FlowSpecDocument,
        expected_target_revision: revision,
        context_revision_id: value.context_revision_id,
        rationale: value.rationale,
        acknowledge_oracle_weakening: value.acknowledge_oracle_weakening ?? false,
      }),
    onSuccess: (result) => {
      void message.success('修复 Proposal 已创建，请人工审核后 Re-preview')
      onCreated(result.proposal.id)
    },
    onError: (error) => void message.error(apiErrorMessage(error)),
  })
  const policy = diagnosis.diagnosis.repair_policy
  if (!policy.proposal_allowed) return null
  return (
    <Form<RepairFormValue>
      form={form}
      layout="vertical"
      initialValues={{
        kind: policy.allowed_kinds[0],
        context_revision_id: eligibleContexts[0]?.revision_id,
        rationale: diagnosis.diagnosis.triage.recommended_action,
        acknowledge_oracle_weakening: false,
        spec: JSON.stringify(spec, null, 2),
      }}
      onFinish={(value) => mutation.mutate(value)}
    >
      <Alert
        type="info"
        showIcon
        title="仅允许修改所选 Patch 类型对应的 FlowSpec 字段"
        description="提交后仍需人工 Accept；Oracle 变更必须显式确认，之后才能申请一次性 Sandbox Re-preview。"
      />
      <Space align="start" wrap>
        <Form.Item name="kind" label="Patch 类型" rules={[{ required: true }]}>
          <Select
            style={{ width: 220 }}
            options={policy.allowed_kinds.map((kind) => ({
              value: kind,
              label: repairLabel(kind),
            }))}
          />
        </Form.Item>
        <Form.Item
          name="context_revision_id"
          label="Context Revision"
          rules={[{ required: true, message: '请选择 Ready Context Revision' }]}
        >
          <Select
            style={{ width: 320 }}
            options={eligibleContexts.map((item) => ({
              value: item.revision_id,
              label: `${item.name} · r${item.current_revision}`,
            }))}
          />
        </Form.Item>
      </Space>
      <Form.Item name="rationale" label="修复理由" rules={[{ required: true }]}>
        <Input.TextArea rows={2} maxLength={2000} showCount />
      </Form.Item>
      <Form.Item
        name="spec"
        label="Proposed FlowSpec Patch"
        rules={[{ required: true }, { validator: validateJson }]}
      >
        <Input.TextArea className="code-preview" rows={16} spellCheck={false} />
      </Form.Item>
      <Form.Item name="acknowledge_oracle_weakening" valuePropName="checked">
        <Checkbox>我确认 Oracle 变更可能弱化断言，必须由人工复审</Checkbox>
      </Form.Item>
      <Button
        type="primary"
        htmlType="submit"
        loading={mutation.isPending}
        disabled={!eligibleContexts.length}
      >
        创建 Repair Proposal
      </Button>
    </Form>
  )
}

function repairLabel(kind: RepairKind): string {
  return {
    binding: 'Binding Mapping',
    data: 'Test Data',
    cleanup: 'Cleanup',
    contract_drift: 'Contract Drift',
    oracle: 'Oracle',
  }[kind]
}

async function validateJson(_rule: unknown, value: string | undefined) {
  if (!value) return
  try {
    JSON.parse(value)
  } catch {
    throw new Error('请输入合法 JSON')
  }
}

function required<T>(value: T | null | undefined): T {
  if (value === null || value === undefined) throw new Error('缺少修复所需资源')
  return value
}
