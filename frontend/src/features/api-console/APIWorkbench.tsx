import { DeleteOutlined, PlusOutlined, SaveOutlined } from '@ant-design/icons'
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
import { useEffect, useState } from 'react'

import type { ApiVersionInput } from './api-service'
import type { ApiDetail, ApiVersion } from '../../lib/api'

type APIWorkbenchProps = {
  detail?: ApiDetail
  loading: boolean
  saving: boolean
  previewing: boolean
  onSave: (input: ApiVersionInput) => Promise<ApiVersion>
  onPreview: () => Promise<unknown>
}

type KeyValueField = { name: string; value: string }
type WorkbenchFields = {
  method: ApiVersion['method']
  path: string
  query_parameters: Array<KeyValueField & { enabled: boolean }>
  headers: KeyValueField[]
  body_kind: ApiVersion['body_kind']
  body_text: string
  auth_kind: ApiVersion['auth_kind']
  auth_config: KeyValueField[]
  extraction_rules: ApiVersion['extraction_rules']
  assertions: Array<Omit<ApiVersion['assertions'][number], 'expected'> & { expected_text: string }>
}

export default function APIWorkbench(props: APIWorkbenchProps) {
  const [form] = Form.useForm<WorkbenchFields>()
  const [preview, setPreview] = useState<unknown>(null)
  useEffect(() => {
    if (props.detail) form.setFieldsValue(toFields(props.detail.version))
  }, [form, props.detail])
  if (!props.detail && !props.loading) {
    return <Empty description="请选择接口后进行持续编辑" />
  }
  return (
    <Card
      loading={props.loading}
      title={
        <Space>
          <span>{props.detail?.definition.name ?? '接口工作台'}</span>
          {props.detail && <Tag color="blue">v{props.detail.version.version}</Tag>}
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
      <Form form={form} layout="vertical" onFinish={(values) => props.onSave(toInput(values))}>
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
          items={[
            { key: 'params', label: 'Params', children: <ParameterFields />, forceRender: true },
            {
              key: 'headers',
              label: 'Headers',
              children: <KeyValueFields name="headers" />,
              forceRender: true,
            },
            { key: 'auth', label: 'Auth', children: <AuthFields />, forceRender: true },
            { key: 'body', label: 'Body', children: <BodyFields />, forceRender: true },
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
        title="最终请求预览（Secret 已脱敏）"
        open={preview !== null}
        footer={null}
        onCancel={() => setPreview(null)}
        width={760}
      >
        <pre className="preview-code">{JSON.stringify(preview, null, 2)}</pre>
      </Modal>
    </Card>
  )
}

function ParameterFields() {
  return (
    <Form.List name="query_parameters">
      {(fields, { add, remove }) => (
        <DynamicFields
          fields={fields}
          onAdd={() => add({ enabled: true, name: '', value: '' })}
          onRemove={remove}
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

function KeyValueFields({ name }: { name: 'headers' | 'auth_config' }) {
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
                <Input.Password placeholder="值或 {{secret.NAME}}" visibilityToggle={false} />
              </Form.Item>
            </>
          )}
        />
      )}
    </Form.List>
  )
}

function AuthFields() {
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
      <KeyValueFields name="auth_config" />
    </>
  )
}

function BodyFields() {
  return (
    <>
      <Form.Item name="body_kind" label="Body 类型">
        <Select
          options={[
            { value: 'none', label: 'none' },
            { value: 'json', label: 'JSON' },
            { value: 'raw', label: 'raw' },
            { value: 'form', label: 'form' },
            { value: 'multipart', label: 'multipart' },
          ]}
        />
      </Form.Item>
      <Form.Item name="body_text" label="Body" rules={[bodyRule]}>
        <Input.TextArea rows={12} className="code-input" placeholder={'{\n  "name": "demo"\n}'} />
      </Form.Item>
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

type DynamicField = { key: number; name: number }

function DynamicFields({
  fields,
  onAdd,
  onRemove,
  render,
}: {
  fields: DynamicField[]
  onAdd: () => void
  onRemove: (index: number) => void
  render: (field: DynamicField) => React.ReactNode
}) {
  return (
    <Space orientation="vertical" className="full-width">
      {fields.map((field) => (
        <div className="workbench-dynamic-row" key={field.key}>
          {render(field)}
          <Button
            type="text"
            danger
            icon={<DeleteOutlined />}
            aria-label="删除配置行"
            onClick={() => onRemove(field.name)}
          />
        </div>
      ))}
      <Button type="dashed" icon={<PlusOutlined />} onClick={onAdd}>
        添加一行
      </Button>
    </Space>
  )
}

const bodyRule = {
  validator: (_: unknown, value: string) => {
    if (!value?.trim()) return Promise.resolve()
    try {
      JSON.parse(value)
      return Promise.resolve()
    } catch {
      return Promise.reject(new Error('Body 请输入有效 JSON'))
    }
  },
}

function toFields(version: ApiVersion): WorkbenchFields {
  return {
    method: version.method,
    path: version.path,
    query_parameters: version.query_parameters,
    headers: toKeyValues(version.headers),
    body_kind: version.body_kind,
    body_text: version.body === null ? '' : JSON.stringify(version.body, null, 2),
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
  return {
    method: values.method,
    path: values.path,
    query_parameters: values.query_parameters ?? [],
    headers: toRecord(values.headers),
    body_kind: values.body_kind,
    body: values.body_text?.trim() ? JSON.parse(values.body_text) : null,
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
