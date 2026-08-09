import { Form, Input, Modal, Select } from 'antd'

import type { ApiDefinition } from '../../lib/api'
import type { CreateWorkflowInput } from './use-workflows'

type Props = {
  open: boolean
  submitting: boolean
  apis: ApiDefinition[]
  onClose: () => void
  onCreate: (input: CreateWorkflowInput) => Promise<void>
}

export default function CreateWorkflowDialog({ open, submitting, apis, onClose, onCreate }: Props) {
  const [form] = Form.useForm<CreateWorkflowInput>()
  return (
    <Modal
      open={open}
      title="新建工作流草稿"
      okText="创建草稿"
      cancelText="取消"
      confirmLoading={submitting}
      onCancel={onClose}
      onOk={() => void submit(form, onCreate)}
      destroyOnHidden
    >
      <Form form={form} layout="vertical" preserve={false}>
        <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
          <Input maxLength={200} placeholder="例如：用户登录流程" />
        </Form.Item>
        <Form.Item name="description" label="说明" initialValue="">
          <Input.TextArea maxLength={4000} rows={2} />
        </Form.Item>
        <Form.Item
          name="apiId"
          label="初始 API 节点"
          rules={[{ required: true, message: '请选择接口' }]}
        >
          <Select
            placeholder="选择一个接口，创建 Start → API → End 草稿"
            options={apis.map((api) => ({ value: api.id, label: api.name }))}
          />
        </Form.Item>
      </Form>
    </Modal>
  )
}

async function submit(
  form: ReturnType<typeof Form.useForm<CreateWorkflowInput>>[0],
  onCreate: (input: CreateWorkflowInput) => Promise<void>,
) {
  const value = await form.validateFields()
  await onCreate(value)
  form.resetFields()
}
