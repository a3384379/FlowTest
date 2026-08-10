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
import { useMemo, useState } from 'react'

import type { ContractRun, GeneratedContractCase, Page } from '../../lib/api'
import { useProjectContext } from '../projects/use-project-context'
import {
  createContractRun,
  listContractRuns,
  listGeneratedContractCases,
  reviewGeneratedContractCase,
} from './contract-service'

export default function ContractAutomationPanel() {
  const queryClient = useQueryClient()
  const { projectId } = useProjectContext()
  const [file, setFile] = useState<File | null>(null)
  const [baselineRunId, setBaselineRunId] = useState<string | null>(null)
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const [editor, setEditor] = useState<GeneratedContractCase | null>(null)
  const runs = useQuery({
    queryKey: ['contract-runs', projectId],
    queryFn: () => listContractRuns(projectId!),
    enabled: Boolean(projectId),
  })
  const cases = useQuery({
    queryKey: ['contract-cases', projectId, selectedRunId],
    queryFn: () => listGeneratedContractCases(projectId!, selectedRunId!),
    enabled: Boolean(projectId && selectedRunId),
  })
  const runItems = pageItems(runs.data)
  const caseItems = pageItems(cases.data)
  const selectedRun = useMemo(
    () => findSelectedRun(runItems, selectedRunId),
    [runItems, selectedRunId],
  )
  const createRun = useMutation({
    mutationFn: () => createContractRun(projectId!, file!, baselineRunId),
    onSuccess: async (created) => {
      setFile(null)
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
    }) =>
      reviewGeneratedContractCase(
        projectId!,
        input.item.contract_run_id,
        input.item.id,
        input.decision,
        { name: input.name, definition: input.definition, note: input.note },
      ),
    onSuccess: async () => {
      setEditor(null)
      await queryClient.invalidateQueries({
        queryKey: ['contract-cases', projectId, selectedRunId],
      })
    },
  })

  return (
    <Space direction="vertical" size="large" className="contract-panel">
      <ContractUploadCard
        file={file}
        baselineRunId={baselineRunId}
        runs={runItems}
        uploading={createRun.isPending}
        onFile={setFile}
        onBaseline={setBaselineRunId}
        onSubmit={() => createRun.mutate()}
      />
      <ContractRunTable
        items={runItems}
        loading={runs.isLoading}
        selectedRunId={selectedRunId}
        onSelect={setSelectedRunId}
      />
      {selectedRun && <ContractSummary run={selectedRun} />}
      {selectedRun && (
        <GeneratedCaseTable
          items={caseItems}
          loading={cases.isLoading}
          onAccept={setEditor}
          onReject={(item) => review.mutate({ item, decision: 'reject', note: 'Web 审核拒绝' })}
        />
      )}
      {editor && (
        <CaseReviewDialog
          item={editor}
          submitting={review.isPending}
          onClose={() => setEditor(null)}
          onSubmit={(input) => review.mutate({ item: editor, decision: 'accept', ...input })}
        />
      )}
    </Space>
  )
}

function pageItems<T>(page: Page<T> | undefined): T[] {
  return page ? page.items : []
}

function findSelectedRun(items: ContractRun[], selectedRunId: string | null): ContractRun | null {
  return items.find((item) => item.id === selectedRunId) || null
}

export function ContractUploadCard({
  file,
  baselineRunId,
  runs,
  uploading,
  onFile,
  onBaseline,
  onSubmit,
}: {
  file: File | null
  baselineRunId: string | null
  runs: ContractRun[]
  uploading: boolean
  onFile: (file: File | null) => void
  onBaseline: (id: string | null) => void
  onSubmit: () => void
}) {
  return (
    <Card title="OpenAPI 契约分析" size="small">
      <Space wrap>
        <Upload
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
        <Select
          aria-label="契约基线"
          allowClear
          placeholder="自动选择同名最新基线"
          value={baselineRunId ?? undefined}
          style={{ minWidth: 240 }}
          options={runs.map((run) => ({
            value: run.id,
            label: `${run.source_name} · ${formatTime(run.created_at)}`,
          }))}
          onChange={(value?: string) => onBaseline(value ?? null)}
        />
        <Button
          type="primary"
          icon={<FileSearchOutlined />}
          disabled={!file}
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
  items,
  loading,
  onAccept,
  onReject,
}: {
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
                  disabled={item.review_status !== 'pending'}
                  onClick={() => onAccept(item)}
                >
                  编辑并接受
                </Button>
                <Button
                  size="small"
                  danger
                  icon={<CloseOutlined />}
                  disabled={item.review_status !== 'pending'}
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
  item,
  submitting,
  onClose,
  onSubmit,
}: {
  item: GeneratedContractCase
  submitting: boolean
  onClose: () => void
  onSubmit: (input: { name: string; definition: Record<string, unknown>; note: string }) => void
}) {
  const [form] = Form.useForm()
  return (
    <Modal
      open
      title="编辑并接受契约用例"
      okText="接受草稿"
      cancelText="取消"
      confirmLoading={submitting}
      onCancel={onClose}
      onOk={() =>
        void form.validateFields().then((values) =>
          onSubmit({
            name: values.name,
            definition: JSON.parse(values.definition) as Record<string, unknown>,
            note: values.note ?? '',
          }),
        )
      }
    >
      <Form
        form={form}
        layout="vertical"
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
                try {
                  JSON.parse(value)
                } catch {
                  throw new Error('请输入有效的 JSON')
                }
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
      <Typography.Text type="secondary">接受后才允许进入后续测试资产流程。</Typography.Text>
    </Modal>
  )
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
