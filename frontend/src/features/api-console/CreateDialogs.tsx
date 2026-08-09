import { Form, Input, Modal, Select } from 'antd'

import type {
  CreateApiInput,
  CreateEnvironmentInput,
  CreateProjectInput,
  HttpMethod,
} from './api-service'

type DialogState = 'project' | 'environment' | 'api' | null

type DialogProps = {
  open: DialogState
  submitting: boolean
  onClose: () => void
  onCreateProject: (input: CreateProjectInput) => Promise<void>
  onCreateEnvironment: (input: CreateEnvironmentInput) => Promise<void>
  onCreateApi: (input: CreateApiInput) => Promise<void>
}

type EnvironmentFields = { name: string; baseUrl: string }
type ApiFields = {
  name: string
  description?: string
  method: HttpMethod
  path: string
  body?: string
}

export default function CreateDialogs(props: DialogProps) {
  return (
    <>
      <ProjectDialog {...props} />
      <EnvironmentDialog {...props} />
      <ApiDialog {...props} />
    </>
  )
}

function ProjectDialog({ open, submitting, onClose, onCreateProject }: DialogProps) {
  const [form] = Form.useForm<CreateProjectInput>()
  return (
    <Modal
      title="新建项目"
      open={open === 'project'}
      confirmLoading={submitting}
      onCancel={onClose}
      onOk={() => form.submit()}
      destroyOnHidden
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={{ description: '' }}
        onFinish={onCreateProject}
      >
        <Form.Item name="name" label="项目名称" rules={[{ required: true }]}>
          <Input placeholder="例如：订单服务" />
        </Form.Item>
        <Form.Item name="description" label="项目说明">
          <Input.TextArea rows={3} />
        </Form.Item>
      </Form>
    </Modal>
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

function ApiDialog({ open, submitting, onClose, onCreateApi }: DialogProps) {
  const [form] = Form.useForm<ApiFields>()
  async function submit(values: ApiFields) {
    await onCreateApi({
      name: values.name,
      description: values.description ?? '',
      method: values.method,
      path: values.path,
      body: parseBody(values.body),
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
        initialValues={{ method: 'GET', description: '', body: '' }}
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
        <Form.Item name="body" label="JSON Body（可选）" rules={[{ validator: validateJson }]}>
          <Input.TextArea rows={7} className="code-input" placeholder={'{\n  "name": "demo"\n}'} />
        </Form.Item>
      </Form>
    </Modal>
  )
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
