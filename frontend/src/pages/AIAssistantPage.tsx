import CatalogPagination from '../components/CatalogPagination'
import { CheckOutlined, CloseOutlined, PlusOutlined, RobotOutlined } from '@ant-design/icons'
import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Row,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
} from 'antd'
import { Link } from 'react-router-dom'
import { projectPath } from '../features/projects/project-routing'
import { useState } from 'react'
import type { AIJob, AIJobInput, AISuggestion } from '../features/ai/ai-service'
import { useAIReview } from '../features/ai/use-ai-review'
import CreateAIJobDialog from '../features/ai/CreateAIJobDialog'
import AISuggestionReviewDialog from '../features/ai/AISuggestionReviewDialog'
import { useProjectContext } from '../features/projects/use-project-context'
import { apiErrorWithTrace } from '../lib/api'

export default function AIAssistantPage() {
  const { projectId } = useProjectContext()
  return <AIReviewWorkspace key={projectId ?? 'none'} />
}
type AIReviewState = ReturnType<typeof useAIReview>
function AIReviewWorkspace() {
  const state = useAIReview()
  const [createOpen, setCreateOpen] = useState(false)
  const suggestion = state.suggestions.isSuccess
    ? state.suggestions.data.find((item) => item.id === state.suggestionId)
    : undefined
  return (
    <>
      <AIPageHeader
        canCreate={Boolean(state.canEdit && state.status.isSuccess && state.status.data.enabled)}
        onCreate={() => setCreateOpen(true)}
      />
      <AIErrorAlert state={state} />
      {state.status.isSuccess && !state.status.data.enabled ? (
        <Alert
          showIcon
          type="info"
          title="AI 助手当前关闭"
          description="未配置 OpenAI-compatible 网关时不会影响接口、Workflow 或计划运行。历史任务和审核结果仍可只读查看。"
          className="page-alert"
        />
      ) : null}
      <AIPolicyCard state={state} />
      <div className="catalog-controls">
        <CatalogPagination query={state.jobs} label="AI 任务" />
      </div>
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={10} style={{ minWidth: 0 }}>
          <AIJobsCard state={state} />
        </Col>
        <Col xs={24} lg={14} style={{ minWidth: 0 }}>
          <AIJobDetails job={state.selectedJob.isSuccess ? state.selectedJob.data : undefined} />
          <AISuggestionsCard state={state} />
        </Col>
      </Row>
      <AICreateDialog state={state} open={createOpen} onClose={() => setCreateOpen(false)} />
      {missingSuggestion(state, Boolean(suggestion)) ? (
        <Alert
          type="warning"
          title="所选建议不存在或不属于当前任务"
          action={<Button onClick={() => state.selectSuggestion(null)}>返回当前任务</Button>}
        />
      ) : null}
      {suggestion && state.projectId ? (
        <AISuggestionReviewDialog
          key={`${state.projectId}:${suggestion.job_id}:${suggestion.id}:${suggestion.review_status}`}
          projectId={state.projectId}
          suggestion={suggestion}
          decision={state.reviewDecision}
          canEdit={state.canReview}
          submitting={state.reviewing}
          onClose={() => state.selectSuggestion(null)}
          onSubmit={state.review}
          onReload={async () => {
            const result = await state.suggestions.refetch()
            if (result.isError) throw result.error
          }}
        />
      ) : null}
    </>
  )
}
function AIPageHeader({ canCreate, onCreate }: { canCreate: boolean; onCreate: () => void }) {
  return (
    <div className="page-heading">
      <div>
        <Typography.Title level={2}>AI 助手</Typography.Title>
        <Typography.Text type="secondary">
          选择公开契约或失败摘要生成建议，人工审核后继续处理。任务不会自动发布或执行。
        </Typography.Text>
      </div>
      <Button type="primary" icon={<PlusOutlined />} disabled={!canCreate} onClick={onCreate}>
        新建 AI 任务
      </Button>
    </div>
  )
}
function AIErrorAlert({ state }: { state: AIReviewState }) {
  const queries = [
    state.status,
    state.jobs,
    state.selectedJob,
    state.suggestions,
    state.permissions,
  ]
  const error = queries.find((query) => query.isError)?.error
  if (!error) return null
  return (
    <Alert
      type="error"
      showIcon
      title="AI 工作区加载失败"
      description={apiErrorWithTrace(error)}
      action={
        <Button
          onClick={() =>
            queries.filter((query) => query.isError).forEach((query) => void query.refetch())
          }
        >
          重试
        </Button>
      }
    />
  )
}
function AIPolicyCard({ state }: { state: AIReviewState }) {
  const status = state.status.data,
    enabled = state.status.isSuccess && state.status.data.enabled
  return (
    <Card className="ai-policy-card">
      <Space wrap size="large">
        <Tag icon={<RobotOutlined />} color={enabled ? 'processing' : 'default'}>
          {enabled ? `模型：${state.status.data?.model}` : '未启用'}
        </Tag>
        <Typography.Text>允许 Owner 显式提交样本</Typography.Text>
        <Switch
          aria-label="允许 Owner 提交样本"
          checked={status?.sample_sharing_enabled ?? false}
          loading={state.updatingSettings}
          disabled={!enabled || !state.canManageSecurity}
          onChange={(checked) => void state.updateSampleSharing(checked)}
        />
      </Space>
    </Card>
  )
}
function AIJobsCard({ state }: { state: AIReviewState }) {
  return (
    <Card title="AI 任务" loading={state.jobs.isLoading}>
      <Table<AIJob>
        rowKey="id"
        size="small"
        pagination={false}
        scroll={{ x: 460 }}
        dataSource={state.jobs.isSuccess ? state.jobs.data.items : []}
        rowClassName={(job) => (job.id === state.selectedJobId ? 'selected-row' : '')}
        columns={[
          {
            title: '任务',
            dataIndex: 'job_type',
            render: (value: string, job) => (
              <Button type="link" onClick={() => state.selectJob(job.id)}>
                {jobTypeLabel(value)}
              </Button>
            ),
          },
          {
            title: '状态',
            dataIndex: 'status',
            render: (value: string) => <Tag color={statusColor(value)}>{value}</Tag>,
          },
          { title: '模型', dataIndex: 'model_name', ellipsis: true },
          {
            title: '输入摘要',
            dataIndex: 'input_sha256',
            render: (value: string) => value?.slice(0, 10) ?? '未提供',
          },
        ]}
      />
    </Card>
  )
}
function AIJobDetails({ job }: { job?: AIJob }) {
  if (!job) return null
  return (
    <Card size="small" title="任务详情" style={{ marginBottom: 16 }}>
      <AIChangeSetJobNotice job={job} />
      {job.status === 'failed' ? (
        <Alert
          type="error"
          showIcon
          title={job.error_code ?? '任务失败，未提供错误代码'}
          description={job.error_message ?? '未提供失败原因，可核对队列与网关可用性后新建任务。'}
        />
      ) : null}
      <Descriptions
        size="small"
        column={1}
        items={[
          { key: 'id', label: '任务ID', children: job.id },
          { key: 'status', label: '当前状态', children: `当前状态：${job.status}` },
          { key: 'created', label: '创建时间', children: job.created_at },
          { key: 'completed', label: '完成时间', children: job.completed_at ?? '尚未提供完成时间' },
          { key: 'trace', label: 'Trace 引用', children: '未提供 Trace ID' },
          {
            key: 'policy',
            label: '任务处理策略',
            children: job.redaction_mode
              ? `${job.redaction_mode.toUpperCase()}，版本 ${job.redaction_policy_version ?? '未提供'}`
              : '历史任务未提供策略信息',
          },
        ]}
      />
      <Typography.Paragraph type="secondary">{nextStep(job.status)}</Typography.Paragraph>
    </Card>
  )
}
function AISuggestionsCard({ state }: { state: AIReviewState }) {
  return (
    <Card title="人工审核" loading={state.suggestions.isFetching}>
      <Table<AISuggestion>
        rowKey="id"
        size="small"
        pagination={false}
        scroll={{ x: 530 }}
        dataSource={
          state.suggestions.isSuccess &&
          state.selectedJob.isSuccess &&
          state.selectedJob.data.status === 'completed'
            ? state.suggestions.data
            : []
        }
        locale={{ emptyText: nextStep(state.selectedJob.data?.status) }}
        columns={[
          { title: '建议', dataIndex: 'title', ellipsis: true },
          { title: '类型', dataIndex: 'suggestion_type' },
          {
            title: '状态',
            dataIndex: 'review_status',
            render: (value: string) => <Tag>{value}</Tag>,
          },
          {
            title: '操作',
            width: 240,
            render: (_, suggestion) => (
              <Space>
                <Button
                  size="small"
                  type="link"
                  onClick={() => state.selectSuggestion(suggestion.id)}
                >
                  查看
                </Button>
                <Button
                  size="small"
                  type="link"
                  icon={<CheckOutlined />}
                  disabled={!state.canReview || suggestion.review_status !== 'pending'}
                  onClick={() => state.selectSuggestion(suggestion.id, 'accept')}
                >
                  接受
                </Button>
                <Button
                  size="small"
                  type="link"
                  danger
                  icon={<CloseOutlined />}
                  disabled={!state.canReview || suggestion.review_status !== 'pending'}
                  onClick={() => state.selectSuggestion(suggestion.id, 'reject')}
                >
                  拒绝
                </Button>
              </Space>
            ),
          },
        ]}
      />
    </Card>
  )
}
function jobTypeLabel(value: AIJobInput['job_type'] | string): string {
  const names: Record<string, string> = {
    schema_cases: 'Schema 用例',
    assertion_suggestions: '断言建议',
    workflow_draft: 'Workflow',
    failure_analysis: '失败归因',
    change_set: 'AI 变更集',
  }
  return names[value] ?? value
}
function statusColor(value: string): string {
  if (value === 'completed') return 'success'
  if (value === 'failed') return 'error'
  return 'processing'
}
function nextStep(status?: string): string {
  if (status === 'failed') return '任务失败。检查错误后可重新填写新任务，当前不会自动重试。'
  if (status === 'pending' || status === 'running') return '任务仍在处理中，完成后可人工审核建议。'
  if (status === 'completed') return '任务已完成；如没有建议，可补充明确的公开材料后新建任务。'
  return '请选择任务，完成后在此审核建议。'
}

function AICreateDialog({
  state,
  open,
  onClose,
}: {
  state: AIReviewState
  open: boolean
  onClose: () => void
}) {
  if (!state.projectId) return null
  return (
    <CreateAIJobDialog
      projectId={state.projectId}
      open={open}
      submitting={state.creating}
      sampleEnabled={Boolean(
        state.status.isSuccess &&
        state.status.data.sample_sharing_enabled &&
        state.canManageSecurity,
      )}
      onClose={onClose}
      onCreate={state.createJob}
    />
  )
}

function missingSuggestion(state: AIReviewState, present: boolean): boolean {
  return Boolean(state.suggestionId && state.suggestions.isSuccess && !present)
}

function AIChangeSetJobNotice({ job }: { job: AIJob }) {
  if (job.job_type !== 'change_set') return null
  return (
    <Alert
      type="info"
      title="此任务属于 AI 变更集，普通 AI 助手只读展示"
      description={
        <Link to={projectPath(job.project_id, 'ai-changes')}>前往本项目 AI 变更集核对和审核</Link>
      }
    />
  )
}
