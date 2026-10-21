import { useQuery } from '@tanstack/react-query'
import {
  Alert,
  Button,
  Checkbox,
  Collapse,
  Descriptions,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Typography,
} from 'antd'
import { useRef, useState } from 'react'
import AIDraftProtection from './AIDraftProtection'
import { apiErrorWithTrace } from '../../lib/api'
import { getProjectRedactionPolicy } from '../projects/project-service'
import { type AIJobInput, type AIJobType, type AIPublicSource } from './ai-service'
import AISourcePicker from './AISourcePicker'

type JobForm = {
  job_type: AIJobType
  goal?: string
  schema?: string
  metadata?: string
  sample?: string
  includeSample?: boolean
  coverage_scope?: string
  response_path?: string
  expected_status?: number
  workflow_steps?: string
  completion_condition?: string
  expected_behavior?: string
  observed_behavior?: string
}
const goals: Record<AIJobType, { label: string; key: string; help: string }> = {
  schema_cases: {
    label: '用例覆盖目标',
    key: 'coverage_goal',
    help: '选择接口或协议契约，并描述边界、异常或正常路径。',
  },
  assertion_suggestions: {
    label: '断言目标',
    key: 'assertion_goal',
    help: '描述需要验证的字段、条件或状态，可附接口契约。',
  },
  workflow_draft: {
    label: '流程目标',
    key: 'workflow_goal',
    help: '描述步骤、依赖及结束条件；接受建议后生成未发布流程草稿。',
  },
  failure_analysis: {
    label: '失败现象',
    key: 'failure_summary',
    help: '选择冻结执行或填写已授权的失败现象。无需填写 Schema。',
  },
}
export default function CreateAIJobDialog(props: {
  projectId: string
  open: boolean
  submitting: boolean
  sampleEnabled: boolean
  onClose: () => void
  onCreate: (input: Omit<AIJobInput, 'project_id'>, onCreated?: () => void) => Promise<boolean>
}) {
  if (!props.open) return null
  return <CreateAIJobForm {...props} />
}
function CreateAIJobForm({
  projectId,
  submitting,
  sampleEnabled,
  onClose,
  onCreate,
}: {
  projectId: string
  submitting: boolean
  sampleEnabled: boolean
  onClose: () => void
  onCreate: (input: Omit<AIJobInput, 'project_id'>, onCreated?: () => void) => Promise<boolean>
}) {
  const [form] = Form.useForm<JobForm>()
  const allowLeaveRef = useRef(false)
  const type = Form.useWatch('job_type', form) ?? 'schema_cases'
  const includeSample = Form.useWatch('includeSample', form) ?? false
  const [source, setSource] = useState<AIPublicSource | null>(null)
  const [preview, setPreview] = useState<AIJobInput | null>(null)
  const [error, setError] = useState(''),
    [dirty, setDirty] = useState(false),
    [discard, setDiscard] = useState(false)
  const policy = useQuery({
    queryKey: ['project-redaction-policy', projectId],
    queryFn: () => getProjectRedactionPolicy(projectId),
  })
  function prepare(value: JobForm) {
    try {
      setPreview(buildInput(projectId, value, source, sampleEnabled))
      setError('')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '请检查提交材料')
    }
  }
  async function submit() {
    if (!preview || !policy.isSuccess || (preview.sample !== undefined && !sampleEnabled)) return
    const { project_id: project, ...input } = preview
    if (project !== projectId) return
    if (
      await onCreate(input, () => {
        allowLeaveRef.current = true
      })
    ) {
      setDirty(false)
      onClose()
    } else {
      allowLeaveRef.current = false
      setError('提交结果未确认，已保留材料。请先核对任务列表和错误信息，避免重复提交。')
    }
  }
  return (
    <>
      <AIDraftProtection
        dirty={dirty}
        allowLeaveRef={allowLeaveRef}
        title="提交材料尚未保存"
        description="离开将放弃本次尚未提交的材料。"
      />
      <Modal
        title="新建 AI 建议任务"
        open
        width={760}
        style={{ top: 24 }}
        styles={{ body: { maxHeight: 'calc(100dvh - 190px)', overflowY: 'auto' } }}
        closable={!submitting}
        maskClosable={!submitting}
        keyboard={!submitting}
        onCancel={() => {
          if (!submitting) {
            if (dirty) setDiscard(true)
            else onClose()
          }
        }}
        footer={
          <Space wrap>
            <Button disabled={submitting} onClick={() => (dirty ? setDiscard(true) : onClose())}>
              取消
            </Button>
            {preview ? (
              <Button disabled={submitting} onClick={() => setPreview(null)}>
                返回编辑
              </Button>
            ) : null}
            <Button
              type="primary"
              loading={submitting}
              disabled={submissionBlocked(policy.isSuccess, preview, sampleEnabled)}
              onClick={() => (preview ? void submit() : form.submit())}
            >
              {preview ? '确认提交任务' : '预览提交材料'}
            </Button>
          </Space>
        }
      >
        <AIInputPolicyNotice policy={policy} />
        {error ? <Alert type="error" title={error} /> : null}
        {preview ? (
          <section>
            <Typography.Paragraph>
              以下为发送到 FlowTest 的完整请求；确认后才进入 AI
              队列。服务端按届时有效策略处理，不额外读取材料。
            </Typography.Paragraph>
            <AIInputPreviewSummary payload={preview} source={source} />
            <pre
              aria-label="最终提交负载"
              style={{
                maxHeight: 460,
                overflow: 'auto',
                whiteSpace: 'pre-wrap',
                overflowWrap: 'anywhere',
              }}
            >
              {JSON.stringify(preview, null, 2)}
            </pre>
          </section>
        ) : (
          <Form
            form={form}
            layout="vertical"
            initialValues={{
              job_type: 'schema_cases',
              schema: '',
              metadata: '{}',
              sample: '',
              includeSample: false,
            }}
            onValuesChange={() => setDirty(true)}
            onFinish={prepare}
          >
            <Form.Item name="job_type" label="任务类型">
              <Select
                options={[
                  { value: 'schema_cases', label: 'Schema 用例建议' },
                  { value: 'assertion_suggestions', label: '断言建议' },
                  { value: 'workflow_draft', label: 'Workflow 草稿' },
                  { value: 'failure_analysis', label: '失败归因' },
                ]}
              />
            </Form.Item>
            <Typography.Paragraph type="secondary">{goals[type].help}</Typography.Paragraph>
            <Form.Item name="goal" label={goals[type].label}>
              <Input.TextArea rows={3} maxLength={10000} />
            </Form.Item>
            <AITaskFields type={type} />
            <Collapse
              items={[
                {
                  key: 'sources',
                  label: '从项目选择公开材料',
                  children: (
                    <AISourcePicker
                      projectId={projectId}
                      initialKind={type === 'failure_analysis' ? 'execution' : 'api'}
                      onUse={(value) => {
                        setSource(value)
                        setDirty(true)
                      }}
                    />
                  ),
                },
              ]}
            />
            <SelectedSource
              source={source}
              onClear={() => {
                setSource(null)
                setDirty(true)
              }}
            />
            <Collapse
              items={[
                {
                  key: 'json',
                  label: '高级 JSON 材料',
                  children: (
                    <>
                      <Form.Item name="schema" label="契约 Schema JSON（可选）">
                        <Input.TextArea rows={6} />
                      </Form.Item>
                      <Form.Item name="metadata" label="补充元数据 JSON">
                        <Input.TextArea rows={4} />
                      </Form.Item>
                    </>
                  ),
                },
              ]}
            />
            {sampleEnabled ? (
              <>
                <Form.Item name="includeSample" valuePropName="checked">
                  <Checkbox>本次提交样本（Owner 显式确认）</Checkbox>
                </Form.Item>
                {includeSample ? (
                  <Form.Item name="sample" label="本次提交样本 JSON">
                    <Input.TextArea rows={4} />
                  </Form.Item>
                ) : null}
              </>
            ) : (
              <Typography.Paragraph type="secondary">
                本次不提交样本；仅Owner在项目策略允许时可显式添加。
              </Typography.Paragraph>
            )}
          </Form>
        )}
      </Modal>
      <Modal
        open={discard}
        title="提交材料尚未保存"
        okText="放弃修改"
        cancelText="继续编辑"
        onOk={() => {
          allowLeaveRef.current = true
          setDiscard(false)
          onClose()
        }}
        onCancel={() => setDiscard(false)}
      >
        关闭将放弃本次尚未提交的材料。
      </Modal>
    </>
  )
}
function objectInput(text: string, label: string): Record<string, unknown> {
  try {
    const value: unknown = JSON.parse(text)
    if (value && typeof value === 'object' && !Array.isArray(value))
      return value as Record<string, unknown>
  } catch {
    throw new Error(`${label}必须是有效 JSON 对象`)
  }
  throw new Error(`${label}必须是 JSON 对象`)
}
function buildInput(
  projectId: string,
  value: JobForm,
  source: AIPublicSource | null,
  sampleEnabled: boolean,
): AIJobInput {
  const metadata = materialMetadata(value, source)
  const schema = materialSchema(value, source)
  if (value.job_type === 'schema_cases' && !schema)
    throw new Error('请选择含契约的公开来源或填写契约 Schema JSON')
  if (!schema && Object.keys(metadata).length === 0)
    throw new Error(`请选择公开来源或填写${goals[value.job_type].label}`)
  const payload: AIJobInput = { project_id: projectId, job_type: value.job_type, metadata }
  if (schema) payload.schema_document = schema
  const sample = materialSample(value, sampleEnabled)
  if (sample !== undefined) payload.sample = sample
  if (new TextEncoder().encode(JSON.stringify(payload)).length > 1048576)
    throw new Error('提交材料超过1 MiB限制')
  return payload
}
function materialMetadata(value: JobForm, source: AIPublicSource | null): Record<string, unknown> {
  const metadata = objectInput(value.metadata?.trim() || '{}', '元数据')
  if (source) metadata.source = source.metadata
  if (value.goal?.trim()) metadata[goals[value.job_type].key] = value.goal.trim()
  addTaskMetadata(metadata, value)
  return metadata
}
function materialSchema(
  value: JobForm,
  source: AIPublicSource | null,
): Record<string, unknown> | undefined {
  if (value.schema?.trim()) return objectInput(value.schema, 'Schema')
  return source?.schema_document ?? undefined
}
function materialSample(value: JobForm, enabled: boolean): unknown {
  if (!enabled || !value.includeSample) return undefined
  if (!value.sample?.trim()) throw new Error('请填写本次提交样本 JSON')
  try {
    return JSON.parse(value.sample)
  } catch {
    throw new Error('样本必须是有效 JSON')
  }
}
function submissionBlocked(
  policyReady: boolean,
  preview: AIJobInput | null,
  sampleEnabled: boolean,
): boolean {
  return !policyReady || (preview?.sample !== undefined && !sampleEnabled)
}
function SelectedSource({
  source,
  onClear,
}: {
  source: AIPublicSource | null
  onClear: () => void
}) {
  if (!source) return null
  return (
    <Alert
      type="success"
      title={`已选择：${source.metadata.name} · ${source.metadata.source_id}${source.metadata.version ? ` · v${source.metadata.version}` : ''}`}
      action={<Button onClick={onClear}>清除来源</Button>}
    />
  )
}
function AIInputPolicyNotice({
  policy,
}: {
  policy: ReturnType<typeof useQuery<import('../../lib/api').ProjectRedactionPolicy, Error>>
}) {
  return (
    <>
      {' '}
      <Alert
        type="info"
        showIcon
        title={
          policy.isSuccess
            ? `当前自动脱敏策略：${policy.data.mode.toUpperCase()}（${policy.data.source === 'project' ? '项目覆盖' : '安装默认'}，版本 ${policy.data.policy_version}）`
            : '正在读取当前处理策略'
        }
        description={
          policy.isSuccess
            ? policy.data.mode === 'on'
              ? '服务端按当前项目策略处理本次明确提交的材料。'
              : 'OFF 不扫描、遮盖或替换本次明确提交的材料。'
            : '策略读取成功前不能提交。'
        }
      />
      {policy.isError ? (
        <Alert
          type="error"
          title={apiErrorWithTrace(policy.error)}
          action={<Button onClick={() => void policy.refetch()}>重试策略</Button>}
        />
      ) : null}
    </>
  )
}

function AITaskFields({ type }: { type: AIJobType }) {
  if (type === 'schema_cases')
    return (
      <Form.Item name="coverage_scope" label="覆盖范围">
        <Select
          allowClear
          placeholder="选择需要覆盖的路径"
          options={[
            { value: 'normal', label: '正常路径' },
            { value: 'boundary', label: '边界条件' },
            { value: 'error', label: '异常路径' },
            { value: 'all', label: '综合覆盖' },
          ]}
        />
      </Form.Item>
    )
  if (type === 'assertion_suggestions')
    return (
      <>
        <Form.Item name="response_path" label="待验证字段路径">
          <Input placeholder="例如 response.body.order_id" />
        </Form.Item>
        <Form.Item name="expected_status" label="预期 HTTP 状态码（可选）">
          <InputNumber min={100} max={599} />
        </Form.Item>
      </>
    )
  if (type === 'workflow_draft')
    return (
      <>
        <Form.Item name="workflow_steps" label="期望步骤（每行一步）">
          <Input.TextArea rows={4} />
        </Form.Item>
        <Form.Item name="completion_condition" label="完成条件">
          <Input />
        </Form.Item>
      </>
    )
  return (
    <>
      <Form.Item name="expected_behavior" label="期望行为">
        <Input.TextArea rows={2} />
      </Form.Item>
      <Form.Item name="observed_behavior" label="实际行为">
        <Input.TextArea rows={2} />
      </Form.Item>
    </>
  )
}
function addTaskMetadata(metadata: Record<string, unknown>, value: JobForm): void {
  const fields: Record<AIJobType, readonly (keyof JobForm)[]> = {
    schema_cases: ['coverage_scope'],
    assertion_suggestions: ['response_path', 'expected_status'],
    workflow_draft: ['workflow_steps', 'completion_condition'],
    failure_analysis: ['expected_behavior', 'observed_behavior'],
  }
  for (const field of fields[value.job_type]) {
    const content = value[field]
    if (content === undefined || content === '') continue
    metadata[field] = normalizeTaskMaterial(field, content)
  }
}
function normalizeTaskMaterial(field: keyof JobForm, content: string | number | boolean): unknown {
  if (field === 'workflow_steps' && typeof content === 'string')
    return content
      .split('\n')
      .map((step) => step.trim())
      .filter(Boolean)
  return typeof content === 'string' ? content.trim() : content
}

function AIInputPreviewSummary({
  payload,
  source,
}: {
  payload: AIJobInput
  source: AIPublicSource | null
}) {
  const goal = payload.metadata[goals[payload.job_type].key]
  return (
    <Descriptions
      column={1}
      size="small"
      items={[
        { key: 'type', label: '任务', children: goals[payload.job_type].label },
        {
          key: 'goal',
          label: '目标或现象',
          children: typeof goal === 'string' ? goal : '未填写。请核对所选来源及补充材料。',
        },
        {
          key: 'source',
          label: '公开来源',
          children: source
            ? `${source.metadata.name} · ${source.metadata.source_id}`
            : '手动填写材料',
        },
        {
          key: 'version',
          label: '固定版本',
          children: materialVersionLabel(source),
        },
        {
          key: 'schema',
          label: '契约材料',
          children: payload.schema_document ? '已提供' : '未提交',
        },
        {
          key: 'sample',
          label: '样本',
          children: payload.sample !== undefined ? 'Owner 已明确选择本次提交' : '不提交',
        },
        {
          key: 'size',
          label: '请求大小',
          children: `${new TextEncoder().encode(JSON.stringify(payload)).length} 字节`,
        },
      ]}
    />
  )
}

function materialVersionLabel(source: AIPublicSource | null): string | number {
  if (!source) return '手动材料，无来源版本'
  return source.metadata.version ?? '使用来源固定 ID；其他版本信息见完整负载。'
}
