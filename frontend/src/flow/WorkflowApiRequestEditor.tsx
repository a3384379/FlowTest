import WorkflowRequestDrawer from './WorkflowRequestDrawer'
import axios from 'axios'
import { apiErrorMessage } from '../lib/api'
import {
  BulkDraftContext,
  useBulkDraft,
  type BulkDraft,
} from '../features/api-console/use-bulk-draft'
import { useNodeEditContext } from './editor/node-edit-session'
import { useInspectorPresentation } from './editor/inspector-presentation'
import {
  applyRequestEditorDraft,
  extraRequestPolicies,
  requestOverridesFromFields,
  type RequestOverrides,
} from './editor/request-overrides'
import { EyeOutlined, SettingOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import {
  Alert,
  Button,
  Checkbox,
  ConfigProvider,
  Descriptions,
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
  const presentation = useInspectorPresentation()
  const apiId = stringValue(props.node.config.api_definition_id)
  const pinnedVersion = numberValue(props.node.config.api_version)
  const currentVersion = props.api?.current_version

  const summary = (
    <Space orientation="vertical" className="full-width" size="small">
      <RequestInheritanceSummary node={props.node} version={pinnedVersion ?? currentVersion} />
      {canUpgrade(props.editable, pinnedVersion, currentVersion) && (
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
    </Space>
  )
  if (presentation === 'fullscreen') {
    return (
      <div className="workflow-request-inline">
        {summary}
        {!apiId || !props.projectId ? (
          <Alert type="warning" showIcon title="选择接口和项目后可配置节点请求" />
        ) : (
          <RequestEditorLoader
            {...props}
            apiId={apiId}
            pinnedVersion={pinnedVersion}
            onClose={() => undefined}
          />
        )}
      </div>
    )
  }
  return (
    <>
      <Space orientation="vertical" className="full-width" size="small">
        {summary}
        <Button
          block
          icon={<SettingOutlined />}
          disabled={!apiId || !props.projectId}
          onClick={() => setOpen(true)}
        >
          配置节点请求
        </Button>
      </Space>
      <WorkflowRequestDrawer projectId={props.projectId} open={open} onClose={() => setOpen(false)}>
        {
          <RequestEditorLoader
            {...props}
            apiId={apiId}
            pinnedVersion={pinnedVersion}
            onClose={() => setOpen(false)}
          />
        }
      </WorkflowRequestDrawer>
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
  const session = useNodeEditContext()
  const restored = session?.draft.requestDraft
  const [form] = Form.useForm<RequestEditorFields>()
  const inherited = useMemo(() => requestOverrides(node), [node])
  const [modes, setModes] = useState(() => restored?.modes ?? sectionModes(inherited))
  const customDrafts = useRef<Partial<Record<RequestSectionKey, Partial<RequestEditorFields>>>>(
    restored?.customDrafts ?? {},
  )
  const templateFields = useMemo(() => editorFields(detail, {}), [detail])
  const [preview, setPreview] = useState<unknown>(null)
  const [previewing, setPreviewing] = useState(false)

  const [initialFields] = useState(() => restored?.fields ?? editorFields(detail, inherited))
  const [activeTab, setActiveTab] = useState(() => restored?.activeTab ?? 'params')
  const bulkDrafts = useRef<Record<string, BulkDraft>>(restored?.bulkDrafts ?? {})
  const [error, setError] = useState<string | null>(null)
  const watchedFields = Form.useWatch([], form) as RequestEditorFields | undefined
  useEffect(() => {
    form.setFieldsValue(initialFields)
  }, [form, initialFields])
  function remember(nextModes = modes, tab = activeTab, dirty = true) {
    session?.setRequest(
      {
        apiVersion: detail.version,
        fields: form.getFieldsValue(true),
        modes: nextModes,
        customDrafts: customDrafts.current,
        activeTab: tab,
        bulkDrafts: bulkDrafts.current,
      },
      dirty,
    )
  }
  useEffect(() => {
    session?.registerRequestApply(save)
    return () => session?.registerRequestApply(null)
  })

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
    const nextModes = { ...modes, [section]: nextMode }
    setModes(nextModes)
    remember(nextModes)
  }

  async function effectiveOverrides(): Promise<RequestOverrides> {
    if (Object.values(bulkDrafts.current).some((draft) => draft.text !== null))
      throw new Error('请先应用或取消批量输入')
    const values = await form.validateFields()
    return buildOverrides(values, modes)
  }

  async function save() {
    if (!editable) return false
    try {
      await effectiveOverrides()
      const next = applyRequestEditorDraft(node, {
        apiVersion: detail.version,
        fields: form.getFieldsValue(true),
        modes,
        customDrafts: customDrafts.current,
        activeTab,
        bulkDrafts: bulkDrafts.current,
      })
      if (session) {
        if (!session.apply(next)) {
          setError('节点配置未能应用，请检查名称、JSON 字段或外部修改冲突。')
          return false
        }
      } else onUpdate(next)
      setError(null)
      onClose()
      return true
    } catch {
      setError('请修正请求字段和 JSON 格式后再应用。')
      return false
    }
  }

  async function showPreview() {
    if (!projectId || !environmentId) return
    setPreviewing(true)
    try {
      const overrides = await effectiveOverrides()
      const result = await previewApi(projectId, detail.api_definition_id, environmentId, {
        version: detail.version,
        serviceOverride: stringValue(node.config.service_override),
        endpointVariant: stringValue(node.config.endpoint_variant),
        queryParametersOverride: overrides.query_parameters,
        headersOverride: overrides.headers,
        bodyOverride: overrides.body?.value,
        useBodyOverride: overrides.body !== undefined,
      })
      setPreview(withFileMetadata(result, artifacts))
    } catch (error) {
      setError(previewFailureMessage(error))
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
      <BulkDraftContext.Provider
        value={{
          drafts: restored?.bulkDrafts ?? {},
          onChange: (key, value) => {
            bulkDrafts.current = { ...bulkDrafts.current, [key]: value }
            remember()
          },
        }}
      >
        <Form form={form} layout="vertical" onValuesChange={() => remember()}>
          <Tabs
            activeKey={activeTab}
            onChange={(tab) => {
              setActiveTab(tab)
              remember(modes, tab, false)
            }}
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
                    <BodyEditor
                      artifacts={artifacts}
                      syncHeaders={modes.headers === 'custom'}
                      onProgrammaticChange={() => remember()}
                    />
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
      </BulkDraftContext.Provider>
      <RequestActions
        error={error}
        policies={extraRequestPolicies(node.config.request_overrides)}
        limitation={previewLimitation(node, detail, modes, watchedFields ?? initialFields)}
        environmentId={environmentId}
        editable={editable}
        previewing={previewing}
        onPreview={() => void showPreview()}
        onSave={() => void save()}
      />
      <Modal
        width={760}
        title="模板请求预览（不发送）"
        open={preview !== null}
        footer={null}
        onCancel={() => setPreview(null)}
      >
        <pre className="preview-code">{JSON.stringify(preview, null, 2)}</pre>
      </Modal>
    </>
  )
}

function previewFailureMessage(error: unknown): string {
  if (!axios.isAxiosError<{ error?: { trace_id?: unknown } }>(error))
    return '预览失败，请检查请求字段、JSON 格式与环境配置。'
  const traceId = error.response?.data?.error?.trace_id
  const message = apiErrorMessage(error)
  return typeof traceId === 'string' ? `${message}（追踪 ID：${traceId}）` : message
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
  const { bulkText, setBulkText, bulkErrors, setBulkErrors } = useBulkDraft('params')
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
  const { bulkText, setBulkText, bulkErrors, setBulkErrors } = useBulkDraft('headers')
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
  return requestOverridesFromFields(values, modes)
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

function previewLimitation(
  node: WorkflowNode,
  detail: ApiVersion,
  modes: ReturnType<typeof sectionModes>,
  fields: RequestEditorFields,
): string | null {
  if (extraRequestPolicies(node.config.request_overrides).length)
    return '当前预览接口不支持节点的额外请求策略，预览已禁用。'
  if (modes.body !== 'custom') return null
  try {
    const body = toBodyInput(fields)
    if (body.body_kind !== detail.body_kind || body.body === null)
      return '当前预览接口无法表达该 Body 类型变化或空值覆盖，预览已禁用。'
  } catch {
    return '请先修正 Body JSON 格式。'
  }
  return null
}

function canUpgrade(editable: boolean, pinned?: number, current?: number): boolean {
  return editable && pinned !== undefined && current !== undefined && pinned !== current
}

function RequestActions({
  error,
  policies,
  limitation,
  environmentId,
  editable,
  previewing,
  onPreview,
  onSave,
}: {
  error: string | null
  policies: string[]
  limitation: string | null
  environmentId?: string | null
  editable: boolean
  previewing: boolean
  onPreview: () => void
  onSave: () => void
}) {
  return (
    <>
      {' '}
      {error && <Alert type="error" title={error} />}
      <Alert
        type="info"
        title="模板请求预览（不发送）"
        description="不包含上游运行结果、边映射、运行时凭据或轮询结果；实际执行以已发布版本为准。"
      />
      {policies.length > 0 && (
        <Alert type="info" title="已保留其他请求策略" description={policies.join('、')} />
      )}
      {limitation && <Alert type="warning" title={limitation} />}
      <Space className="workflow-request-actions" wrap>
        <Button
          icon={<EyeOutlined />}
          loading={previewing}
          disabled={!environmentId || Boolean(limitation)}
          onClick={onPreview}
        >
          预览模板请求
        </Button>
        {editable && (
          <Button type="primary" onClick={onSave}>
            保存节点配置
          </Button>
        )}
      </Space>
      {!environmentId && (
        <Typography.Text type="secondary">选择环境后可预览模板请求。</Typography.Text>
      )}
    </>
  )
}
