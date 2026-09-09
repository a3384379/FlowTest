import { DeleteOutlined, SaveOutlined } from '@ant-design/icons'
import { Button, Drawer, Form, Input, Popconfirm, Space, Typography } from 'antd'
import { useEffect } from 'react'

import type { Environment } from '../../lib/api'
import type { CreateEnvironmentInput } from './api-service'

type EnvironmentForm = {
  name: string
  base_url: string
  variables: string
  headers: string
}

type Props = {
  open: boolean
  environment?: Environment
  saving: boolean
  deleting: boolean
  onClose: () => void
  onSave: (input: Partial<CreateEnvironmentInput>) => Promise<void>
  onDelete: () => Promise<void>
}

export default function EnvironmentManager({
  open,
  environment,
  saving,
  deleting,
  onClose,
  onSave,
  onDelete,
}: Props) {
  const [form] = Form.useForm<EnvironmentForm>()
  useEffect(() => {
    if (!environment) return
    form.setFieldsValue({
      name: environment.name,
      base_url: environment.base_url,
      variables: JSON.stringify(environment.variables, null, 2),
      headers: JSON.stringify(environment.headers, null, 2),
    })
  }, [environment, form])

  async function submit(values: EnvironmentForm) {
    let variables: Record<string, string>
    let headers: Record<string, string>
    try {
      variables = parseMap(values.variables, '变量')
      headers = parseMap(values.headers, '请求头')
    } catch (error) {
      const message = String(error)
      form.setFields([
        { name: 'variables', errors: [message] },
        { name: 'headers', errors: [message] },
      ])
      return
    }
    await onSave({ name: values.name, base_url: values.base_url, variables, headers })
  }

  return (
    <Drawer
      title="管理环境"
      open={open}
      onClose={onClose}
      width={440}
      destroyOnClose={false}
      extra={
        environment && (
          <Popconfirm
            title="删除环境？"
            description="历史执行和快照会保留，环境将不再用于新执行。"
            okText="删除"
            cancelText="取消"
            onConfirm={() => void onDelete()}
          >
            <Button danger icon={<DeleteOutlined />} loading={deleting}>
              删除
            </Button>
          </Popconfirm>
        )
      }
    >
      {!environment ? (
        <Typography.Text type="secondary">请选择环境后管理其配置。</Typography.Text>
      ) : (
        <Form form={form} layout="vertical" onFinish={(values) => void submit(values)}>
          <Form.Item
            name="name"
            label="名称"
            rules={[{ required: true, message: '请输入环境名称' }]}
          >
            <Input />
          </Form.Item>
          <Form.Item
            name="base_url"
            label="地址"
            rules={[{ required: true, message: '请输入环境地址' }]}
          >
            <Input placeholder="https://example.test" />
          </Form.Item>
          <Form.Item name="variables" label="变量 JSON">
            <Input.TextArea autoSize={{ minRows: 4, maxRows: 8 }} />
          </Form.Item>
          <Form.Item name="headers" label="请求头 JSON">
            <Input.TextArea autoSize={{ minRows: 4, maxRows: 8 }} />
          </Form.Item>
          <Space>
            <Button onClick={onClose}>取消</Button>
            <Button type="primary" htmlType="submit" icon={<SaveOutlined />} loading={saving}>
              保存配置
            </Button>
          </Space>
        </Form>
      )}
    </Drawer>
  )
}

function parseMap(value: string, label: string): Record<string, string> {
  const parsed: unknown = JSON.parse(value || '{}')
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error(`${label}必须是 JSON 对象`)
  }
  const entries = Object.entries(parsed as Record<string, unknown>)
  if (entries.some(([, item]) => typeof item !== 'string')) {
    throw new Error(`${label}的值必须是字符串`)
  }
  return Object.fromEntries(entries) as Record<string, string>
}
