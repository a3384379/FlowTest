import CatalogPagination from '../components/CatalogPagination'
import { AuditOutlined, PlusOutlined, RobotOutlined } from '@ant-design/icons'
import {
  Alert,
  Button,
  Card,
  Col,
  Flex,
  Form,
  Input,
  Modal,
  Row,
  Select,
  Space,
  Tag,
  Typography,
} from 'antd'
import { useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import type {
  AIChangeItem,
  AIChangeSetDetail,
  AIChangeSetInput,
} from '../features/ai/ai-change-set-service'
import { useAIChangeSets } from '../features/ai/use-ai-change-sets'
import { useProjectContext } from '../features/projects/use-project-context'
import { apiErrorWithTrace } from '../lib/api'
import { useRouteScopedState } from '../lib/use-route-scoped-state'
import AIDraftProtection from '../features/ai/AIDraftProtection'
import {
  AIChangeSource,
  AIChangeBaseline,
  AIChangeReviewReceipt,
} from '../features/ai/AIChangeReviewEvidence'

type ReviewSelection = {
  changeSetId: string
  item: AIChangeItem
  decision: 'accept' | 'reject'
}

export default function AIChangeSetsPage() {
  const { projectId } = useProjectContext()
  return <AIChangeSetWorkspace key={projectId ?? 'none'} />
}

function AIChangeSetWorkspace() {
  const [searchParams] = useSearchParams()
  const state = useAIChangeSets(searchParams.get('focus'))
  const [createOpen, setCreateOpen] = useState(false)
  const [review, setReview] = useRouteScopedState<ReviewSelection | null>(
    state.projectId,
    state.activeId,
    null,
  )
  const detail = state.detail.data
  return (
    <>
      <div className="page-heading">
        <div>
          <Typography.Title level={2}>AI 测试资产变更审核</Typography.Title>
          <Typography.Text type="secondary">
            将影响与风险证据转成结构化 Draft Change Set，由人工逐项接受、编辑或拒绝。
          </Typography.Text>
        </div>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          aria-label="生成 Draft Change Set"
          disabled={!state.canCreate}
          onClick={() => setCreateOpen(true)}
        >
          生成 Draft Change Set
        </Button>
      </div>
      <div className="catalog-controls">
        <CatalogPagination query={state.changeSets} label="变更集" />
        <CatalogPagination query={state.impacts} label="影响证据" />
        <CatalogPagination query={state.risks} label="风险证据" />
      </div>
      <AIChangeSetStatus state={state} />
      <Alert
        showIcon
        type="info"
        icon={<RobotOutlined />}
        title="AI 只生成草稿：不读取 Secret、不自动发布、不自动执行，也不能修改权限或 Credential。"
        style={{ marginBottom: 16 }}
      />
      <Row gutter={16}>
        <Col xs={24} xl={7}>
          <Card title="AI 建议摘要" loading={state.changeSets.isLoading}>
            {(state.changeSets.data?.items.length ?? 0) === 0 ? (
              <Typography.Text type="secondary">暂无 AI Change Set</Typography.Text>
            ) : (
              <Flex vertical gap={8}>
                {state.changeSets.data?.items.map((item) => (
                  <Button
                    key={item.id}
                    type={item.id === state.activeId ? 'primary' : 'text'}
                    ghost={item.id === state.activeId}
                    block
                    onClick={() => state.select(item.id)}
                    style={{ height: 'auto', padding: 12, textAlign: 'left' }}
                  >
                    <Flex vertical gap={4} align="flex-start">
                      <Typography.Text strong>{item.title}</Typography.Text>
                      <Space size={4}>
                        <Tag color={statusColor(item.status)}>{statusLabel(item.status)}</Tag>
                        <Typography.Text type="secondary" code>
                          {item.source_fingerprint.slice(0, 12)}
                        </Typography.Text>
                      </Space>
                    </Flex>
                  </Button>
                ))}
              </Flex>
            )}
          </Card>
        </Col>
        <Col xs={24} xl={17}>
          <Card
            title="变更集审核"
            extra={<Tag icon={<AuditOutlined />}>接受后只更新草稿</Tag>}
            loading={state.detail.isLoading}
          >
            <ChangeSetDetail
              detail={detail}
              readOnly={!state.canReview || state.reviewing}
              onReview={(value) => {
                state.clearReviewError()
                if (detail) setReview({ ...value, changeSetId: detail.id })
              }}
            />
          </Card>
        </Col>
      </Row>
      <CreateChangeSetDialog
        readOnly={!state.canCreate}
        open={createOpen}
        submitting={state.creating}
        risks={state.risks.data?.items ?? []}
        riskQuery={state.risks}
        impacts={state.impacts.data?.items ?? []}
        onClose={() => setCreateOpen(false)}
        onCreate={async (input) => {
          if (await state.addChangeSet(input)) setCreateOpen(false)
        }}
      />
      <ReviewChangeItemDialog
        readOnly={!state.canReview}
        detail={detail}
        apiError={state.reviewError}
        value={review}
        submitting={state.reviewing}
        onClose={() => setReview(null)}
        onSubmit={async (item, decision, content, note) => {
          if (await state.reviewItem(item.id, decision, content, note)) setReview(null)
        }}
      />
    </>
  )
}

function AIChangeSetStatus({ state }: { state: ReturnType<typeof useAIChangeSets> }) {
  const queries = [state.status, state.flags, state.permissions, state.detail]
  const failed = queries.filter((query) => query.isError)
  if (failed.length)
    return (
      <Alert
        className="page-alert"
        showIcon
        type="error"
        title={apiErrorWithTrace(failed[0].error)}
        action={
          <Button onClick={() => void Promise.all(failed.map((query) => query.refetch()))}>
            重试
          </Button>
        }
      />
    )
  if (state.status.data?.enabled === false)
    return (
      <Alert
        className="page-alert"
        showIcon
        type="info"
        title="AI 生成功能尚未启用，可查看已有审核记录。"
      />
    )
  if (state.flags.data?.quality_intelligence === false)
    return (
      <Alert className="page-alert" showIcon type="info" title="质量智能尚未启用，历史记录只读。" />
    )
  if (state.flags.data?.impact_engine === false)
    return (
      <Alert
        className="page-alert"
        showIcon
        type="info"
        title="影响分析尚未启用，无法选择新的生成来源。"
      />
    )
  return null
}

function ChangeSetDetail({
  detail,
  readOnly,
  onReview,
}: {
  detail: AIChangeSetDetail | undefined
  readOnly: boolean
  onReview: (value: { item: AIChangeItem; decision: 'accept' | 'reject' }) => void
}) {
  if (!detail) {
    return <Typography.Text type="secondary">请选择或生成一个 Draft Change Set。</Typography.Text>
  }
  return (
    <Flex vertical gap={16}>
      <AIChangeSource detail={detail} projectId={detail.project_id} />
      <ChangeSetContent detail={detail} readOnly={readOnly} onReview={onReview} />
    </Flex>
  )
}
function ChangeSetContent({
  detail,
  readOnly,
  onReview,
}: {
  detail: AIChangeSetDetail
  readOnly: boolean
  onReview: (value: { item: AIChangeItem; decision: 'accept' | 'reject' }) => void
}) {
  if (detail.status === 'generating')
    return <Alert showIcon type="info" title="AI 正在生成结构化变更项，请稍候…" />
  if (detail.status === 'failed')
    return <Alert showIcon type="error" title="AI Change Set 生成失败，请查看 AI 任务审计。" />
  return <ChangeItems detail={detail} readOnly={readOnly} onReview={onReview} />
}

function CreateChangeSetDialog({
  readOnly,
  open,
  submitting,
  risks,
  riskQuery,
  impacts,
  onClose,
  onCreate,
}: {
  readOnly: boolean
  open: boolean
  submitting: boolean
  risks: Array<{ id: string; impact_run_id: string; title: string; score: number }>
  riskQuery: ReturnType<typeof useAIChangeSets>['risks']
  impacts: Array<{ id: string; title: string }>
  onClose: () => void
  onCreate: (input: Omit<AIChangeSetInput, 'project_id'>) => Promise<void>
}) {
  const [form] = Form.useForm<Omit<AIChangeSetInput, 'project_id'>>()
  const riskId = Form.useWatch('release_risk_id', form)
  const [selectedRisk, setSelectedRisk] = useState<(typeof risks)[number] | null>(null)
  const risk =
    risks.find((item) => item.id === riskId) ?? (selectedRisk?.id === riskId ? selectedRisk : null)
  const options = risk && !risks.some((item) => item.id === risk.id) ? [risk, ...risks] : risks
  return (
    <Modal
      title="生成 Draft Change Set"
      open={open}
      confirmLoading={submitting}
      okButtonProps={{ disabled: readOnly }}
      onCancel={onClose}
      onOk={() => form.submit()}
      destroyOnHidden
    >
      <Form
        disabled={readOnly}
        form={form}
        layout="vertical"
        onFinish={(value) => void onCreate(value)}
        onValuesChange={(changed) => {
          if ('release_risk_id' in changed) {
            const selected = risks.find((item) => item.id === changed.release_risk_id)
            setSelectedRisk(selected ?? null)
            form.setFieldValue('impact_run_id', selected?.impact_run_id)
          }
        }}
      >
        <Form.Item name="title" label="变更集名称" rules={[{ required: true }]}>
          <Input maxLength={200} />
        </Form.Item>
        <Form.Item name="release_risk_id" label="发布风险证据" rules={[{ required: true }]}>
          <Select
            showSearch
            optionFilterProp="label"
            virtual={false}
            options={options.map((item) => ({
              value: item.id,
              label: `${item.title} · 风险 ${item.score}`,
            }))}
          />
        </Form.Item>
        <CatalogPagination query={riskQuery} label="可选风险" />
        <Form.Item name="impact_run_id" label="绑定影响分析" rules={[{ required: true }]}>
          <Select
            disabled
            options={impacts.map((item) => ({ value: item.id, label: item.title }))}
          />
        </Form.Item>
        {risk ? <Alert type="success" title="风险与影响证据已绑定，提交后不可替换。" /> : null}
      </Form>
    </Modal>
  )
}

function ChangeItems({
  detail,
  readOnly,
  onReview,
}: {
  detail: AIChangeSetDetail
  readOnly: boolean
  onReview: (value: { item: AIChangeItem; decision: 'accept' | 'reject' }) => void
}) {
  const items = detail.items
  if (items.length === 0) {
    return <Typography.Text type="secondary">AI 没有给出可审核的变更项</Typography.Text>
  }
  return (
    <Flex vertical gap={12}>
      {items.map((item) => (
        <Card
          key={item.id}
          size="small"
          title={
            <Space wrap>
              <Tag>{itemTypeLabel(item.item_type)}</Tag>
              <Tag color={item.action === 'create' ? 'blue' : 'purple'}>
                {item.action === 'create' ? '新增' : '修改'}
              </Tag>
              <Typography.Text strong>{item.title}</Typography.Text>
            </Space>
          }
          extra={
            item.review_status === 'pending' ? (
              <Space>
                <Button
                  disabled={readOnly}
                  aria-label="拒绝"
                  onClick={() => onReview({ item, decision: 'reject' })}
                >
                  拒绝
                </Button>
                <Button
                  type="primary"
                  disabled={readOnly}
                  onClick={() => onReview({ item, decision: 'accept' })}
                >
                  审核并接受
                </Button>
              </Space>
            ) : (
              <Tag color={item.review_status === 'accepted' ? 'success' : 'default'}>
                {item.review_status === 'accepted' ? '已接受' : '已拒绝'}
              </Tag>
            )
          }
        >
          <Flex vertical gap={12}>
            <AIChangeBaseline detail={detail} item={item} />
            <AIChangeReviewReceipt item={item} projectId={detail.project_id} />
          </Flex>
        </Card>
      ))}
    </Flex>
  )
}

function ReviewChangeItemDialog({
  detail,
  apiError,
  readOnly,
  value,
  submitting,
  onClose,
  onSubmit,
}: {
  detail: AIChangeSetDetail | undefined
  apiError: string
  readOnly: boolean
  value: ReviewSelection | null
  submitting: boolean
  onClose: () => void
  onSubmit: (
    item: AIChangeItem,
    decision: 'accept' | 'reject',
    content: Record<string, unknown> | undefined,
    note: string,
  ) => Promise<void>
}) {
  if (!value || detail?.id !== value.changeSetId) return null
  return (
    <ReviewChangeItemDialogContent
      detail={detail}
      apiError={apiError}
      readOnly={readOnly}
      key={`${value.changeSetId}:${value.item.id}:${value.decision}`}
      value={value}
      submitting={submitting}
      onClose={onClose}
      onSubmit={onSubmit}
    />
  )
}

function ReviewChangeItemDialogContent({
  detail,
  apiError,
  readOnly,
  value,
  submitting,
  onClose,
  onSubmit,
}: {
  detail: AIChangeSetDetail | undefined
  apiError: string
  readOnly: boolean
  value: ReviewSelection
  submitting: boolean
  onClose: () => void
  onSubmit: (
    item: AIChangeItem,
    decision: 'accept' | 'reject',
    content: Record<string, unknown> | undefined,
    note: string,
  ) => Promise<void>
}) {
  const originalContent = JSON.stringify(value.item.proposed_content)
  const [content, setContent] = useState(() => JSON.stringify(value.item.proposed_content, null, 2))
  const [note, setNote] = useState(value.item.review_note)
  const [error, setError] = useState('')
  const [discardOpen, setDiscardOpen] = useState(false)
  const allowLeaveRef = useRef(false)
  const dirty =
    content !== JSON.stringify(value.item.proposed_content, null, 2) ||
    note !== value.item.review_note
  function requestClose() {
    if (submitting) return
    if (dirty) setDiscardOpen(true)
    else onClose()
  }
  return (
    <>
      <AIDraftProtection
        dirty={dirty || submitting}
        allowLeaveRef={allowLeaveRef}
        title="审核修改尚未保存"
        description="离开会丢弃变更内容和备注；不会自动接受或拒绝。"
      />
      <Modal
        title="审核修改尚未保存"
        open={discardOpen}
        okText="放弃修改"
        cancelText="继续编辑"
        onOk={onClose}
        onCancel={() => setDiscardOpen(false)}
      >
        关闭会丢弃本次修改，不会写入审核决定。
      </Modal>
      <Modal
        title={value.decision === 'accept' ? '编辑并接受变更项' : '拒绝变更项'}
        open
        confirmLoading={submitting}
        okButtonProps={{ disabled: readOnly }}
        closable={!submitting}
        maskClosable={false}
        keyboard={!submitting}
        onCancel={requestClose}
        onOk={() => {
          let parsed: Record<string, unknown> | undefined
          if (value.decision === 'accept') {
            try {
              const candidate: unknown = JSON.parse(content)
              if (!candidate || typeof candidate !== 'object' || Array.isArray(candidate)) {
                throw new Error('内容必须是 JSON 对象')
              }
              parsed =
                JSON.stringify(candidate) === originalContent
                  ? undefined
                  : (candidate as Record<string, unknown>)
            } catch (parseError) {
              setError(parseError instanceof Error ? parseError.message : 'JSON 格式无效')
              return
            }
          }
          void onSubmit(value.item, value.decision, parsed, note)
        }}
      >
        {detail ? (
          <Flex vertical gap={12} style={{ marginBottom: 16 }}>
            <AIChangeSource detail={detail} projectId={detail.project_id} />
            <AIChangeBaseline
              detail={detail}
              item={value.item}
              proposed={readDraft(content, value.item.proposed_content)}
            />
          </Flex>
        ) : null}
        {apiError ? <Alert type="error" showIcon title={apiError} /> : null}
        {value.decision === 'accept' ? (
          <>
            <Typography.Paragraph type="secondary">
              接受后只创建或更新草稿；不会发布或执行。
            </Typography.Paragraph>
            <Input.TextArea
              aria-label="变更内容 JSON"
              rows={14}
              value={content}
              onChange={(event) => setContent(event.target.value)}
            />
            {error ? <Typography.Text type="danger">{error}</Typography.Text> : null}
          </>
        ) : null}
        <Input.TextArea
          aria-label="审核备注"
          rows={3}
          maxLength={2000}
          value={note}
          placeholder="审核备注（可选）"
          onChange={(event) => setNote(event.target.value)}
          style={{ marginTop: 12 }}
        />
      </Modal>
    </>
  )
}
function readDraft(content: string, original: Record<string, unknown>): Record<string, unknown> {
  try {
    const parsed: unknown = JSON.parse(content)
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : original
  } catch {
    return original
  }
}

function statusLabel(value: string): string {
  return (
    {
      generating: '生成中',
      draft: '待审核',
      partially_reviewed: '部分审核',
      accepted: '已接受',
      rejected: '已拒绝',
      failed: '失败',
    }[value] ?? value
  )
}

function statusColor(value: string): string {
  return (
    {
      generating: 'processing',
      draft: 'warning',
      partially_reviewed: 'processing',
      accepted: 'success',
      rejected: 'default',
      failed: 'error',
    }[value] ?? 'default'
  )
}

function itemTypeLabel(value: AIChangeItem['item_type']): string {
  return { test_case: 'Test Case', workflow: 'Workflow', assertion: 'Assertion' }[value]
}
