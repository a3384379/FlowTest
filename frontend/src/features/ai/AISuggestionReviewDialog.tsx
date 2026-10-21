import {
  Alert,
  Button,
  Descriptions,
  Form,
  Input,
  InputNumber,
  Modal,
  Space,
  Table,
  Tabs,
  Typography,
} from 'antd'
import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import AIDraftProtection from './AIDraftProtection'
import ResponseCodeReader from '../api-console/ResponseCodeReader'
import { apiErrorWithTrace } from '../../lib/api'
import { useRouteScopedState } from '../../lib/use-route-scoped-state'
import { projectPath } from '../projects/project-routing'
import type { AISuggestion } from './ai-service'

type Props = {
  projectId: string
  suggestion: AISuggestion
  decision: 'accept' | 'reject'
  canEdit: boolean
  submitting: boolean
  onClose: () => void
  onReload: () => Promise<void>
  onSubmit: (input: {
    id: string
    decision: 'accept' | 'reject'
    content?: Record<string, unknown>
    note: string
  }) => Promise<AISuggestion | null>
}
export default function AISuggestionReviewDialog(props: Props) {
  const { suggestion, decision, canEdit, submitting, onClose, onSubmit } = props
  const original = JSON.stringify(suggestion.content, null, 2)
  const [edited, setEdited] = useState(original),
    [note, setNote] = useState(suggestion.review_note ?? '')
  const [error, setError] = useState(''),
    [fieldError, setFieldError] = useState(''),
    [discard, setDiscard] = useState(false),
    [refreshing, setRefreshing] = useState(false)
  const allowLeaveRef = useRef(false)
  const editable = canEdit && suggestion.review_status === 'pending'
  const dirty =
    suggestion.review_status === 'pending' &&
    reviewDirty(suggestion, original, edited, note, fieldError)
  const parsed = parseSuggestion(edited)
  async function submit() {
    if (!editable || submitting) return
    if (decision === 'accept' && (!parsed || fieldError)) {
      setError(fieldError || '建议内容必须是 JSON 对象')
      return
    }
    const result = await onSubmit({
      id: suggestion.id,
      decision,
      content: decision === 'accept' ? parsed! : undefined,
      note,
    })
    if (result) {
      allowLeaveRef.current = true
      setEdited(JSON.stringify(result.content, null, 2))
      setNote(result.review_note)
      setError('')
    } else setError('审核结果未确认，输入已保留。可刷新审核状态核对已保存结果，再决定是否重试。')
  }
  async function reload() {
    setRefreshing(true)
    try {
      await props.onReload()
      setError('')
    } catch (error) {
      setError(apiErrorWithTrace(error))
    } finally {
      setRefreshing(false)
    }
  }
  function close() {
    if (dirty) setDiscard(true)
    else onClose()
  }
  return (
    <>
      <AIDraftProtection
        dirty={dirty}
        allowLeaveRef={allowLeaveRef}
        title="审核内容尚未保存"
        description="离开将放弃当前审核内容与备注。"
      />
      <Modal
        open
        title={reviewTitle(editable, decision, suggestion.review_status)}
        width={780}
        style={{ top: 24 }}
        styles={{ body: { maxHeight: 'calc(100dvh - 190px)', overflowY: 'auto' } }}
        onCancel={close}
        footer={
          <Space wrap>
            <Button disabled={submitting} loading={refreshing} onClick={() => void reload()}>
              刷新审核状态
            </Button>
            <Button onClick={close}>{editable ? '取消' : '关闭'}</Button>
            {editable ? (
              <Button
                type="primary"
                danger={decision === 'reject'}
                loading={submitting}
                onClick={() => void submit()}
              >
                {decision === 'accept' ? '确认接受' : '确认拒绝'}
              </Button>
            ) : null}
          </Space>
        }
      >
        <Typography.Title level={4}>{suggestion.title}</Typography.Title>
        <Alert
          showIcon
          type="info"
          title={reviewOutcome(suggestion)}
          description="审核不会自动发布或执行。用例和流程的接受结果可形成草稿；断言和归因保存为审核记录。"
        />
        <AcceptedAIResource projectId={props.projectId} suggestion={suggestion} />
        {error ? <Alert type="error" title={error} /> : null}
        {fieldError ? <Alert type="error" title={fieldError} /> : null}
        <ReviewContent
          suggestion={suggestion}
          decision={decision}
          editable={editable && !submitting}
          model={{ edited, note, parsed, setEdited, setNote, setFieldError, setError }}
        />
      </Modal>
      <Modal
        open={discard}
        title="审核内容尚未保存"
        okText="放弃修改"
        cancelText="继续编辑"
        onOk={() => {
          allowLeaveRef.current = true
          setDiscard(false)
          onClose()
        }}
        onCancel={() => setDiscard(false)}
      >
        关闭将放弃当前内容与备注。
      </Modal>
    </>
  )
}
function reviewOutcome(suggestion: AISuggestion): string {
  if (suggestion.review_status === 'rejected') return '已拒绝，可回看内容和备注'
  if (suggestion.review_status === 'accepted') return '已接受，请继续检查审核结果'
  return '待人工审核，请检查建议内容后明确接受或拒绝'
}
export function AcceptedAIResource({
  projectId,
  suggestion,
}: {
  projectId: string
  suggestion: AISuggestion
}) {
  if (suggestion.review_status !== 'accepted') return null
  const type = suggestion.accepted_resource_type,
    id = suggestion.accepted_resource_id
  if (type === 'workflow' && id)
    return (
      <Typography.Paragraph>
        <Link to={`${projectPath(projectId, 'workflows')}?${new URLSearchParams({ focus: id })}`}>
          打开流程草稿
        </Link>{' '}
        · {id}
      </Typography.Paragraph>
    )
  if (type === 'test_case' && id)
    return (
      <Typography.Paragraph>
        <Link
          to={`${projectPath(projectId, 'assets')}?${new URLSearchParams({ type: 'case', focus: id, version: 'draft' })}`}
        >
          打开用例草稿
        </Link>{' '}
        · {id}
      </Typography.Paragraph>
    )
  return (
    <Typography.Paragraph>
      已保存审核记录；
      {type || id
        ? `资产类型 ${type ?? '未提供'}，ID ${id ?? '未提供'}，没有可确认的跳转入口。`
        : '未提供独立资产 ID。'}
    </Typography.Paragraph>
  )
}
function parseSuggestion(text: string): Record<string, unknown> | null {
  try {
    const value: unknown = JSON.parse(text)
    return value && typeof value === 'object' && !Array.isArray(value)
      ? (value as Record<string, unknown>)
      : null
  } catch {
    return null
  }
}
function SuggestionFields({
  suggestion,
  value,
  editable,
  onChange,
  onError,
}: {
  suggestion: AISuggestion
  value: Record<string, unknown> | null
  editable: boolean
  onChange: (value: Record<string, unknown>) => void
  onError: (error: string) => void
}) {
  if (!value) return <Alert type="warning" title="建议内容不是有效对象，请在高级 JSON 中修正。" />
  const change = (key: string, next: unknown) => onChange({ ...value, [key]: next })
  return (
    <Form layout="vertical">
      {suggestion.suggestion_type === 'assertion' ? (
        <AssertionFields value={value} editable={editable} onChange={change} onError={onError} />
      ) : null}
      {['workflow', 'test_case'].includes(suggestion.suggestion_type) ? (
        <>
          <Form.Item label="草稿名称">
            <Input
              aria-label="草稿名称"
              value={text(value.name)}
              readOnly={!editable}
              maxLength={200}
              onChange={(e) => change('name', e.target.value)}
            />
          </Form.Item>
          <Form.Item label="草稿说明">
            <Input.TextArea
              aria-label="草稿说明"
              value={text(value.description)}
              readOnly={!editable}
              rows={3}
              onChange={(e) => change('description', e.target.value)}
            />
          </Form.Item>
          <DefinitionSummary value={value.definition} />
        </>
      ) : null}
      {suggestion.suggestion_type === 'failure_analysis' ? (
        <>
          <Form.Item label="归因类别">
            <Input
              aria-label="归因类别"
              value={text(value.category)}
              readOnly={!editable}
              onChange={(e) => change('category', e.target.value)}
            />
          </Form.Item>
          <Form.Item label="置信度">
            <InputNumber
              value={typeof value.confidence === 'number' ? value.confidence : undefined}
              readOnly={!editable}
              min={0}
              max={1}
              step={0.1}
              onChange={(next) => change('confidence', next)}
            />
          </Form.Item>
          <Form.Item label="归因说明">
            <Input.TextArea
              aria-label="归因说明"
              value={text(value.reason)}
              readOnly={!editable}
              onChange={(e) => change('reason', e.target.value)}
            />
          </Form.Item>
        </>
      ) : null}
      <ResponseCodeReader value={value} title="当前建议完整内容" />
    </Form>
  )
}
function AssertionFields({
  value,
  editable,
  onChange,
  onError,
}: {
  value: Record<string, unknown>
  editable: boolean
  onChange: (key: string, value: unknown) => void
  onError: (error: string) => void
}) {
  return (
    <>
      <Form.Item label="断言表达式">
        <Input
          aria-label="断言表达式"
          value={text(value.expression)}
          readOnly={!editable}
          onChange={(e) => onChange('expression', e.target.value)}
        />
      </Form.Item>
      <Form.Item label="比较操作">
        <Input
          aria-label="比较操作"
          value={text(value.operator)}
          readOnly={!editable}
          onChange={(e) => onChange('operator', e.target.value)}
        />
      </Form.Item>
      <ExpectedValueInput
        value={value.expected}
        editable={editable}
        onChange={(next) => onChange('expected', next)}
        onError={onError}
      />
      {typeof value.status_code === 'number' ? (
        <Form.Item label="预期状态码">
          <InputNumber
            value={value.status_code}
            readOnly={!editable}
            onChange={(next) => onChange('status_code', next)}
          />
        </Form.Item>
      ) : null}
    </>
  )
}
function DefinitionSummary({ value }: { value: unknown }) {
  if (!value || typeof value !== 'object' || Array.isArray(value))
    return <Typography.Paragraph>未提供可识别的定义，请检查原文。</Typography.Paragraph>
  const definition = value as Record<string, unknown>
  if (Array.isArray(definition.nodes))
    return (
      <Table
        size="small"
        pagination={false}
        scroll={{ x: 420 }}
        rowKey={(node) => (typeof node.id === 'string' ? node.id : JSON.stringify(node))}
        dataSource={definition.nodes.filter(isRecord)}
        columns={[
          { title: '节点', dataIndex: 'name' },
          { title: '类型', dataIndex: 'type' },
          { title: '节点ID', dataIndex: 'id' },
        ]}
      />
    )
  return (
    <Descriptions
      column={1}
      items={[
        { key: 'workflow', label: '关联流程', children: text(definition.workflow_id) || '未提供' },
        {
          key: 'environment',
          label: '环境',
          children: text(definition.environment_id) || '未提供',
        },
      ]}
    />
  )
}
function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value))
}
function text(value: unknown): string {
  return typeof value === 'string' ? value : ''
}
function reviewDirty(
  suggestion: AISuggestion,
  original: string,
  edited: string,
  note: string,
  error: string,
): boolean {
  return edited !== original || note !== (suggestion.review_note ?? '') || Boolean(error)
}
function reviewTitle(
  editable: boolean,
  decision: 'accept' | 'reject',
  status: AISuggestion['review_status'],
): string {
  if (status !== 'pending') return '已审核建议'
  if (!editable) return '只读建议'
  return decision === 'accept' ? '接受建议' : '拒绝建议'
}

type ReviewContentModel = {
  edited: string
  note: string
  parsed: Record<string, unknown> | null
  setEdited: (text: string) => void
  setNote: (text: string) => void
  setFieldError: (text: string) => void
  setError: (text: string) => void
}
function ReviewContent({
  suggestion,
  decision,
  editable,
  model,
}: {
  suggestion: AISuggestion
  decision: 'accept' | 'reject'
  editable: boolean
  model: ReviewContentModel
}) {
  const { edited, note, parsed, setEdited, setNote, setFieldError, setError } = model
  return (
    <>
      {' '}
      <Tabs
        items={[
          {
            key: 'structured',
            label: '内容与字段',
            children: (
              <SuggestionFields
                suggestion={suggestion}
                value={parsed}
                editable={editable && decision === 'accept'}
                onChange={(value) => {
                  setEdited(JSON.stringify(value, null, 2))
                  setError('')
                }}
                onError={setFieldError}
              />
            ),
          },
          {
            key: 'json',
            label: '高级 JSON',
            forceRender: true,
            children: (
              <Form layout="vertical">
                <Form.Item label="建议内容">
                  <Input.TextArea
                    aria-label="建议内容"
                    readOnly={!editable || decision !== 'accept'}
                    rows={12}
                    value={edited}
                    onChange={(e) => {
                      setEdited(e.target.value)
                      setFieldError('')
                      setError('')
                    }}
                  />
                </Form.Item>
              </Form>
            ),
          },
          {
            key: 'original',
            label: '原始建议',
            children: <ResponseCodeReader value={suggestion.content} title="原始建议内容" />,
          },
        ]}
      />
      <Form layout="vertical">
        <Form.Item label="审核备注">
          <Input.TextArea
            aria-label="审核备注"
            rows={3}
            maxLength={2000}
            readOnly={!editable}
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
        </Form.Item>
      </Form>
      {!editable ? (
        <Descriptions
          column={1}
          items={[
            { key: 'status', label: '审核状态', children: suggestion.review_status },
            { key: 'by', label: '审核人', children: suggestion.reviewed_by_id ?? '未提供' },
            { key: 'at', label: '审核时间', children: suggestion.reviewed_at ?? '未提供' },
          ]}
        />
      ) : null}
    </>
  )
}

function ExpectedValueInput({
  value,
  editable,
  onChange,
  onError,
}: {
  value: unknown
  editable: boolean
  onChange: (value: unknown) => void
  onError: (message: string) => void
}) {
  const serialized = JSON.stringify(value) ?? ''
  const [draft, setDraft] = useRouteScopedState(null, serialized, serialized)
  return (
    <Form.Item label="预期值 JSON">
      <Input
        aria-label="预期值 JSON"
        value={draft}
        readOnly={!editable}
        onChange={(event) => {
          setDraft(event.target.value)
          try {
            const parsed: unknown = JSON.parse(event.target.value)
            onError('')
            onChange(parsed)
          } catch {
            onError('预期值必须是有效 JSON')
          }
        }}
      />
    </Form.Item>
  )
}
