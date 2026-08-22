import { Form, Input, Modal } from 'antd'

import type { CreateProjectInput } from './project-service'

type CreateProjectDialogProps = {
  open: boolean
  submitting: boolean
  onClose: () => void
  onCreate: (input: CreateProjectInput) => Promise<void>
}

export default function CreateProjectDialog({
  open,
  submitting,
  onClose,
  onCreate,
}: CreateProjectDialogProps) {
  const [form] = Form.useForm<CreateProjectInput>()
  return (
    <Modal
      title="新建项目"
      open={open}
      confirmLoading={submitting}
      onCancel={onClose}
      onOk={() => form.submit()}
      destroyOnHidden
    >
      <Form form={form} layout="vertical" initialValues={{ description: '' }} onFinish={onCreate}>
        <Form.Item
          name="name"
          label="项目名称"
          rules={[{ required: true, message: '请输入项目名称' }]}
        >
          <Input placeholder="例如：订单服务" />
        </Form.Item>
        <Form.Item name="description" label="项目说明">
          <Input.TextArea rows={3} />
        </Form.Item>
      </Form>
    </Modal>
  )
}
