import { Form, Input, Modal, Select } from 'antd'

import type {
  AuthKind,
  BodyKind,
  CreateApiInput,
  CreateEnvironmentInput,
  CreateProjectInput,
  HttpMethod,
} from './api-service'
import type { Artifact } from '../../lib/api'
import CreateProjectDialog from '../projects/CreateProjectDialog'

type DialogState = 'project' | 'environment' | 'api' | null

type DialogProps = {
  open: DialogState
  submitting: boolean
  onClose: () => void
  onCreateProject: (input: CreateProjectInput) => Promise<void>
  onCreateEnvironment: (input: CreateEnvironmentInput) => Promise<void>
  onCreateApi: (input: CreateApiInput) => Promise<void>
  artifacts?: Artifact[]
}

type EnvironmentFields = { name: string; baseUrl: string }
type ApiFields = {
  name: string
  description?: string
  method: HttpMethod
  path: string
  bodyKind: BodyKind
  body?: string
  fileId?: string
  authKind: AuthKind
  bearerToken?: string
  basicUsername?: string
  basicPassword?: string
  apiKeyName?: string
  apiKeyValue?: string
  apiKeyLocation?: 'header' | 'query'
}

export default function CreateDialogs(props: DialogProps) {
  return (
    <>
      <CreateProjectDialog
        open={props.open === 'project'}
        submitting={props.submitting}
        onClose={props.onClose}
        onCreate={props.onCreateProject}
      />
      <EnvironmentDialog {...props} />
      <ApiDialog {...props} />
    </>
  )
}

function EnvironmentDialog({ open, submitting, onClose, onCreateEnvironment }: DialogProps) {
  const [form] = Form.useForm<EnvironmentFields>()
  async function submit(values: EnvironmentFields) {
    await onCreateEnvironment({
      name: values.name,
      base_url: values.baseUrl,
      variables: {},
      headers: {},
    })
  }
  return (
    <Modal
      title="新建环境"
      open={open === 'environment'}
      confirmLoading={submitting}
      onCancel={onClose}
      onOk={() => form.submit()}
      destroyOnHidden
    >
      <Form form={form} layout="vertical" onFinish={submit}>
        <Form.Item name="name" label="环境名称" rules={[{ required: true }]}>
          <Input placeholder="例如：本地测试" />
        </Form.Item>
        <Form.Item
          name="baseUrl"
          label="基础 URL"
          rules={[{ required: true, type: 'url', message: '请输入有效 URL' }]}
        >
          <Input placeholder="http://mock-target:8080" />
        </Form.Item>
      </Form>
    </Modal>
  )
}

function ApiDialog({ open, submitting, onClose, onCreateApi, artifacts }: DialogProps) {
  const [form] = Form.useForm<ApiFields>()
  async function submit(values: ApiFields) {
    await onCreateApi({
      name: values.name,
      description: values.description ?? '',
      method: values.method,
      path: values.path,
      body_kind: values.bodyKind,
      body: buildBody(values),
      auth: buildAuth(values),
    })
  }
  return (
    <Modal
      title="新建接口"
      width={620}
      open={open === 'api'}
      confirmLoading={submitting}
      onCancel={onClose}
      onOk={() => form.submit()}
      destroyOnHidden
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={{
          method: 'GET',
          description: '',
          bodyKind: 'none',
          body: '',
          authKind: 'none',
          bearerToken: '{{secret.BEARER_TOKEN}}',
          basicUsername: '{{secret.BASIC_USERNAME}}',
          basicPassword: '{{secret.BASIC_PASSWORD}}',
          apiKeyName: 'X-API-Key',
          apiKeyValue: '{{secret.API_KEY}}',
          apiKeyLocation: 'header',
        }}
        onFinish={submit}
      >
        <Form.Item name="name" label="接口名称" rules={[{ required: true }]}>
          <Input placeholder="例如：查询当前用户" />
        </Form.Item>
        <div className="request-line">
          <Form.Item name="method" label="方法" rules={[{ required: true }]}>
            <Select
              options={['GET', 'POST', 'PUT', 'PATCH', 'DELETE'].map((value) => ({
                value,
                label: value,
              }))}
            />
          </Form.Item>
          <Form.Item name="path" label="请求路径" rules={[{ required: true }]}>
            <Input placeholder="/users/me" />
          </Form.Item>
        </div>
        <Form.Item name="description" label="说明">
          <Input />
        </Form.Item>
        <Form.Item name="bodyKind" label="请求体类型">
          <Select
            options={[
              { value: 'none', label: '无请求体' },
              { value: 'json', label: 'JSON' },
              { value: 'multipart', label: 'multipart 文件上传' },
            ]}
          />
        </Form.Item>
        <Form.Item noStyle shouldUpdate={(before, after) => before.bodyKind !== after.bodyKind}>
          {({ getFieldValue }) =>
            getFieldValue('bodyKind') === 'json' ? (
              <Form.Item name="body" label="JSON Body" rules={[{ validator: validateJson }]}>
                <Input.TextArea
                  rows={6}
                  className="code-input"
                  placeholder={'{\n  "name": "demo"\n}'}
                />
              </Form.Item>
            ) : getFieldValue('bodyKind') === 'multipart' ? (
              <Form.Item name="fileId" label="文件" rules={[{ required: true }]}>
                <Select
                  placeholder="请先在文件仓库上传文件"
                  options={(artifacts ?? []).map((artifact) => ({
                    value: artifact.id,
                    label: `${artifact.filename} (${artifact.size_bytes} B)`,
                  }))}
                />
              </Form.Item>
            ) : null
          }
        </Form.Item>
        <Form.Item name="authKind" label="认证方式">
          <Select
            options={[
              { value: 'none', label: '无认证' },
              { value: 'bearer', label: 'Bearer Token' },
              { value: 'basic', label: 'Basic Auth' },
              { value: 'api_key', label: 'API Key' },
            ]}
          />
        </Form.Item>
        <AuthFields />
      </Form>
    </Modal>
  )
}

function AuthFields() {
  return (
    <Form.Item noStyle shouldUpdate={(before, after) => before.authKind !== after.authKind}>
      {({ getFieldValue }) => {
        const kind = getFieldValue('authKind') as AuthKind
        if (kind === 'bearer') {
          return (
            <Form.Item name="bearerToken" label="Token 或 Secret 变量" rules={[{ required: true }]}>
              <Input placeholder="{{secret.BEARER_TOKEN}}" />
            </Form.Item>
          )
        }
        if (kind === 'basic') {
          return (
            <div className="request-line">
              <Form.Item name="basicUsername" label="用户名" rules={[{ required: true }]}>
                <Input />
              </Form.Item>
              <Form.Item
                name="basicPassword"
                label="密码或 Secret 变量"
                rules={[{ required: true }]}
              >
                <Input.Password />
              </Form.Item>
            </div>
          )
        }
        if (kind === 'api_key') {
          return (
            <>
              <div className="request-line">
                <Form.Item name="apiKeyName" label="参数名" rules={[{ required: true }]}>
                  <Input />
                </Form.Item>
                <Form.Item name="apiKeyLocation" label="位置">
                  <Select
                    options={[
                      { value: 'header', label: 'Header' },
                      { value: 'query', label: 'Query' },
                    ]}
                  />
                </Form.Item>
              </div>
              <Form.Item name="apiKeyValue" label="值或 Secret 变量" rules={[{ required: true }]}>
                <Input.Password />
              </Form.Item>
            </>
          )
        }
        return null
      }}
    </Form.Item>
  )
}

function buildBody(values: ApiFields): unknown {
  if (values.bodyKind === 'json') return parseBody(values.body)
  if (values.bodyKind === 'multipart') {
    return {
      fields: {},
      files: [{ field: 'file', artifact_id: values.fileId }],
    }
  }
  return null
}

function buildAuth(values: ApiFields): CreateApiInput['auth'] {
  if (values.authKind === 'bearer') {
    return { kind: 'bearer', values: { token: values.bearerToken ?? '' } }
  }
  if (values.authKind === 'basic') {
    return {
      kind: 'basic',
      values: {
        username: values.basicUsername ?? '',
        password: values.basicPassword ?? '',
      },
    }
  }
  if (values.authKind === 'api_key') {
    return {
      kind: 'api_key',
      values: {
        name: values.apiKeyName ?? 'X-API-Key',
        value: values.apiKeyValue ?? '',
        in: values.apiKeyLocation ?? 'header',
      },
    }
  }
  return { kind: 'none', values: {} }
}

function parseBody(value?: string): unknown {
  return value?.trim() ? JSON.parse(value) : null
}

function validateJson(_: unknown, value?: string) {
  if (!value?.trim()) return Promise.resolve()
  try {
    JSON.parse(value)
    return Promise.resolve()
  } catch {
    return Promise.reject(new Error('请输入有效 JSON'))
  }
}
