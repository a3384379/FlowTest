import { useDraftSession } from '../drafts/draft-session'
import RequestTargetSummary from './RequestTargetSummary'
import { EditOutlined, SaveOutlined } from '@ant-design/icons'
import {
  Button,
  Card,
  Checkbox,
  Empty,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Tabs,
  Tag,
  Typography,
} from 'antd'
import { useEffect, useRef, useState } from 'react'

import BodyEditor from './BodyEditor'
import { toBodyFields, toBodyInput, type BodyEditorFields } from './body-edit'
import {
  parseBulkHeaders,
  parseBulkParameters,
  serializeBulkHeaders,
  serializeBulkParameters,
  type BulkRedactionMode,
  type KeyValueField,
  type ParameterField,
} from './bulk-edit'
import { BulkEditor, DynamicFields } from './StructuredFields'
import type { ApiVersionInput } from './api-service'
import type { ApiDetail, ApiVersion, Artifact } from '../../lib/api'

type APIWorkbenchProps = {
  detail?: ApiDetail
  loading: boolean
  saving: boolean
  previewing: boolean
  onSave: (input: ApiVersionInput) => Promise<ApiVersion>
  onPreview: () => Promise<unknown>
  onRename: () => void
  artifacts?: Artifact[]
  redactionMode?: BulkRedactionMode
  draftScope?: string
}

export type WorkbenchFields = BodyEditorFields & {
  method: ApiVersion['method']
  path: string
  query_parameters: Array<KeyValueField & { enabled: boolean }>
  headers: KeyValueField[]
  auth_kind: ApiVersion['auth_kind']
  auth_config: KeyValueField[]
  extraction_rules: ApiVersion['extraction_rules']
  assertions: Array<Omit<ApiVersion['assertions'][number], 'expected'> & { expected_text: string }>
}

type PersistedApiDraft = {
  schemaVersion: 2
  fields: WorkbenchFields
  baseVersion: number
}

type RestoredApiDraft = {
  fields: WorkbenchFields
  baseVersion: number | null
}

export default function APIWorkbench(props: APIWorkbenchProps) {
  if (!props.detail) {
    return props.loading ? <Card loading /> : <Empty description="请选择接口后进行持续编辑" />
  }
  return <LoadedAPIWorkbench {...props} detail={props.detail} />
}

function LoadedAPIWorkbench(props: APIWorkbenchProps & { detail: ApiDetail }) {
  const [form] = Form.useForm<WorkbenchFields>()
  const [preview, setPreview] = useState<unknown>(null)
  const draft = useApiDraft(form, props)
  const redactionMode = props.redactionMode ?? 'off'
  return (
    <Card
      loading={props.loading}
      title={
        <Space>
          <span>{props.detail.definition.name}</span>
          <Tag color="blue">v{props.detail.version.version}</Tag>
          {draft.restored && <Tag color="orange">本地未保存</Tag>}
          {draft.serverChanged && (
            <Tag color="orange">服务器有新版本，已保留本地编辑，请核对后保存</Tag>
          )}
          {draft.storageError && <Tag color="red">浏览器无法持久化草稿，请先保存再离开</Tag>}
          <Button
            type="text"
            size="small"
            icon={<EditOutlined />}
            aria-label="重命名接口"
            onClick={props.onRename}
          />
        </Space>
      }
      extra={
        <Space>
          <Button
            loading={props.previewing}
            onClick={() => void props.onPreview().then(setPreview)}
          >
            预览最终请求
          </Button>
          <Button
            type="primary"
            icon={<SaveOutlined />}
            loading={props.saving}
            onClick={() => form.submit()}
          >
            保存新版本
          </Button>
        </Space>
      }
    >
      <Form
        form={form}
        layout="vertical"
        onValuesChange={draft.onValuesChange}
        onFinish={draft.onFinish}
      >
        <div className="workbench-request-line">
          <Form.Item name="method" rules={[{ required: true }]}>
            <Select
              className="method-select"
              options={['GET', 'POST', 'PUT', 'PATCH', 'DELETE'].map((value) => ({
                value,
                label: value,
              }))}
            />
          </Form.Item>
          <Form.Item name="path" rules={[{ required: true, message: '请输入请求路径' }]}>
            <Input placeholder="/api/users/{{user_id}}" />
          </Form.Item>
        </div>
        <Tabs
          key={props.detail?.definition.id}
          items={[
            {
              key: 'params',
              label: 'Params',
              children: <ParameterFields onProgrammaticChange={draft.persistCurrent} />,
              forceRender: true,
            },
            {
              key: 'headers',
              label: 'Headers',
              children: (
                <HeaderFields
                  redactionMode={redactionMode}
                  onProgrammaticChange={draft.persistCurrent}
                />
              ),
              forceRender: true,
            },
            {
              key: 'auth',
              label: 'Auth',
              children: <AuthFields redactionMode={redactionMode} />,
              forceRender: true,
            },
            {
              key: 'body',
              label: 'Body',
              children: (
                <BodyEditor
                  artifacts={props.artifacts ?? []}
                  onProgrammaticChange={draft.persistCurrent}
                />
              ),
              forceRender: true,
            },
            { key: 'extract', label: '提取', children: <ExtractionFields />, forceRender: true },
            {
              key: 'assertions',
              label: '断言',
              children: <AssertionFields />,
              forceRender: true,
            },
          ]}
        />
      </Form>
      <Modal
        title={previewTitle(redactionMode)}
        open={preview !== null}
        footer={null}
        onCancel={() => setPreview(null)}
        width={760}
      >
        <RequestTargetSummary preview={preview} />
        <pre className="preview-code">{JSON.stringify(preview, null, 2)}</pre>
      </Modal>
    </Card>
  )
}

function useApiDraft(
  form: ReturnType<typeof Form.useForm<WorkbenchFields>>[0],
  props: APIWorkbenchProps & { detail: ApiDetail },
) {
  const session = useDraftSession()
  const identity = JSON.stringify([props.draftScope ?? null, props.detail.definition.id])
  const activeIdentity = useRef(identity)
  const baseline = useRef<{ identity: string; version: number } | null>(null)
  const [restored, setRestored] = useState(false)
  const [storageError, setStorageError] = useState(false)
  const [serverChanged, setServerChanged] = useState(false)
  useEffect(() => {
    activeIdentity.current = identity
  }, [identity])
  useEffect(() => {
    const changedIdentity = baseline.current?.identity !== identity
    const incomingVersion = props.detail.version.version
    if (!changedIdentity && baseline.current?.version === incomingVersion) return
    const draft = restoreApiSessionDraft(session, identity, props)
    if (draft) session.apis.set(identity, draft)
    if (changedIdentity || !draft)
      form.setFieldsValue(draft?.fields ?? toFields(props.detail.version))
    baseline.current = { identity, version: incomingVersion }
    queueMicrotask(() => {
      setRestored(Boolean(draft))
      setStorageError(Boolean(draft && draft.storageError))
      setServerChanged(Boolean(draft && draft.baseVersion !== incomingVersion))
    })
  }, [form, props, identity, session])
  useEffect(() => {
    if (!restored || !storageError) return
    const blockUnload = (event: BeforeUnloadEvent) => event.preventDefault()
    window.addEventListener('beforeunload', blockUnload)
    return () => window.removeEventListener('beforeunload', blockUnload)
  }, [restored, storageError])
  function persist(values: WorkbenchFields) {
    const baseVersion = session.apis.get(identity)?.baseVersion ?? props.detail.version.version
    const failed = !writeApiDraft(props.draftScope, props.detail.definition.id, values, baseVersion)
    session.apis.set(identity, {
      fields: structuredClone(values),
      generation: session.nextGeneration(),
      storageError: failed,
      baseVersion,
    })
    session.markUnsafe(identity, failed)
    setStorageError(failed)
    setRestored(true)
  }
  return {
    restored,
    storageError,
    serverChanged,
    onValuesChange: (_: unknown, values: WorkbenchFields) => persist(values),
    persistCurrent: () => queueMicrotask(() => persist(form.getFieldsValue(true))),
    onFinish: async (values: WorkbenchFields) => {
      const generation = session.apis.get(identity)?.generation
      const saved = await props.onSave(toInput(values))
      const latest = session.apis.get(identity)
      if (latest && latest.generation !== generation) {
        const persisted = writeApiDraft(
          props.draftScope,
          props.detail.definition.id,
          latest.fields,
          saved.version,
        )
        session.apis.set(identity, {
          ...latest,
          storageError: !persisted,
          baseVersion: saved.version,
        })
        session.markUnsafe(identity, !persisted)
        setStorageError(!persisted)
        return
      }
      // An inactive resource is retained for its next mount; it cannot clear another form.
      if (activeIdentity.current !== identity) return
      const removed = removeApiDraft(props.draftScope, props.detail.definition.id)
      if (removed) session.apis.delete(identity)
      session.markUnsafe(identity, !removed)
      setRestored(!removed)
      setStorageError(!removed)
      setServerChanged(false)
    },
  }
}

function restoreApiSessionDraft(
  session: ReturnType<typeof useDraftSession>,
  identity: string,
  props: APIWorkbenchProps & { detail: ApiDetail },
) {
  const memory = session.apis.get(identity)
  if (memory) return memory
  const stored = readApiDraft(props.draftScope, props.detail.definition.id)
  return stored
    ? {
        fields: stored.fields,
        generation: session.nextGeneration(),
        storageError: false,
        baseVersion: stored.baseVersion ?? props.detail.version.version,
      }
    : null
}

function apiDraftKey(scope: string | undefined, apiId: string): string | null {
  return scope
    ? `flowtest:api-draft:v1:${encodeURIComponent(scope)}:${encodeURIComponent(apiId)}`
    : null
}

function readApiDraft(scope: string | undefined, apiId: string): RestoredApiDraft | null {
  const key = apiDraftKey(scope, apiId)
  if (!key) return null
  try {
    const value: unknown = JSON.parse(window.localStorage.getItem(key) ?? 'null')
    if (isPersistedApiDraft(value)) {
      return { fields: value.fields, baseVersion: value.baseVersion }
    }
    return value && typeof value === 'object'
      ? { fields: value as WorkbenchFields, baseVersion: null }
      : null
  } catch {
    return null
  }
}

function writeApiDraft(
  scope: string | undefined,
  apiId: string,
  fields: WorkbenchFields,
  baseVersion: number,
): boolean {
  const key = apiDraftKey(scope, apiId)
  if (!key) return false
  try {
    const draft: PersistedApiDraft = { schemaVersion: 2, fields, baseVersion }
    window.localStorage.setItem(key, JSON.stringify(draft))
    return true
  } catch {
    return false
  }
}

function isPersistedApiDraft(value: unknown): value is PersistedApiDraft {
  if (!value || typeof value !== 'object') return false
  const draft = value as Partial<PersistedApiDraft>
  return (
    draft.schemaVersion === 2 &&
    typeof draft.baseVersion === 'number' &&
    Boolean(draft.fields && typeof draft.fields === 'object')
  )
}

function removeApiDraft(scope: string | undefined, apiId: string): boolean {
  const key = apiDraftKey(scope, apiId)
  if (!key) return true
  try {
    window.localStorage.removeItem(key)
    return true
  } catch {
    return false
  }
}

function previewTitle(redactionMode: BulkRedactionMode): string {
  return redactionMode === 'on' ? '最终请求预览（Secret 已脱敏）' : '最终请求预览（按原样展示）'
}

function ParameterFields({ onProgrammaticChange }: { onProgrammaticChange: () => void }) {
  const form = Form.useFormInstance<WorkbenchFields>()
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
        onCancel={() => {
          setBulkText(null)
          setBulkErrors([])
        }}
        onApply={() => {
          const parsed = parseBulkParameters(bulkText)
          setBulkErrors(parsed.errors)
          if (parsed.errors.length) return
          form.setFieldValue('query_parameters', parsed.values)
          onProgrammaticChange()
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
            const parameters = (form.getFieldValue('query_parameters') ?? []) as ParameterField[]
            setBulkText(serializeBulkParameters(parameters))
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
                <Input placeholder="值或 {{变量}}" />
              </Form.Item>
            </>
          )}
        />
      )}
    </Form.List>
  )
}

function HeaderFields({
  redactionMode,
  onProgrammaticChange,
}: {
  redactionMode: BulkRedactionMode
  onProgrammaticChange: () => void
}) {
  const form = Form.useFormInstance<WorkbenchFields>()
  const [bulkText, setBulkText] = useState<string | null>(null)
  const [bulkErrors, setBulkErrors] = useState<string[]>([])
  const [originalHeaders, setOriginalHeaders] = useState<KeyValueField[]>([])
  if (bulkText !== null) {
    return (
      <BulkEditor
        label="Headers"
        text={bulkText}
        errors={bulkErrors}
        help={
          redactionMode === 'on'
            ? '每行使用“Header 名: 值”；# 开头的注释行不会保存，敏感值请使用 {{secret.NAME}}。'
            : '每行使用“Header 名: 值”；# 开头的注释行不会保存，当前项目脱敏已关闭，输入值会按原样保留。'
        }
        onChange={setBulkText}
        onCancel={() => {
          setBulkText(null)
          setBulkErrors([])
        }}
        onApply={() => {
          const parsed = parseBulkHeaders(bulkText, originalHeaders, redactionMode)
          setBulkErrors(parsed.errors)
          if (parsed.errors.length) return
          form.setFieldValue('headers', parsed.values)
          onProgrammaticChange()
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
            const headers = (form.getFieldValue('headers') ?? []) as KeyValueField[]
            setOriginalHeaders(headers)
            setBulkText(serializeBulkHeaders(headers, redactionMode))
            setBulkErrors([])
          }}
          render={(field) => (
            <>
              <Form.Item name={[field.name, 'name']} rules={[{ required: true }]}>
                <Input placeholder="名称" />
              </Form.Item>
              <Form.Item name={[field.name, 'value']}>
                <Input
                  type={redactionMode === 'on' ? 'password' : 'text'}
                  placeholder="值或 {{secret.NAME}}"
                />
              </Form.Item>
            </>
          )}
        />
      )}
    </Form.List>
  )
}

function KeyValueFields({
  name,
  redactionMode,
}: {
  name: 'auth_config'
  redactionMode: BulkRedactionMode
}) {
  return (
    <Form.List name={name}>
      {(fields, { add, remove }) => (
        <DynamicFields
          fields={fields}
          onAdd={() => add({ name: '', value: '' })}
          onRemove={remove}
          render={(field) => (
            <>
              <Form.Item name={[field.name, 'name']} rules={[{ required: true }]}>
                <Input placeholder="名称" />
              </Form.Item>
              <Form.Item name={[field.name, 'value']}>
                <Input
                  type={redactionMode === 'on' ? 'password' : 'text'}
                  placeholder="值或 {{secret.NAME}}"
                />
              </Form.Item>
            </>
          )}
        />
      )}
    </Form.List>
  )
}

function AuthFields({ redactionMode }: { redactionMode: BulkRedactionMode }) {
  return (
    <>
      <Form.Item name="auth_kind" label="认证方式">
        <Select
          options={[
            { value: 'none', label: '无认证' },
            { value: 'bearer', label: 'Bearer Token' },
            { value: 'basic', label: 'Basic Auth' },
            { value: 'api_key', label: 'API Key' },
          ]}
        />
      </Form.Item>
      <Typography.Paragraph type="secondary">
        Bearer 使用 token；Basic 使用 username/password；API Key 使用 name/value/in。
      </Typography.Paragraph>
      <KeyValueFields name="auth_config" redactionMode={redactionMode} />
    </>
  )
}

function ExtractionFields() {
  return (
    <Form.List name="extraction_rules">
      {(fields, { add, remove }) => (
        <DynamicFields
          fields={fields}
          onAdd={() => add({ name: '', kind: 'jsonpath', expression: '' })}
          onRemove={remove}
          render={(field) => (
            <>
              <Form.Item name={[field.name, 'name']} rules={[{ required: true }]}>
                <Input placeholder="变量名" />
              </Form.Item>
              <Form.Item name={[field.name, 'kind']}>
                <Select
                  className="role-select"
                  options={['jsonpath', 'jmespath', 'header'].map((value) => ({
                    value,
                    label: value,
                  }))}
                />
              </Form.Item>
              <Form.Item name={[field.name, 'expression']} rules={[{ required: true }]}>
                <Input placeholder="$.data.token" />
              </Form.Item>
            </>
          )}
        />
      )}
    </Form.List>
  )
}

function AssertionFields() {
  return (
    <Form.List name="assertions">
      {(fields, { add, remove }) => (
        <DynamicFields
          fields={fields}
          onAdd={() =>
            add({ kind: 'status_code', operator: 'equals', target: null, expected_text: '200' })
          }
          onRemove={remove}
          render={(field) => (
            <>
              <Form.Item name={[field.name, 'kind']}>
                <Select
                  className="assertion-select"
                  options={[
                    'status_code',
                    'response_time',
                    'header',
                    'jsonpath',
                    'jmespath',
                    'json_schema',
                  ].map((value) => ({ value, label: value }))}
                />
              </Form.Item>
              <Form.Item name={[field.name, 'operator']}>
                <Select
                  className="assertion-select"
                  options={[
                    'equals',
                    'not_equals',
                    'contains',
                    'exists',
                    'less_than',
                    'greater_than',
                  ].map((value) => ({ value, label: value }))}
                />
              </Form.Item>
              <Form.Item name={[field.name, 'target']}>
                <Input placeholder="目标（可选）" />
              </Form.Item>
              <Form.Item name={[field.name, 'expected_text']}>
                <Input placeholder="预期值（JSON 或文本）" />
              </Form.Item>
            </>
          )}
        />
      )}
    </Form.List>
  )
}

function toFields(version: ApiVersion): WorkbenchFields {
  return {
    method: version.method,
    path: version.path,
    query_parameters: version.query_parameters,
    headers: toKeyValues(version.headers),
    ...toBodyFields(version),
    auth_kind: version.auth_kind,
    auth_config: toKeyValues(version.auth_config),
    extraction_rules: version.extraction_rules,
    assertions: version.assertions.map((assertion) => ({
      kind: assertion.kind,
      operator: assertion.operator,
      target: assertion.target,
      expected_text: JSON.stringify(assertion.expected),
    })),
  }
}

function toInput(values: WorkbenchFields): ApiVersionInput {
  const body = toBodyInput(values)
  return {
    method: values.method,
    path: values.path,
    query_parameters: values.query_parameters ?? [],
    headers: toRecord(values.headers),
    ...body,
    auth: { kind: values.auth_kind, values: toRecord(values.auth_config) },
    extraction_rules: values.extraction_rules ?? [],
    assertions: (values.assertions ?? []).map((assertion) => ({
      kind: assertion.kind,
      operator: assertion.operator,
      target: assertion.target || null,
      expected: parseExpected(assertion.expected_text),
    })),
  }
}

function toKeyValues(value: Record<string, string>): KeyValueField[] {
  return Object.entries(value).map(([name, fieldValue]) => ({ name, value: fieldValue }))
}

function toRecord(values: KeyValueField[] = []): Record<string, string> {
  return Object.fromEntries(
    values.filter((item) => item.name).map((item) => [item.name, item.value]),
  )
}

function parseExpected(value: string): unknown {
  if (!value?.trim()) return null
  try {
    return JSON.parse(value)
  } catch {
    return value
  }
}
