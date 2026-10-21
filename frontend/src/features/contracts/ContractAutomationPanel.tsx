import {
  CheckOutlined,
  CloseOutlined,
  DiffOutlined,
  FileSearchOutlined,
  UploadOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Form,
  Input,
  Modal,
  Progress,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  Upload,
} from 'antd'
import { useState } from 'react'

import {
  apiErrorMessage,
  apiErrorTraceId,
  type ContractRun,
  type GeneratedContractCase,
  type Page,
} from '../../lib/api'
import CatalogPagination from '../../components/CatalogPagination'
import QueryFailureNotice from '../../components/QueryFailureNotice'
import { useCatalogQuery } from '../../lib/catalog-query'
import { useProjectContext } from '../projects/use-project-context'
import { useProjectCapabilities } from '../projects/use-project-capabilities'
import {
  createContractRun,
  getContractRun,
  listContractRuns,
  listGeneratedContractCases,
  reviewGeneratedContractCase,
} from './contract-service'
import ContractReferencePicker from './ContractReferencePicker'

export default function ContractAutomationPanel() {
  const { projectId } = useProjectContext()
  return <ContractAutomationWorkspace key={projectId ?? 'none'} />
}

function ContractAutomationWorkspace() {
  const queryClient = useQueryClient()
  const { projectId } = useProjectContext()
  const { canEdit, permissions } = useProjectCapabilities()
  const editable = canEdit && permissions.isSuccess
  const [runSearch, setRunSearch] = useState('')
  const [reviewStatus, setReviewStatus] = useState<GeneratedContractCase['review_status'] | 'all'>(
    'all',
  )
  const [file, setFile] = useState<File | null>(null)
  const [baselineRunId, setBaselineRunId] = useState<string | null>(null)
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const [editor, setEditor] = useState<GeneratedContractCase | null>(null)
  const runs = useCatalogQuery(
    'contract-runs',
    projectId,
    (page) => listContractRuns(projectId!, page, 20, runSearch),
    true,
    runSearch,
  )
  const selected = useQuery({
    queryKey: ['contract-run', projectId, selectedRunId],
    queryFn: () => getContractRun(projectId!, selectedRunId!),
    enabled: Boolean(projectId && selectedRunId),
  })
  const cases = useCatalogQuery(
    'contract-cases',
    projectId,
    (page) =>
      listGeneratedContractCases(
        projectId!,
        selectedRunId!,
        page,
        20,
        reviewStatus === 'all' ? undefined : reviewStatus,
      ),
    Boolean(selectedRunId),
    `${selectedRunId}:${reviewStatus}`,
  )
  const runItems = pageItems(runs.data)
  const caseItems = pageItems(cases.data)
  const selectedRun = selected.data
  function selectRun(id: string) {
    const item = runItems.find((run) => run.id === id)
    if (item) queryClient.setQueryData(['contract-run', projectId, id], item)
    setSelectedRunId(id)
  }
  const createRun = useMutation({
    mutationFn: () => {
      if (!editable) throw new Error('当前项目为只读或权限读取失败')
      return createContractRun(projectId!, file!, baselineRunId)
    },
    onSuccess: async (created) => {
      setFile(null)
      queryClient.setQueryData(['contract-run', projectId, created.id], created)
      setSelectedRunId(created.id)
      await queryClient.invalidateQueries({ queryKey: ['contract-runs', projectId] })
    },
  })
  const review = useMutation({
    mutationFn: (input: {
      item: GeneratedContractCase
      decision: 'accept' | 'reject'
      name?: string
      definition?: Record<string, unknown>
      note: string
    }) => {
      if (!editable) throw new Error('当前项目为只读或权限读取失败')
      return reviewGeneratedContractCase(
        projectId!,
        input.item.contract_run_id,
        input.item.id,
        input.decision,
        { name: input.name, definition: input.definition, note: input.note },
      )
    },
    onSuccess: async (item) => {
      setEditor((current) => (current?.id === item.id ? null : current))
      await queryClient.invalidateQueries({
        queryKey: ['contract-cases', projectId],
      })
    },
  })
  const errors = [permissions.error, createRun.error, review.error]
  const error = errors.find(Boolean)
  function openReview(item: GeneratedContractCase) {
    review.reset()
    setEditor(item)
  }

  return (
    <Space direction="vertical" size="large" className="contract-panel">
      {error ? <Alert showIcon type="error" title={apiErrorMessage(error)} /> : null}
      <ContractUploadCard
        projectId={projectId}
        readOnly={!editable}
        file={file}
        baselineRunId={baselineRunId}
        uploading={createRun.isPending}
        onFile={setFile}
        onBaseline={setBaselineRunId}
        onSubmit={() => createRun.mutate()}
      />
      <Input.Search
        aria-label="分析批次搜索"
        placeholder="按文档名称搜索批次"
        onSearch={setRunSearch}
        allowClear
      />
      <ContractRunTable
        items={runItems}
        loading={runs.isLoading}
        selectedRunId={selectedRunId}
        onSelect={selectRun}
      />
      <CatalogPagination query={runs} label="分析批次" />
      <QueryFailureNotice queries={[selected, cases]} />
      {selectedRun && <ContractSummary run={selectedRun} />}
      {selectedRun && (
        <>
          <Select
            aria-label="候选审核状态"
            value={reviewStatus}
            onChange={setReviewStatus}
            options={[
              { value: 'all', label: '全部审核状态' },
              { value: 'pending', label: '待审核' },
              { value: 'accepted', label: '已接受' },
              { value: 'rejected', label: '已拒绝' },
            ]}
          />
          <GeneratedCaseTable
            readOnly={!editable || review.isPending || cases.isError}
            items={caseItems}
            loading={cases.isLoading}
            onAccept={openReview}
            onReject={(item) => review.mutate({ item, decision: 'reject', note: 'Web 审核拒绝' })}
          />
          <CatalogPagination query={cases} label="生成候选" />
        </>
      )}
      {editor && (
        <CaseReviewDialog
          readOnly={!editable}
          item={editor}
          submitting={review.isPending}
          error={review.error}
          onClose={() => {
            if (!review.isPending) setEditor(null)
          }}
          onSubmit={(input) => review.mutate({ item: editor, decision: 'accept', ...input })}
        />
      )}
    </Space>
  )
}

function pageItems<T>(page?: Page<T>): T[] {
  return page?.items ?? []
}

export function ContractUploadCard({
  projectId,
  readOnly = false,
  file,
  baselineRunId,
  uploading,
  onFile,
  onBaseline,
  onSubmit,
}: {
  projectId: string | null
  readOnly?: boolean
  file: File | null
  baselineRunId: string | null
  uploading: boolean
  onFile: (file: File | null) => void
  onBaseline: (id: string | null) => void
  onSubmit: () => void
}) {
  const [baselineReady, setBaselineReady] = useState(true)
  return (
    <Card title="OpenAPI 契约分析" size="small">
      <Space wrap>
        <Upload
          disabled={readOnly || uploading}
          accept=".json,.yaml,.yml"
          maxCount={1}
          beforeUpload={(selected) => {
            onFile(selected)
            return false
          }}
          onRemove={() => onFile(null)}
          fileList={file ? [{ uid: file.name, name: file.name, status: 'done' }] : []}
        >
          <Button icon={<UploadOutlined />}>选择契约文档</Button>
        </Upload>
        <ContractReferencePicker
          projectId={projectId}
          kind="run"
          label="契约基线"
          disabled={readOnly || uploading}
          value={baselineRunId ?? undefined}
          onReadyChange={setBaselineReady}
          onChange={(value?: string) => onBaseline(value ?? null)}
        />
        <Button
          type="primary"
          icon={<FileSearchOutlined />}
          disabled={readOnly || !file || !baselineReady}
          loading={uploading}
          onClick={onSubmit}
        >
          生成契约用例
        </Button>
      </Space>
    </Card>
  )
}

export function ContractRunTable({
  items,
  loading,
  selectedRunId,
  onSelect,
}: {
  items: ContractRun[]
  loading: boolean
  selectedRunId: string | null
  onSelect: (id: string) => void
}) {
  return (
    <Card title="契约运行" size="small">
      <Table
        rowKey="id"
        size="small"
        loading={loading}
        pagination={false}
        dataSource={items}
        rowClassName={(item) => (item.id === selectedRunId ? 'selected-row' : '')}
        columns={[
          { title: '文档', dataIndex: 'source_name' },
          {
            title: '变更',
            render: (_, item) =>
              `+${item.diff_summary.added} / ~${item.diff_summary.changed} / -${item.diff_summary.deleted}`,
          },
          {
            title: '破坏性',
            render: (_, item) => (
              <Tag color={item.breaking_changes.length ? 'red' : 'green'}>
                {item.breaking_changes.length}
              </Tag>
            ),
          },
          {
            title: 'Schema 覆盖率',
            render: (_, item) => `${item.coverage.schema_coverage_percent}%`,
          },
          { title: '生成用例', dataIndex: 'generated_case_count' },
          { title: '时间', render: (_, item) => formatTime(item.created_at) },
          {
            title: '操作',
            render: (_, item) => (
              <Button size="small" icon={<DiffOutlined />} onClick={() => onSelect(item.id)}>
                审核用例
              </Button>
            ),
          },
        ]}
      />
    </Card>
  )
}

export function ContractSummary({ run }: { run: ContractRun }) {
  return (
    <Card title="契约差异与覆盖率" size="small">
      <Descriptions
        size="small"
        column={4}
        items={[
          { label: '操作覆盖', children: `${run.coverage.operation_coverage_percent}%` },
          { label: 'Schema 覆盖', children: `${run.coverage.schema_coverage_percent}%` },
          { label: 'Schema 字段', children: run.coverage.schema_fields_total },
          { label: '破坏性变更', children: run.breaking_changes.length },
        ]}
      />
      <Progress
        percent={run.coverage.schema_coverage_percent}
        status={run.coverage.schema_coverage_percent === 100 ? 'success' : 'normal'}
      />
      {run.breaking_changes.length > 0 && (
        <Alert
          type="error"
          showIcon
          message="检测到破坏性变更"
          description={run.breaking_changes.map((item) => item.message).join('；')}
        />
      )}
    </Card>
  )
}

export function GeneratedCaseTable({
  readOnly = false,
  items,
  loading,
  onAccept,
  onReject,
}: {
  readOnly?: boolean
  items: GeneratedContractCase[]
  loading: boolean
  onAccept: (item: GeneratedContractCase) => void
  onReject: (item: GeneratedContractCase) => void
}) {
  return (
    <Card title="生成草稿审核" size="small">
      <Table
        rowKey="id"
        size="small"
        loading={loading}
        pagination={false}
        dataSource={items}
        columns={[
          { title: '名称', dataIndex: 'name' },
          { title: '方法', dataIndex: 'method', width: 80 },
          { title: '路径', dataIndex: 'path' },
          {
            title: '生成类型',
            render: (_, item) => <Tag>{generationLabel(item.generation_kind)}</Tag>,
          },
          {
            title: '审核状态',
            render: (_, item) => (
              <Tag color={reviewColor(item.review_status)}>{reviewLabel(item.review_status)}</Tag>
            ),
          },
          {
            title: '操作',
            width: 190,
            render: (_, item) => (
              <Space>
                <Button
                  size="small"
                  type="primary"
                  icon={<CheckOutlined />}
                  disabled={readOnly || item.review_status !== 'pending'}
                  onClick={() => onAccept(item)}
                >
                  编辑并接受
                </Button>
                <Button
                  size="small"
                  danger
                  icon={<CloseOutlined />}
                  disabled={readOnly || item.review_status !== 'pending'}
                  onClick={() => onReject(item)}
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

export function CaseReviewDialog({
  readOnly = false,
  item,
  submitting,
  onClose,
  onSubmit,
  error,
}: {
  readOnly?: boolean
  item: GeneratedContractCase
  submitting: boolean
  onClose: () => void
  onSubmit: (input: { name: string; definition: Record<string, unknown>; note: string }) => void
  error?: unknown
}) {
  const [form] = Form.useForm<{ name: string; definition: string; note?: string }>()
  return (
    <Modal
      open
      title="编辑并接受契约用例"
      okText="接受草稿"
      cancelText="取消"
      confirmLoading={submitting}
      okButtonProps={{ disabled: readOnly }}
      onCancel={onClose}
      onOk={() => form.submit()}
    >
      {error ? (
        <Alert
          type="error"
          showIcon
          title={apiErrorMessage(error)}
          description={apiErrorTraceId(error)}
        />
      ) : null}
      <Form
        disabled={readOnly}
        form={form}
        layout="vertical"
        onFinish={(values) =>
          onSubmit({
            name: values.name,
            definition: parseCaseDefinition(values.definition),
            note: values.note ?? '',
          })
        }
        initialValues={{
          name: item.name,
          definition: JSON.stringify(item.definition, null, 2),
          note: '',
        }}
      >
        <Form.Item name="name" label="用例名称" rules={[{ required: true }]}>
          <Input maxLength={200} />
        </Form.Item>
        <Form.Item
          name="definition"
          label="生成定义"
          rules={[
            { required: true },
            {
              validator: async (_, value: string) => {
                parseCaseDefinition(value)
              },
            },
          ]}
        >
          <Input.TextArea rows={12} className="code-editor" />
        </Form.Item>
        <Form.Item name="note" label="审核说明">
          <Input.TextArea rows={2} maxLength={2000} />
        </Form.Item>
      </Form>
      <Typography.Text type="secondary">接受后才允许进入后续测试用例流程。</Typography.Text>
    </Modal>
  )
}

function parseCaseDefinition(value: string): Record<string, unknown> {
  let result: unknown
  try {
    result = JSON.parse(value)
  } catch (error) {
    if (error instanceof SyntaxError) throw new Error('请输入有效的JSON', { cause: error })
    throw error
  }
  if (typeof result !== 'object' || result === null || Array.isArray(result))
    throw new Error('生成定义必须为JSON对象')
  return result as Record<string, unknown>
}

function generationLabel(value: GeneratedContractCase['generation_kind']) {
  return { example: '示例', boundary: '边界', property: '属性', negative: '异常' }[value]
}

function reviewLabel(value: GeneratedContractCase['review_status']) {
  return { pending: '待审核', accepted: '已接受', rejected: '已拒绝' }[value]
}

function reviewColor(value: GeneratedContractCase['review_status']) {
  return { pending: 'gold', accepted: 'green', rejected: 'red' }[value]
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    dateStyle: 'short',
    timeStyle: 'short',
  }).format(new Date(value))
}
