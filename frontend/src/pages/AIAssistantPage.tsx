import { CheckOutlined, CloseOutlined, PlusOutlined, RobotOutlined } from '@ant-design/icons'
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  Form,
  Input,
  Modal,
  Row,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
} from 'antd'
import { useState } from 'react'

import type { AIJobInput, AISuggestion } from '../features/ai/ai-service'
import { useAIReview } from '../features/ai/use-ai-review'

type JobForm = {
  job_type: AIJobInput['job_type']
  schema: string
  metadata: string
  sample: string
}

type ReviewDraft = {
  suggestion: AISuggestion
  decision: 'accept' | 'reject'
}

export default function AIAssistantPage() {
  const state = useAIReview()
  const [createOpen, setCreateOpen] = useState(false)
  const review = useSuggestionReview(state)
  const aiStatus = state.status.data
  return (
    <>
      <AIPageHeader
        canCreate={Boolean(state.projectId && aiStatus?.enabled)}
        onCreate={() => setCreateOpen(true)}
      />
      <AIDisabledAlert loading={state.status.isLoading} enabled={aiStatus?.enabled ?? false} />
      <AIPolicyCard state={state} />
      <AIWorkspace state={state} onReview={review.open} />
      <CreateAIJobDialog
        open={createOpen}
        submitting={state.creating}
        sampleEnabled={aiStatus?.sample_sharing_enabled ?? false}
        onClose={() => setCreateOpen(false)}
        onCreate={async (input) => {
          await state.createJob(input)
          setCreateOpen(false)
        }}
      />
      <ReviewDialog state={state} review={review} />
    </>
  )
}

type AIReviewState = ReturnType<typeof useAIReview>

function AIPageHeader({ canCreate, onCreate }: { canCreate: boolean; onCreate: () => void }) {
  return (
    <div className="page-heading">
      <div>
        <Typography.Title level={2}>AI 助手</Typography.Title>
        <Typography.Text type="secondary">
          基于 Schema 和脱敏元数据生成可审核建议。AI 不会读取 Secret、自动发布或自动执行。
        </Typography.Text>
      </div>
      <Button type="primary" icon={<PlusOutlined />} disabled={!canCreate} onClick={onCreate}>
        新建 AI 任务
      </Button>
    </div>
  )
}

function AIDisabledAlert({ loading, enabled }: { loading: boolean; enabled: boolean }) {
  if (loading || enabled) return null
  return (
    <Alert
      showIcon
      type="info"
      message="AI 助手当前关闭"
      description="未配置 OpenAI-compatible 网关时不会影响接口、Workflow 或计划运行。"
      className="page-alert"
    />
  )
}

function AIPolicyCard({ state }: { state: AIReviewState }) {
  const aiStatus = state.status.data
  const enabled = aiStatus?.enabled ?? false
  return (
    <Card className="ai-policy-card">
      <Space size="large">
        <Tag icon={<RobotOutlined />} color={enabled ? 'processing' : 'default'}>
          {enabled ? `模型：${aiStatus?.model}` : '未启用'}
        </Tag>
        <Typography.Text>允许 Owner 提交脱敏样本</Typography.Text>
        <Switch
          aria-label="允许提交脱敏样本"
          checked={aiStatus?.sample_sharing_enabled ?? false}
          loading={state.updatingSettings}
          disabled={!enabled}
          onChange={(checked) => state.updateSampleSharing(checked)}
        />
      </Space>
    </Card>
  )
}

function AIWorkspace({
  state,
  onReview,
}: {
  state: AIReviewState
  onReview: (suggestion: AISuggestion, decision: 'accept' | 'reject') => void
}) {
  return (
    <Row gutter={16}>
      <Col span={10}>
        <AIJobsCard state={state} />
      </Col>
      <Col span={14}>
        <AISuggestionsCard state={state} onReview={onReview} />
      </Col>
    </Row>
  )
}

function AIJobsCard({ state }: { state: AIReviewState }) {
  return (
    <Card title="AI 任务" loading={state.jobs.isLoading}>
      <Table
        rowKey="id"
        size="small"
        pagination={false}
        dataSource={state.jobs.data?.items ?? []}
        rowClassName={(job) => (job.id === state.selectedJobId ? 'selected-row' : '')}
        onRow={(job) => ({ onClick: () => state.selectJob(job.id) })}
        columns={[
          { title: '类型', dataIndex: 'job_type', render: jobTypeLabel },
          {
            title: '状态',
            dataIndex: 'status',
            render: (value: string) => <Tag color={statusColor(value)}>{value}</Tag>,
          },
          { title: '模型', dataIndex: 'model_name', ellipsis: true },
          {
            title: '输入摘要',
            dataIndex: 'input_sha256',
            render: (value: string) => value.slice(0, 10),
          },
        ]}
      />
    </Card>
  )
}

function AISuggestionsCard({
  state,
  onReview,
}: {
  state: AIReviewState
  onReview: (suggestion: AISuggestion, decision: 'accept' | 'reject') => void
}) {
  return (
    <Card title="人工审核" loading={state.suggestions.isLoading}>
      <Table
        rowKey="id"
        size="small"
        pagination={false}
        dataSource={state.suggestions.data ?? []}
        locale={{ emptyText: '任务完成后在此审核建议' }}
        columns={[
          { title: '建议', dataIndex: 'title', ellipsis: true },
          { title: '类型', dataIndex: 'suggestion_type', width: 120 },
          {
            title: '状态',
            dataIndex: 'review_status',
            width: 100,
            render: (value: string) => <Tag>{value}</Tag>,
          },
          {
            title: '操作',
            width: 150,
            render: (_, suggestion: AISuggestion) => (
              <ReviewActions suggestion={suggestion} onReview={onReview} />
            ),
          },
        ]}
      />
    </Card>
  )
}

function ReviewActions({
  suggestion,
  onReview,
}: {
  suggestion: AISuggestion
  onReview: (suggestion: AISuggestion, decision: 'accept' | 'reject') => void
}) {
  const disabled = suggestion.review_status !== 'pending'
  return (
    <Space>
      <Button
        size="small"
        type="link"
        icon={<CheckOutlined />}
        disabled={disabled}
        onClick={() => onReview(suggestion, 'accept')}
      >
        接受
      </Button>
      <Button
        size="small"
        type="link"
        danger
        icon={<CloseOutlined />}
        disabled={disabled}
        onClick={() => onReview(suggestion, 'reject')}
      >
        拒绝
      </Button>
    </Space>
  )
}

function ReviewDialog({
  state,
  review,
}: {
  state: AIReviewState
  review: ReturnType<typeof useSuggestionReview>
}) {
  return (
    <Modal
      title={review.draft?.decision === 'accept' ? '接受并生成草稿' : '拒绝建议'}
      open={Boolean(review.draft)}
      confirmLoading={state.reviewing}
      onCancel={review.close}
      onOk={() => void review.submit()}
    >
      {review.draft?.decision === 'accept' ? (
        <Input.TextArea
          aria-label="建议内容"
          rows={12}
          value={review.editedContent}
          onChange={(event) => review.setEditedContent(event.target.value)}
        />
      ) : null}
      <Input.TextArea
        aria-label="审核备注"
        rows={3}
        maxLength={2000}
        placeholder="审核备注"
        value={review.note}
        onChange={(event) => review.setNote(event.target.value)}
      />
    </Modal>
  )
}

function useSuggestionReview(state: AIReviewState) {
  const { message } = App.useApp()
  const [draft, setDraft] = useState<ReviewDraft | null>(null)
  const [editedContent, setEditedContent] = useState('')
  const [note, setNote] = useState('')

  function open(suggestion: AISuggestion, decision: 'accept' | 'reject') {
    setDraft({ suggestion, decision })
    setEditedContent(JSON.stringify(suggestion.content, null, 2))
    setNote('')
  }

  function close() {
    setDraft(null)
  }

  async function submit() {
    if (!draft) return
    const content = acceptedContent(draft, editedContent, message.error)
    if (draft.decision === 'accept' && !content) return
    await state.review({
      id: draft.suggestion.id,
      decision: draft.decision,
      content,
      note,
    })
    close()
  }

  return { draft, editedContent, note, setEditedContent, setNote, open, close, submit }
}

function acceptedContent(
  draft: ReviewDraft,
  editedContent: string,
  showError: (message: string) => void,
) {
  if (draft.decision !== 'accept') return undefined
  try {
    return parseObject(editedContent, '建议内容必须是 JSON 对象')
  } catch {
    showError('建议内容必须是 JSON 对象')
    return undefined
  }
}

function CreateAIJobDialog({
  open,
  submitting,
  sampleEnabled,
  onClose,
  onCreate,
}: {
  open: boolean
  submitting: boolean
  sampleEnabled: boolean
  onClose: () => void
  onCreate: (input: Omit<AIJobInput, 'project_id'>) => Promise<void>
}) {
  const [form] = Form.useForm<JobForm>()
  return (
    <Modal
      title="新建 AI 建议任务"
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
          job_type: 'schema_cases',
          schema: '{\n  "openapi": "3.1.0",\n  "paths": {}\n}',
          metadata: '{}',
          sample: '',
        }}
        onFinish={(value) =>
          void onCreate({
            job_type: value.job_type,
            schema_document: parseObject(value.schema, 'Schema 必须是 JSON 对象'),
            metadata: parseObject(value.metadata, '元数据必须是 JSON 对象'),
            sample: sampleEnabled && value.sample.trim() ? JSON.parse(value.sample) : undefined,
          })
        }
      >
        <Form.Item name="job_type" label="任务类型" rules={[{ required: true }]}>
          <Select
            options={[
              { value: 'schema_cases', label: 'Schema 用例建议' },
              { value: 'assertion_suggestions', label: '断言建议' },
              { value: 'workflow_draft', label: 'Workflow 草稿' },
              { value: 'failure_analysis', label: '失败归因' },
            ]}
          />
        </Form.Item>
        <Form.Item
          name="schema"
          label="OpenAPI Schema"
          rules={[{ required: true }, { validator: validateJSONObject }]}
        >
          <Input.TextArea rows={8} />
        </Form.Item>
        <Form.Item
          name="metadata"
          label="脱敏元数据"
          rules={[{ required: true }, { validator: validateJSONObject }]}
        >
          <Input.TextArea rows={4} />
        </Form.Item>
        {sampleEnabled ? (
          <Form.Item
            name="sample"
            label="脱敏样本（Owner 显式开启）"
            rules={[{ validator: validateOptionalJSON }]}
          >
            <Input.TextArea rows={4} />
          </Form.Item>
        ) : null}
      </Form>
    </Modal>
  )
}

function parseObject(value: string, message: string): Record<string, unknown> {
  const parsed: unknown = JSON.parse(value)
  if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') throw new Error(message)
  return parsed as Record<string, unknown>
}

async function validateJSONObject(_: unknown, value: string) {
  try {
    parseObject(value, '请输入 JSON 对象')
  } catch {
    throw new Error('请输入有效的 JSON 对象')
  }
}

async function validateOptionalJSON(_: unknown, value: string) {
  if (!value?.trim()) return
  try {
    JSON.parse(value)
  } catch {
    throw new Error('请输入有效 JSON')
  }
}

function jobTypeLabel(value: AIJobInput['job_type']) {
  return {
    schema_cases: 'Schema 用例',
    assertion_suggestions: '断言建议',
    workflow_draft: 'Workflow',
    failure_analysis: '失败归因',
  }[value]
}

function statusColor(value: string) {
  if (value === 'completed') return 'success'
  if (value === 'failed') return 'error'
  return 'processing'
}
