import { InboxOutlined, LinkOutlined } from '@ant-design/icons'
import {
  Alert,
  Input,
  Modal,
  Radio,
  Segmented,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Upload,
  Typography,
} from 'antd'
import { useMemo, useState } from 'react'

import type { ImportChange, ImportRun } from '../../lib/api'
import type { ImportPreviewInput, ImportSourceType, ImportUrlDiscovery } from './api-service'

type ImportDialogProps = {
  open: boolean
  importing: boolean
  result: ImportRun | null
  onClose: () => void
  onDiscover: (url: string) => Promise<ImportUrlDiscovery>
  onPreview: (input: ImportPreviewInput) => Promise<ImportRun>
  onMerge: (selectedKeys: string[]) => Promise<ImportRun>
}

type ImportInputKind = ImportPreviewInput['kind']

const changeLabels: Record<ImportChange, { label: string; color: string }> = {
  added: { label: '新增', color: 'green' },
  changed: { label: '变更', color: 'blue' },
  deleted: { label: '待停用', color: 'red' },
  unchanged: { label: '未变化', color: 'default' },
}

export default function ImportDialog(props: ImportDialogProps) {
  const [inputKind, setInputKind] = useState<ImportInputKind>('file')
  const [file, setFile] = useState<File | null>(null)
  const [url, setUrl] = useState('')
  const [sourceType, setSourceType] = useState<ImportSourceType>('auto')
  const [discovery, setDiscovery] = useState<ImportUrlDiscovery | null>(null)
  const [documentId, setDocumentId] = useState<string | null>(null)
  const [selectedKeys, setSelectedKeys] = useState<string[] | null>(null)
  const effectiveSelectedKeys = selectedKeys ?? defaultSelection(props.result)

  const completed = props.result?.status === 'applied'
  const inputReady = isImportInputReady(inputKind, file, url, discovery, documentId)

  const submitUrl = async () => {
    const sourceUrl = url.trim()
    if (!isValidHttpUrl(sourceUrl)) return
    const resolved = discovery ?? (await props.onDiscover(sourceUrl))
    if (resolved.documents.length > 1 && !documentId) {
      setDiscovery(resolved)
      return
    }
    const selectedDocumentId = documentId ?? resolved.documents[0]?.id
    if (!selectedDocumentId) return
    await props.onPreview({
      kind: 'url',
      url: sourceUrl,
      sourceType,
      documentId: selectedDocumentId,
    })
  }

  const resetPicker = () => {
    setInputKind('file')
    setFile(null)
    setUrl('')
    setSourceType('auto')
    setDiscovery(null)
    setDocumentId(null)
    setSelectedKeys(null)
  }

  return (
    <Modal
      title="导入接口文档"
      width={820}
      open={props.open}
      confirmLoading={props.importing}
      okText={importOkText(completed, props.result, inputKind, discovery)}
      okButtonProps={{ disabled: !props.result && !inputReady }}
      onCancel={() => {
        resetPicker()
        props.onClose()
      }}
      onOk={() => {
        if (completed) {
          resetPicker()
          props.onClose()
        } else if (props.result) {
          void props.onMerge(effectiveSelectedKeys)
        } else if (inputKind === 'file' && file) {
          void props.onPreview({ kind: 'file', file, sourceType })
        } else if (inputKind === 'url' && isValidHttpUrl(url)) {
          void submitUrl()
        }
      }}
      destroyOnHidden
    >
      {props.result ? (
        <ImportResult
          result={props.result}
          selectedKeys={effectiveSelectedKeys}
          onSelectionChange={setSelectedKeys}
        />
      ) : (
        <ImportPicker
          inputKind={inputKind}
          url={url}
          sourceType={sourceType}
          discovery={discovery}
          documentId={documentId}
          onInputKindChange={(value) => {
            setInputKind(value)
            setSourceType('auto')
            setDiscovery(null)
            setDocumentId(null)
          }}
          onUrlChange={(value) => {
            setUrl(value)
            setDiscovery(null)
            setDocumentId(null)
          }}
          onDocumentChange={setDocumentId}
          onSourceTypeChange={setSourceType}
          onChange={setFile}
        />
      )}
    </Modal>
  )
}

function isImportInputReady(
  inputKind: ImportInputKind,
  file: File | null,
  url: string,
  discovery: ImportUrlDiscovery | null,
  documentId: string | null,
): boolean {
  if (inputKind === 'file') return Boolean(file)
  if (!isValidHttpUrl(url)) return false
  return !discovery || discovery.documents.length === 1 || Boolean(documentId)
}

function importOkText(
  completed: boolean,
  result: ImportRun | null,
  inputKind: ImportInputKind,
  discovery: ImportUrlDiscovery | null,
): string {
  if (completed) return '完成'
  if (result) return '合并所选'
  if (inputKind === 'url' && !discovery) return '解析并生成 Diff'
  return '生成 Diff'
}

function defaultSelection(result: ImportRun | null): string[] {
  if (result?.status !== 'preview') return []
  return result.results
    .filter((item) => item.change === 'added' || item.change === 'changed')
    .map((item) => item.import_key)
}

function ImportPicker({
  inputKind,
  url,
  sourceType,
  discovery,
  documentId,
  onInputKindChange,
  onUrlChange,
  onDocumentChange,
  onSourceTypeChange,
  onChange,
}: {
  inputKind: ImportInputKind
  url: string
  sourceType: ImportSourceType
  discovery: ImportUrlDiscovery | null
  documentId: string | null
  onInputKindChange: (value: ImportInputKind) => void
  onUrlChange: (value: string) => void
  onDocumentChange: (value: string) => void
  onSourceTypeChange: (value: ImportSourceType) => void
  onChange: (file: File) => void
}) {
  return (
    <>
      <Alert
        type="info"
        showIcon
        title={
          inputKind === 'url'
            ? '支持原始接口文档和 Swagger UI 页面'
            : '支持 OpenAPI 3、Swagger 2、Postman、HAR、cURL、Bruno 和 Excel'
        }
        description={
          inputKind === 'url'
            ? '系统会自动发现 Swagger UI、Springdoc、FastAPI 和 Knife4j 页面背后的 OpenAPI 文档。'
            : '系统会按请求方法和规范化路径去重，并展示新增、变更、删除和未变化项。'
        }
      />
      <Segmented
        block
        className="import-source-picker"
        aria-label="导入来源"
        value={inputKind}
        options={[
          { value: 'file', label: '本地文件', icon: <InboxOutlined /> },
          { value: 'url', label: 'URL 导入', icon: <LinkOutlined /> },
        ]}
        onChange={(value) => onInputKindChange(value as ImportInputKind)}
      />
      <div className="import-format-row">
        <Typography.Text>格式识别</Typography.Text>
        <Select
          value={sourceType}
          onChange={onSourceTypeChange}
          options={sourceTypeOptions(inputKind)}
        />
      </div>
      {inputKind === 'file' ? (
        <Upload.Dragger
          accept=".json,.yaml,.yml,.har,.txt,.curl,.bru,.xlsx"
          maxCount={1}
          beforeUpload={(selected) => {
            onChange(selected)
            return false
          }}
        >
          <p className="ant-upload-drag-icon">
            <InboxOutlined />
          </p>
          <p className="ant-upload-text">点击或拖拽文档到此处</p>
          <p className="ant-upload-hint">单个文件最大 50 MB</p>
        </Upload.Dragger>
      ) : (
        <div className="import-url-field">
          <Typography.Text strong>文档或 Swagger UI URL</Typography.Text>
          <Input
            aria-label="文档或 Swagger UI URL"
            prefix={<LinkOutlined />}
            placeholder="https://api.example.com/swagger-ui/index.html"
            value={url}
            status={url && !isValidHttpUrl(url) ? 'error' : undefined}
            onChange={(event) => onUrlChange(event.target.value)}
          />
          {url && !isValidHttpUrl(url) ? (
            <Typography.Text type="danger">请输入有效的 HTTP 或 HTTPS 地址</Typography.Text>
          ) : (
            <Typography.Text type="secondary">
              页面和发现到的文档都由 FlowTest 服务端获取，并逐次执行出站安全校验。
            </Typography.Text>
          )}
          {discovery?.documents.length ? (
            <ImportDocumentPicker
              discovery={discovery}
              documentId={documentId}
              onChange={onDocumentChange}
            />
          ) : null}
        </div>
      )}
    </>
  )
}

function ImportDocumentPicker({
  discovery,
  documentId,
  onChange,
}: {
  discovery: ImportUrlDiscovery
  documentId: string | null
  onChange: (value: string) => void
}) {
  const [search, setSearch] = useState('')
  if (discovery.documents.length <= 1) return null
  const normalizedSearch = search.trim().toLowerCase()
  const documents = discovery.documents.filter((document) => {
    if (!normalizedSearch) return true
    return `${document.name} ${document.url}`.toLowerCase().includes(normalizedSearch)
  })
  return (
    <div className="import-document-picker">
      <Alert
        type="success"
        showIcon
        title={`已发现 ${discovery.documents.length} 份接口文档`}
        description="请选择本次需要生成 Diff 的接口分组。"
      />
      <Input.Search
        aria-label="搜索接口文档分组"
        allowClear
        placeholder="搜索文档名称或 URL"
        value={search}
        onChange={(event) => setSearch(event.target.value)}
      />
      <Radio.Group
        aria-label="接口文档分组"
        value={documentId}
        onChange={(event) => onChange(String(event.target.value))}
      >
        <div className="import-document-options-scroll">
          <Space direction="vertical" size="middle">
            {documents.map((document) => (
              <Radio key={document.id} value={document.id}>
                <span className="import-document-option">
                  <Typography.Text strong>{document.name}</Typography.Text>
                  <Typography.Text type="secondary">{document.url}</Typography.Text>
                </span>
              </Radio>
            ))}
            {!documents.length ? (
              <Typography.Text type="secondary">没有匹配的接口文档分组</Typography.Text>
            ) : null}
          </Space>
        </div>
      </Radio.Group>
    </div>
  )
}

function ImportResult({
  result,
  selectedKeys,
  onSelectionChange,
}: {
  result: ImportRun
  selectedKeys: string[]
  onSelectionChange: (keys: string[]) => void
}) {
  const [search, setSearch] = useState('')
  const [changeFilter, setChangeFilter] = useState<ImportChange | 'all'>('all')
  const filteredResults = useMemo(() => {
    const normalizedSearch = search.trim().toLowerCase()
    return result.results.filter((item) => {
      if (changeFilter !== 'all' && item.change !== changeFilter) return false
      if (!normalizedSearch) return true
      return `${item.name} ${item.method} ${item.path} ${item.import_key}`
        .toLowerCase()
        .includes(normalizedSearch)
    })
  }, [changeFilter, result.results, search])
  return (
    <>
      <Alert
        type={result.status === 'applied' ? 'success' : 'warning'}
        showIcon
        title={result.status === 'applied' ? '合并完成' : '请选择需要合并的变更'}
        description={
          result.status === 'applied'
            ? `已应用 ${result.applied_keys.length} 项变更。`
            : '新增和变更默认选中；删除项默认不选中，只有明确选择后才会停用接口。'
        }
      />
      {result.source_kind === 'url' && result.source_url ? (
        <div className="import-result-sources">
          <Typography.Paragraph
            className="import-result-source"
            copyable={{ text: result.source_url }}
          >
            来源页面：{result.source_url}
          </Typography.Paragraph>
          {result.document_url && result.document_url !== result.source_url ? (
            <Typography.Paragraph
              className="import-result-source"
              copyable={{ text: result.document_url }}
            >
              实际文档：{result.document_url}
            </Typography.Paragraph>
          ) : null}
        </div>
      ) : null}
      <Space size="large" className="import-statistics">
        <Statistic title="新增" value={result.added} styles={{ content: { color: '#16a34a' } }} />
        <Statistic title="变更" value={result.changed} styles={{ content: { color: '#2563eb' } }} />
        <Statistic
          title="待停用"
          value={result.deleted}
          styles={{ content: { color: '#dc2626' } }}
        />
        <Statistic title="未变化" value={result.unchanged} />
      </Space>
      <Space wrap className="import-result-filters">
        <Input.Search
          aria-label="筛选导入接口"
          allowClear
          placeholder="搜索名称、方法或路径"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          style={{ width: 260 }}
        />
        <Select
          aria-label="Diff 筛选"
          value={changeFilter}
          onChange={(value) => setChangeFilter(value as ImportChange | 'all')}
          options={[
            { value: 'all', label: '全部变化' },
            ...Object.entries(changeLabels).map(([value, item]) => ({
              value,
              label: item.label,
            })),
          ]}
          style={{ width: 130 }}
        />
        <Typography.Text type="secondary">
          显示 {filteredResults.length} / {result.results.length} 项
        </Typography.Text>
      </Space>
      <Table
        rowKey="import_key"
        size="small"
        pagination={{
          pageSize: 50,
          showSizeChanger: false,
          showTotal: (total) => `共 ${total} 项`,
        }}
        scroll={{ y: 320 }}
        dataSource={filteredResults}
        rowSelection={
          result.status === 'preview'
            ? {
                selectedRowKeys: selectedKeys,
                preserveSelectedRowKeys: true,
                onChange: (keys) => onSelectionChange(keys.map(String)),
                getCheckboxProps: (item) => ({ disabled: item.change === 'unchanged' }),
              }
            : undefined
        }
        columns={[
          { title: '接口', dataIndex: 'name' },
          { title: '方法', dataIndex: 'method', width: 90 },
          { title: '路径', dataIndex: 'path' },
          {
            title: 'Diff',
            dataIndex: 'change',
            width: 100,
            render: (change: ImportChange) => (
              <Tag color={changeLabels[change].color}>{changeLabels[change].label}</Tag>
            ),
          },
        ]}
      />
    </>
  )
}

function sourceTypeOptions(inputKind: ImportInputKind) {
  const openApiOptions = [
    { value: 'auto', label: '自动识别' },
    { value: 'openapi3', label: 'OpenAPI 3' },
    { value: 'swagger2', label: 'Swagger 2' },
  ]
  if (inputKind === 'url') return openApiOptions
  return [
    ...openApiOptions,
    { value: 'postman', label: 'Postman Collection' },
    { value: 'har', label: 'HAR' },
    { value: 'curl', label: 'cURL' },
    { value: 'bruno', label: 'Bruno' },
    { value: 'excel', label: 'Excel' },
  ]
}

function isValidHttpUrl(value: string): boolean {
  try {
    const parsed = new URL(value.trim())
    return parsed.protocol === 'http:' || parsed.protocol === 'https:'
  } catch {
    return false
  }
}
