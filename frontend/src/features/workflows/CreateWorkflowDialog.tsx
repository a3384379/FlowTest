import { Alert, Form, Input, Modal, Select } from 'antd'

import type { ApiDefinition } from '../../lib/api'
import type { CreateWorkflowInput } from './use-workflows'
import { WORKFLOW_TEMPLATES } from './workflow-templates'

type Props = {
  open: boolean
  submitting: boolean
  apis: ApiDefinition[]
  onClose: () => void
  onCreate: (input: CreateWorkflowInput) => Promise<void>
}

export default function CreateWorkflowDialog({ open, submitting, apis, onClose, onCreate }: Props) {
  const [form] = Form.useForm<CreateWorkflowInput>()
  const template = Form.useWatch('template', form)
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
        <Form.Item name="template" label="起始模板" initialValue="linear">
          <Select
            options={WORKFLOW_TEMPLATES.map(({ value, label, help }) => ({
              value,
              label: `${label} · ${help}`,
            }))}
          />
        </Form.Item>
        <Form.Item
          name="apiId"
          label={template === 'async_poll' ? '状态查询 API（GET）' : '初始 API 节点'}
          rules={[{ required: true, message: '请选择接口' }]}
        >
          <Select
            placeholder={template === 'async_poll' ? '选择只读状态查询接口' : '选择初始接口'}
            options={apis.map((api) => ({ value: api.id, label: api.name }))}
          />
        </Form.Item>
        {template === 'async_poll' && (
          <>
            <Form.Item
              name="submitApiId"
              label="任务提交 API（POST）"
              preserve={false}
              dependencies={['apiId']}
              rules={[
                { required: true, message: '请选择任务提交接口' },
                ({ getFieldValue }) => ({
                  validator(_, value) {
                    return value && value === getFieldValue('apiId')
                      ? Promise.reject(new Error('提交与查询必须使用不同接口'))
                      : Promise.resolve()
                  },
                }),
              ]}
            >
              <Select
                placeholder="选择只提交一次的接口"
                options={apis.map((api) => ({ value: api.id, label: api.name }))}
              />
            </Form.Item>
            <Alert
              type="info"
              showIcon
              title="模板从提交响应 body.taskId 绑定查询参数 taskId，并按查询响应 body.status 判断 SUCCESS / FAILED；创建后请先检查接口契约。"
            />
          </>
        )}
        {template === 'try_finally' && (
          <Alert
            type="warning"
            showIcon
            title="此模板的 Finally 仅含占位等待，不会清理外部资源。发布前请配置资源句柄查证和真实清理步骤。"
          />
        )}
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
