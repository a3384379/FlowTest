import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Form,
  Input,
  InputNumber,
  Select,
  Space,
  Tag,
  Typography,
} from 'antd'
import { useRef, useState } from 'react'
import { apiErrorMessage } from '../../lib/api'
import type { ChangeRegressionRun } from './change-regression-service'
import { listContexts } from '../context-inspector/context-inspector-service'
import { exportFlowSpec } from '../workflows/flow-spec-service'
import RegressionPlanWorkflowForm from './RegressionPlanWorkflowForm'
import {
  bindRegressionContext,
  createRegressionMaintenance,
  linkRegressionProposal,
  reviewRegressionMaintenance,
  type ContextBinding,
  type RegressionMaintenance,
  type RegressionMaintenancePatch,
} from './regression-maintenance-service'

export default function RegressionMaintenancePanel({ run }: { run: ChangeRegressionRun }) {
  const queryClient = useQueryClient()
  const snapshot = run.context_maintenance
  const editable = run.status === 'review_required'
  const [bindingOpen, setBindingOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const contexts = useQuery({
    queryKey: ['regression-contexts', run.project_id],
    queryFn: () => listContexts(run.project_id),
    enabled: bindingOpen,
  })

  async function perform(action: () => Promise<unknown>) {
    setBusy(true)
    setError(null)
    try {
      await action()
      await queryClient.invalidateQueries({ queryKey: ['change-regression', run.project_id] })
      setBindingOpen(false)
    } catch (caught) {
      setError(apiErrorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card size="small" title="Context 维护证据 · S59D">
      <Space direction="vertical" style={{ width: '100%' }}>
        <Alert
          type="info"
          message="维护提案复用人工审核、Sandbox Preview 和 Apply Draft；不自动发布，不替代 TestPlan 正式执行与 Release Gate。"
        />
        {error && <Alert type="error" message={error} />}
        {!snapshot && (
          <Typography.Text type="secondary">
            未绑定 Context；历史 v3 链路保持原有行为。
          </Typography.Text>
        )}
        {canBindContext(run) && (
          <Button onClick={() => setBindingOpen(true)}>绑定 / 刷新 Context 对比</Button>
        )}
        {bindingOpen && (
          <Form<ContextBinding>
            name="maintenance-context"
            layout="vertical"
            onFinish={(input) =>
              perform(() => bindRegressionContext(run.project_id, run.id, input))
            }
          >
            <Form.Item name="context_id" label="Context" rules={[{ required: true }]}>
              <Select
                loading={contexts.isLoading}
                options={(contexts.data?.items ?? []).map((item) => ({
                  value: item.id,
                  label: `${item.name} · r${item.current_revision}`,
                }))}
              />
            </Form.Item>
            <Form.Item name="before_revision" label="前版本" rules={[{ required: true }]}>
              <InputNumber min={1} precision={0} />
            </Form.Item>
            <Form.Item
              name="after_revision"
              label="后版本（当前 Ready 版本）"
              rules={[{ required: true }]}
            >
              <InputNumber min={2} precision={0} />
            </Form.Item>
            <Button htmlType="submit" loading={busy}>
              固定对比证据
            </Button>
          </Form>
        )}
        {snapshot && (
          <>
            <MaintenanceEvidence snapshot={snapshot} projectId={run.project_id} />
            {editable && (
              <>
                <MaintenancePatch run={run} snapshot={snapshot} busy={busy} perform={perform} />
                <RegressionPlanWorkflowForm
                  run={run}
                  snapshot={snapshot}
                  busy={busy}
                  perform={perform}
                />
                <Form<{ change_set_id: string }>
                  name="maintenance-link"
                  layout="inline"
                  onFinish={(input) =>
                    perform(() =>
                      linkRegressionProposal(run.project_id, run.id, input.change_set_id),
                    )
                  }
                >
                  <Form.Item
                    name="change_set_id"
                    label="已有维护提案 ID"
                    rules={[{ required: true }]}
                  >
                    <Input />
                  </Form.Item>
                  <Button htmlType="submit" loading={busy}>
                    关联已有提案
                  </Button>
                </Form>
                <Form<{ note: string; acknowledge_incomplete_analysis: boolean }>
                  name="maintenance-review"
                  layout="vertical"
                  initialValues={{ acknowledge_incomplete_analysis: false }}
                  onFinish={(input) =>
                    perform(() => reviewRegressionMaintenance(run.project_id, run.id, input))
                  }
                >
                  <Form.Item
                    name="note"
                    label="维护证据审核说明"
                    rules={[{ required: true, min: 10, max: 1000 }]}
                  >
                    <Input.TextArea rows={2} />
                  </Form.Item>
                  <Form.Item name="acknowledge_incomplete_analysis" valuePropName="checked">
                    <Checkbox>已检查未覆盖诊断并完成人工补充检查</Checkbox>
                  </Form.Item>
                  <Button htmlType="submit" loading={busy}>
                    确认维护证据审核
                  </Button>
                </Form>
              </>
            )}
          </>
        )}
      </Space>
    </Card>
  )
}

function canBindContext(run: ChangeRegressionRun): boolean {
  return run.status === 'review_required' && (run.context_maintenance?.proposals.length ?? 0) === 0
}

function MaintenanceEvidence({
  snapshot,
  projectId,
}: {
  snapshot: RegressionMaintenance
  projectId: string
}) {
  const difference = snapshot.comparison.difference
  return (
    <Space direction="vertical" style={{ width: '100%' }}>
      <Typography.Text>
        Context r{snapshot.comparison.before_revision} → r{snapshot.comparison.after_revision}
      </Typography.Text>
      <Typography.Text code>{snapshot.context_diff_ref}</Typography.Text>
      <Typography.Text>
        Evidence +{difference.evidence.added.length} / -{difference.evidence.removed.length}
        ；Knowledge 节点变化 {difference.knowledge.nodes.length}；关系 +
        {difference.knowledge.edges.added.length} / -{difference.knowledge.edges.removed.length}
      </Typography.Text>
      <Tag color={snapshot.affected.analysis_complete ? 'green' : 'orange'}>
        {snapshot.affected.analysis_complete ? '分析完整' : '分析不完整，需人工补充检查'}
      </Tag>
      <Typography.Text>
        已扫描 {snapshot.affected.scanned_workflow_ids.length} / {snapshot.affected.total_workflows}{' '}
        个流程
      </Typography.Text>
      {snapshot.affected.diagnostics.map((item, index) => (
        <Typography.Text key={index} type="warning">
          {item.code}
          {item.workflow_id ? ` · ${item.workflow_id}` : ''}
        </Typography.Text>
      ))}
      {snapshot.affected.affected_workflows.map((item) => (
        <div key={item.workflow_id}>
          <Typography.Text>
            受影响流程 {item.workflow_id} · 草稿 r{item.draft_revision}
          </Typography.Text>
          {item.reasons.map((reason, index) => (
            <div key={index}>
              <Tag>
                {reason.match_strength} / {reason.knowledge_relation ?? 'contract'}
              </Tag>
              <Typography.Text code>{reason.source_ref}</Typography.Text>
            </div>
          ))}
        </div>
      ))}
      {snapshot.proposals.map((item) => (
        <div key={item.change_set_id}>
          <Typography.Link
            href={`/projects/${projectId}/workflows?proposal=${encodeURIComponent(item.change_set_id)}`}
          >
            审核维护提案 {item.change_set_id}
          </Typography.Link>
          <Tag>
            {item.review_status} / {item.applied ? '已应用草稿' : '未应用'}
          </Tag>
        </div>
      ))}
      {snapshot.review && (
        <Alert
          type="success"
          message={`维护证据已审核：${snapshot.review.note}`}
          description="批准前会重新校验来源与固定版本；此确认不豁免现有语义门禁。"
        />
      )}
      {snapshot.required_workflows.map((item) => (
        <Typography.Text key={item.workflow_id}>
          正式回归要求：{item.workflow_id} v{item.workflow_version}
        </Typography.Text>
      ))}
    </Space>
  )
}

type PatchForm = {
  workflow_id: string
  kind: RegressionMaintenancePatch['kind']
  spec: string
  rationale: string
  acknowledge_oracle_weakening: boolean
}

function MaintenancePatch({
  run,
  snapshot,
  busy,
  perform,
}: {
  run: ChangeRegressionRun
  snapshot: RegressionMaintenance
  busy: boolean
  perform: (action: () => Promise<unknown>) => Promise<void>
}) {
  const [form] = Form.useForm<PatchForm>()
  const pendingRequest = useRef<{ body: string; key: string } | null>(null)
  const workflowId = Form.useWatch('workflow_id', form)
  const candidates = snapshot.affected.affected_workflows.filter((item) =>
    item.reasons.some(
      (reason) =>
        ['instance', 'portable'].includes(reason.match_strength) &&
        reason.knowledge_relation !== 'heuristic',
    ),
  )
  async function submit(input: PatchForm) {
    await perform(async () => {
      const target = candidates.find((item) => item.workflow_id === input.workflow_id)
      if (!target) throw new Error('请选择具有精确证据的流程')
      const body = JSON.stringify(input)
      if (pendingRequest.current?.body !== body) {
        pendingRequest.current = { body, key: crypto.randomUUID() }
      }
      return createRegressionMaintenance(
        run.project_id,
        run.id,
        target.workflow_id,
        {
          context_id: snapshot.comparison.context_id,
          before_revision: snapshot.comparison.before_revision,
          after_revision: snapshot.comparison.after_revision,
          impact_run_id: run.impact_run_id,
          expected_target_revision: target.draft_revision,
          kind: input.kind,
          proposed_spec: JSON.parse(input.spec),
          rationale: input.rationale,
          acknowledge_oracle_weakening: input.acknowledge_oracle_weakening,
        },
        pendingRequest.current.key,
      )
    })
  }
  return (
    <Card size="small" title="创建受限维护提案（人工 Patch）">
      <Form
        name="maintenance-patch"
        form={form}
        layout="vertical"
        initialValues={{ kind: 'data', acknowledge_oracle_weakening: false }}
        onFinish={submit}
      >
        <Form.Item name="workflow_id" label="精确受影响流程" rules={[{ required: true }]}>
          <Select
            options={candidates.map((item) => ({
              value: item.workflow_id,
              label: item.workflow_id,
            }))}
          />
        </Form.Item>
        <Button
          disabled={!workflowId}
          loading={busy}
          onClick={() =>
            perform(async () => {
              const exported = await exportFlowSpec(run.project_id, workflowId)
              form.setFieldValue('spec', JSON.stringify(exported.spec, null, 2))
            })
          }
        >
          读取当前 FlowSpec
        </Button>
        <Form.Item name="kind" label="Patch 类型">
          <Select
            options={['binding', 'data', 'cleanup', 'contract_drift', 'oracle'].map((value) => ({
              value,
              label: value,
            }))}
          />
        </Form.Item>
        <Form.Item name="spec" label="修改后的完整 FlowSpec JSON" rules={[{ required: true }]}>
          <Input.TextArea rows={5} />
        </Form.Item>
        <Form.Item name="rationale" label="维护理由" rules={[{ required: true, max: 2000 }]}>
          <Input />
        </Form.Item>
        <Form.Item name="acknowledge_oracle_weakening" valuePropName="checked">
          <Checkbox>显式确认 Oracle 弱化（仅适用 Oracle Patch）</Checkbox>
        </Form.Item>
        <Button htmlType="submit" loading={busy}>
          创建并原子关联维护提案
        </Button>
      </Form>
    </Card>
  )
}
