import { EyeOutlined, SettingOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import {
  Alert,
  Button,
  Checkbox,
  ConfigProvider,
  Descriptions,
  Drawer,
  Form,
  Input,
  Modal,
  Segmented,
  Space,
  Spin,
  Tabs,
  Tag,
  Typography,
} from 'antd'
import { useEffect, useMemo, useRef, useState } from 'react'

import BodyEditor from '../features/api-console/BodyEditor'
import { toBodyFields, toBodyInput, type BodyEditorFields } from '../features/api-console/body-edit'
import {
  parseBulkHeaders,
  parseBulkParameters,
  serializeBulkHeaders,
  serializeBulkParameters,
  type KeyValueField,
  type ParameterField,
} from '../features/api-console/bulk-edit'
import { BulkEditor, DynamicFields } from '../features/api-console/StructuredFields'
import { getApiDetail, previewApi } from '../features/api-console/api-service'
import type { ApiDefinition, ApiVersion, Artifact, WorkflowNode } from '../lib/api'

type SectionMode = 'inherit' | 'custom'
type RequestSectionKey = 'params' | 'headers' | 'body'

type RequestEditorFields = BodyEditorFields & {
  query_parameters: ApiVersion['query_parameters']
  headers: KeyValueField[]
}

type BodyOverride = {
  kind: ApiVersion['body_kind']
  value: unknown
}

type RequestOverrides = {
  query_parameters?: ApiVersion['query_parameters']
  headers?: Record<string, string>
  body?: BodyOverride
}

type EditorProps = {
  projectId?: string | null
  environmentId?: string | null
  node: WorkflowNode
  api?: ApiDefinition
  artifacts: Artifact[]
  editable: boolean
  onUpdate: (node: WorkflowNode) => void
}

export default function WorkflowApiRequestEditor(props: EditorProps) {
  const [open, setOpen] = useState(false)
  const apiId = stringValue(props.node.config.api_definition_id)
  const pinnedVersion = numberValue(props.node.config.api_version)
  const currentVersion = props.api?.current_version

  return (
    <>
      <Space orientation="vertical" className="full-width" size="small">
        <RequestInheritanceSummary
          node={props.node}
          version={pinnedVersion ?? props.api?.current_version}
        />
        {props.editable &&
          pinnedVersion !== undefined &&
          currentVersion !== undefined &&
          pinnedVersion !== currentVersion && (
            <Button
              type="link"
              className="workflow-request-upgrade"
              onClick={() =>
                props.onUpdate({
                  ...props.node,
                  config: { ...props.node.config, api_version: currentVersion },
                })
              }
            >
              更新至接口最新 v{currentVersion}
            </Button>
          )}
        <Button
          block
          icon={<SettingOutlined />}
          disabled={!apiId || !props.projectId}
          onClick={() => setOpen(true)}
        >
          配置节点请求
        </Button>
      </Space>
      <Drawer
        destroyOnHidden
        size="large"
        title="节点请求配置"
        open={open}
        onClose={() => setOpen(false)}
      >
        {open && (
          <RequestEditorLoader
            {...props}
            apiId={apiId}
            pinnedVersion={pinnedVersion}
            onClose={() => setOpen(false)}
          />
        )}
      </Drawer>
    </>
  )
}

function RequestEditorLoader({
  apiId,
  pinnedVersion,
  onClose,
  ...props
}: EditorProps & { apiId: string; pinnedVersion?: number; onClose: () => void }) {
  const detail = useQuery({
    queryKey: ['workflow-api-detail', props.projectId, apiId, pinnedVersion],
    queryFn: () => getApiDetail(props.projectId ?? '', apiId, pinnedVersion),
    enabled: Boolean(props.projectId && apiId),
  })
  if (detail.isLoading) return <Spin />
  if (detail.isError) {
    return (
      <Alert
        type="error"
        showIcon
        title="接口版本加载失败"
        description="请确认该接口版本仍然存在。"
      />
    )
  }
  if (!detail.data) return null
  return <RequestEditor {...props} detail={detail.data.version} onClose={onClose} />
}

function RequestInheritanceSummary({ node, version }: { node: WorkflowNode; version?: number }) {
  const overrides = requestOverrides(node)
  const customSections = [
    overrides.query_parameters !== undefined ? 'Params' : null,
    overrides.headers !== undefined ? 'Headers' : null,
    overrides.body !== undefined ? 'Body' : null,
  ].filter(Boolean)
  return (
    <Space wrap>
      <Tag color={version === undefined ? 'gold' : 'blue'}>
        {version === undefined ? '版本待固定' : `固定 v${version}`}
      </Tag>
      {customSections.length ? (
        <Tag color="purple">节点覆盖：{customSections.join(' / ')}</Tag>
      ) : (
        <Tag>全部继承接口模板</Tag>
      )}
    </Space>
  )
}

function RequestEditor({
  node,
  detail,
  environmentId,
  projectId,
  artifacts,
  editable,
  onUpdate,
  onClose,
}: EditorProps & { detail: ApiVersion; onClose: () => void }) {
  const [form] = Form.useForm<RequestEditorFields>()
  const inherited = useMemo(() => requestOverrides(node), [node])
  const [modes, setModes] = useState(() => sectionModes(inherited))
  const customDrafts = useRef<Partial<Record<RequestSectionKey, Partial<RequestEditorFields>>>>({})
  const templateFields = useMemo(() => editorFields(detail, {}), [detail])
  const [preview, setPreview] = useState<unknown>(null)
  const [previewing, setPreviewing] = useState(false)

  useEffect(() => {
    form.setFieldsValue(editorFields(detail, inherited))
  }, [detail, form, inherited])

  function changeMode(section: RequestSectionKey, nextMode: SectionMode) {
    const currentMode = modes[section]
    if (currentMode === nextMode) return
    if (currentMode === 'custom') {
      customDrafts.current[section] = fieldsForSection(form.getFieldsValue(true), section)
    }
    const nextFields =
      nextMode === 'custom'
        ? (customDrafts.current[section] ?? fieldsForSection(templateFields, section))
        : fieldsForSection(templateFields, section)
    form.setFieldsValue(nextFields)
    setModes((current) => ({ ...current, [section]: nextMode }))
  }

  async function effectiveOverrides(): Promise<RequestOverrides> {
    const values = await form.validateFields()
    return buildOverrides(values, modes)
  }

  async function save() {
    const overrides = await effectiveOverrides()
    onUpdate({
      ...node,
      config: {
        ...node.config,
        api_version: detail.version,
        request_overrides: overrides,
      },
    })
    onClose()
  }

  async function showPreview() {
    if (!projectId || !environmentId) return
    setPreviewing(true)
    try {
      const overrides = await effectiveOverrides()
      const result = await previewApi(projectId, detail.api_definition_id, environmentId, {
        version: detail.version,
        queryParametersOverride: overrides.query_parameters,
        headersOverride: overrides.headers,
        bodyOverride: overrides.body?.value,
        useBodyOverride: overrides.body !== undefined,
      })
      setPreview(withFileMetadata(result, artifacts))
    } finally {
      setPreviewing(false)
    }
  }

  return (
    <>
      <Alert
        showIcon
        type="info"
        title={`继承接口模板 v${detail.version}`}
        description="选择“节点自定义”后仅保存差异到当前工作流，不会修改接口管理中的模板。"
      />
      <Descriptions
        size="small"
        column={2}
        items={[
          { key: 'method', label: 'Method', children: detail.method },
          { key: 'path', label: 'Path', children: detail.path },
        ]}
        className="workflow-request-base"
      />
      <Form form={form} layout="vertical">
        <Tabs
          items={[
            {
              key: 'params',
              label: sectionLabel('Params', modes.params),
              children: (
                <RequestSection
                  mode={modes.params}
                  editable={editable}
                  onMode={(mode) => changeMode('params', mode)}
                >
                  <ParameterFields />
                </RequestSection>
              ),
              forceRender: true,
            },
            {
              key: 'headers',
              label: sectionLabel('Headers', modes.headers),
              children: (
                <RequestSection
                  mode={modes.headers}
                  editable={editable}
                  onMode={(mode) => changeMode('headers', mode)}
                >
                  <HeaderFields />
                </RequestSection>
              ),
              forceRender: true,
            },
            {
              key: 'body',
              label: sectionLabel('Body', modes.body),
              children: (
                <RequestSection
                  mode={modes.body}
                  editable={editable}
                  onMode={(mode) => changeMode('body', mode)}
                >
                  <BodyEditor artifacts={artifacts} syncHeaders={modes.headers === 'custom'} />
                </RequestSection>
              ),
              forceRender: true,
            },
            {
              key: 'auth',
              label: 'Auth',
              children: (
                <Alert
                  showIcon
                  type="info"
                  title={`继承接口认证方式：${detail.auth_kind}`}
                  description="认证信息继续由接口模板和环境 Secret 管理，工作流节点不复制明文凭据。"
                />
              ),
            },
          ]}
        />
      </Form>
      <Space className="workflow-request-actions" wrap>
        <Button
          icon={<EyeOutlined />}
          loading={previewing}
          disabled={!environmentId}
          onClick={() => void showPreview()}
        >
          预览最终请求
        </Button>
        {editable && (
          <Button type="primary" onClick={() => void save()}>
            保存节点配置
          </Button>
        )}
      </Space>
      {!environmentId && (
        <Typography.Text type="secondary">选择环境后可预览最终请求。</Typography.Text>
      )}
      <Modal
        width={760}
        title="最终请求预览（Secret 已脱敏）"
        open={preview !== null}
        footer={null}
        onCancel={() => setPreview(null)}
      >
        <pre className="preview-code">{JSON.stringify(preview, null, 2)}</pre>
      </Modal>
    </>
  )
}

function RequestSection({
  mode,
  editable,
  onMode,
  children,
}: {
  mode: SectionMode
  editable: boolean
  onMode: (mode: SectionMode) => void
  children: React.ReactNode
}) {
  return (
    <Space orientation="vertical" className="full-width" size="middle">
      <Segmented<SectionMode>
        value={mode}
        disabled={!editable}
        options={[
          { value: 'inherit', label: '继承接口模板' },
          { value: 'custom', label: '节点自定义' },
        ]}
        onChange={onMode}
      />
      {mode === 'inherit' && (
        <Alert
          type="success"
          showIcon
          title="当前展示接口模板默认值（只读）"
          description="切换为“节点自定义”后，可以在下方模板值的基础上修改。"
        />
      )}
      <div
        className={`workflow-request-section${mode === 'inherit' ? ' is-readonly' : ''}`}
        aria-label={mode === 'inherit' ? '接口模板只读内容' : '节点自定义内容'}
      >
        <ConfigProvider componentDisabled={mode === 'inherit' || !editable}>
          {children}
        </ConfigProvider>
      </div>
    </Space>
  )
}

function ParameterFields() {
  const form = Form.useFormInstance<RequestEditorFields>()
  const [bulkText, setBulkText] = useState<string | null>(null)
  const [bulkErrors, setBulkErrors] = useState<string[]>([])
  if (bulkText !== null) {
    return (
      <BulkEditor
        label="Params"
        text={bulkText}
        errors={bulkErrors}
        help="每行使用“参数名: 值”；# 开头表示禁用，同名参数会按顺序保留。"
        onChange={setBulkText}
        onCancel={() => setBulkText(null)}
        onApply={() => {
          const parsed = parseBulkParameters(bulkText)
          setBulkErrors(parsed.errors)
          if (parsed.errors.length) return
          form.setFieldValue('query_parameters', parsed.values)
          setBulkText(null)
        }}
      />
    )
  }
  return (
    <Form.List name="query_parameters">
      {(fields, { add, remove }) => (
        <DynamicFields
          fields={fields}
          onAdd={() => add({ enabled: true, name: '', value: '' })}
          onRemove={remove}
          onBulkEdit={() => {
            setBulkText(
              serializeBulkParameters(
                (form.getFieldValue('query_parameters') ?? []) as ParameterField[],
              ),
            )
            setBulkErrors([])
          }}
          render={(field) => (
            <>
              <Form.Item name={[field.name, 'enabled']} valuePropName="checked">
                <Checkbox aria-label="启用参数" />
              </Form.Item>
              <Form.Item name={[field.name, 'name']} rules={[{ required: true }]}>
                <Input placeholder="参数名" />
              </Form.Item>
              <Form.Item name={[field.name, 'value']}>
                <Input placeholder="值" />
              </Form.Item>
            </>
          )}
        />
      )}
    </Form.List>
  )
}

function HeaderFields() {
  const form = Form.useFormInstance<RequestEditorFields>()
  const [bulkText, setBulkText] = useState<string | null>(null)
  const [bulkErrors, setBulkErrors] = useState<string[]>([])
  if (bulkText !== null) {
    return (
      <BulkEditor
        label="Headers"
        text={bulkText}
        errors={bulkErrors}
        help="每行使用“Header-Name: Value”；空行和 # 注释会被忽略。"
        onChange={setBulkText}
        onCancel={() => setBulkText(null)}
        onApply={() => {
          const parsed = parseBulkHeaders(bulkText, form.getFieldValue('headers') ?? [])
          setBulkErrors(parsed.errors)
          if (parsed.errors.length) return
          form.setFieldValue('headers', parsed.values)
          setBulkText(null)
        }}
      />
    )
  }
  return (
    <Form.List name="headers">
      {(fields, { add, remove }) => (
        <DynamicFields
          fields={fields}
          onAdd={() => add({ name: '', value: '' })}
          onRemove={remove}
          onBulkEdit={() => {
            setBulkText(serializeBulkHeaders(form.getFieldValue('headers') ?? []))
            setBulkErrors([])
          }}
          render={(field) => (
            <>
              <Form.Item name={[field.name, 'name']} rules={[{ required: true }]}>
                <Input placeholder="Header 名称" />
              </Form.Item>
              <Form.Item name={[field.name, 'value']}>
                <Input placeholder="值" />
              </Form.Item>
            </>
          )}
        />
      )}
    </Form.List>
  )
}

function requestOverrides(node: WorkflowNode): RequestOverrides {
  const value = node.config.request_overrides
  if (!isRecord(value)) return {}
  return {
    query_parameters: Array.isArray(value.query_parameters)
      ? (value.query_parameters as ApiVersion['query_parameters'])
      : undefined,
    headers: isStringRecord(value.headers) ? value.headers : undefined,
    body: isBodyOverride(value.body) ? value.body : undefined,
  }
}

function sectionModes(overrides: RequestOverrides) {
  return {
    params: modeFor(overrides.query_parameters),
    headers: modeFor(overrides.headers),
    body: modeFor(overrides.body),
  }
}

function editorFields(detail: ApiVersion, overrides: RequestOverrides): RequestEditorFields {
  const body = overrides.body
    ? { ...detail, body_kind: overrides.body.kind, body: overrides.body.value }
    : detail
  return {
    query_parameters: overrides.query_parameters ?? detail.query_parameters,
    headers: toKeyValues(overrides.headers ?? detail.headers),
    ...toBodyFields(body),
  }
}

function fieldsForSection(
  values: RequestEditorFields,
  section: RequestSectionKey,
): Partial<RequestEditorFields> {
  if (section === 'params') {
    return { query_parameters: (values.query_parameters ?? []).map((item) => ({ ...item })) }
  }
  if (section === 'headers') {
    return { headers: (values.headers ?? []).map((item) => ({ ...item })) }
  }
  return {
    body_mode: values.body_mode,
    body_raw_type: values.body_raw_type,
    body_text: values.body_text,
    body_form: (values.body_form ?? []).map((item) => ({ ...item })),
    body_multipart: (values.body_multipart ?? []).map((item) => ({ ...item })),
  }
}

function buildOverrides(
  values: RequestEditorFields,
  modes: ReturnType<typeof sectionModes>,
): RequestOverrides {
  const body = toBodyInput(values)
  return {
    ...(modes.params === 'custom' ? { query_parameters: values.query_parameters ?? [] } : {}),
    ...(modes.headers === 'custom' ? { headers: toRecord(values.headers) } : {}),
    ...(modes.body === 'custom' ? { body: { kind: body.body_kind, value: body.body } } : {}),
  }
}

function withFileMetadata(value: unknown, artifacts: Artifact[]): unknown {
  if (!isRecord(value) || !isRecord(value.body) || !Array.isArray(value.body.files)) return value
  const byId = new Map(artifacts.map((artifact) => [artifact.id, artifact]))
  const filePreviews: Array<Record<string, unknown>> = []
  for (const file of value.body.files) {
    if (!isRecord(file) || typeof file.artifact_id !== 'string') continue
    const artifact = byId.get(file.artifact_id)
    filePreviews.push(
      artifact
        ? { field: file.field, filename: artifact.filename, size_bytes: artifact.size_bytes }
        : { field: file.field, artifact_id: file.artifact_id, missing: true },
    )
  }
  return {
    ...value,
    file_previews: filePreviews,
  }
}

function sectionLabel(label: string, mode: SectionMode) {
  return (
    <Space size={4}>
      <span>{label}</span>
      {mode === 'custom' && <Tag color="purple">已覆盖</Tag>}
    </Space>
  )
}

function modeFor(value: unknown): SectionMode {
  return value === undefined ? 'inherit' : 'custom'
}

function toKeyValues(value: Record<string, string>): KeyValueField[] {
  return Object.entries(value).map(([name, fieldValue]) => ({ name, value: fieldValue }))
}

function toRecord(values: KeyValueField[] = []): Record<string, string> {
  return Object.fromEntries(
    values.filter((item) => item.name).map((item) => [item.name, item.value]),
  )
}

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function numberValue(value: unknown): number | undefined {
  return typeof value === 'number' ? value : undefined
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isStringRecord(value: unknown): value is Record<string, string> {
  return isRecord(value) && Object.values(value).every((item) => typeof item === 'string')
}

function isBodyOverride(value: unknown): value is BodyOverride {
  return (
    isRecord(value) &&
    ['none', 'json', 'raw', 'form', 'multipart'].includes(String(value.kind)) &&
    'value' in value
  )
}
