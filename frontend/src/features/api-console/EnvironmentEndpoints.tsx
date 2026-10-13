import { EditOutlined, PlusOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  App,
  Button,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
} from 'antd'
import { useState } from 'react'

import QueryFailureNotice from '../../components/QueryFailureNotice'
import { apiErrorMessage, type ServiceEndpoint } from '../../lib/api'
import {
  createServiceEndpoint,
  listRequestServices,
  listServiceEndpoints,
  updateServiceEndpoint,
  type CreateEndpointInput,
} from '../service-targets/service-target-service'
import { invalidateRequestTargets } from '../service-targets/request-target-cache'

type Props = { projectId: string; environmentId: string; editable: boolean }
type EndpointForm = { service_id: string; variant: string; base_url: string; enabled: boolean }
export default function EnvironmentEndpoints(props: Props) {
  const [editing, setEditing] = useState<ServiceEndpoint | 'new' | null>(null)
  const services = useQuery({
    queryKey: ['request-services', props.projectId],
    queryFn: () => listRequestServices(props.projectId),
  })
  const endpoints = useQuery({
    queryKey: ['service-endpoints', props.projectId, props.environmentId],
    queryFn: () => listServiceEndpoints(props.projectId, props.environmentId),
  })
  return (
    <div>
      <QueryFailureNotice queries={[services, endpoints]} />
      <Typography.Paragraph type="secondary">
        各模块可配置不同服务地址及 Variant，发送时由后端解析最终请求地址。
      </Typography.Paragraph>
      <Button
        icon={<PlusOutlined />}
        disabled={!props.editable || services.isPending || services.isError}
        onClick={() => setEditing('new')}
      >
        添加服务地址
      </Button>
      <Table<ServiceEndpoint>
        size="small"
        rowKey="id"
        dataSource={endpoints.data ?? []}
        loading={endpoints.isFetching}
        pagination={false}
        scroll={{ x: 480 }}
        columns={[
          {
            title: '服务 / Variant',
            render: (_, item) => (
              <>
                <Typography.Text>
                  {services.data?.find((service) => service.id === item.service_id)?.name ??
                    item.service_id}
                </Typography.Text>
                <Tag>{item.variant}</Tag>
              </>
            ),
          },
          {
            title: '地址',
            dataIndex: 'base_url',
            render: (url: string) => (
              <Typography.Text className="environment-endpoint-url">{url}</Typography.Text>
            ),
          },
          {
            title: '状态',
            render: (_, item) => (
              <Tag color={item.enabled ? 'green' : undefined}>{item.enabled ? '启用' : '停用'}</Tag>
            ),
          },
          {
            title: '操作',
            render: (_, item) => (
              <Button
                size="small"
                icon={<EditOutlined />}
                disabled={!props.editable}
                onClick={() => setEditing(item)}
              >
                编辑
              </Button>
            ),
          },
        ]}
      />
      {editing && props.editable && (
        <EndpointEditor
          key={editing === 'new' ? 'new' : editing.id}
          {...props}
          endpoint={editing === 'new' ? undefined : editing}
          services={services.data ?? []}
          onClose={() => setEditing(null)}
        />
      )}
    </div>
  )
}

function EndpointEditor({
  projectId,
  environmentId,
  endpoint,
  services,
  onClose,
}: Props & {
  endpoint?: ServiceEndpoint
  services: Array<{ id: string; name: string; enabled: boolean }>
  onClose: () => void
}) {
  const [form] = Form.useForm<EndpointForm>()
  const { message, modal } = App.useApp()
  const client = useQueryClient()
  const [dirty, setDirty] = useState(false)
  const mutation = useMutation({
    mutationFn: (input: CreateEndpointInput) =>
      endpoint
        ? updateServiceEndpoint(projectId, endpoint.id, {
            variant: input.variant,
            base_url: input.base_url,
            enabled: input.enabled,
          })
        : createServiceEndpoint(projectId, environmentId, input),
    onSuccess: async () => {
      await invalidateRequestTargets(client, projectId)
      onClose()
      void message.success('服务地址已保存')
    },
    onError: (error) => void message.error(apiErrorMessage(error)),
  })
  function close() {
    if (mutation.isPending) return
    if (!dirty) {
      onClose()
      return
    }
    modal.confirm({
      title: '服务地址尚未保存',
      content: '关闭会丢弃当前修改。',
      okText: '丢弃修改',
      cancelText: '继续编辑',
      onOk: onClose,
    })
  }
  return (
    <Modal
      open
      title={endpoint ? '编辑服务地址' : '添加服务地址'}
      okText="保存地址"
      cancelText="取消"
      onCancel={close}
      confirmLoading={mutation.isPending}
      onOk={() => form.submit()}
      closable={!mutation.isPending}
      maskClosable={!mutation.isPending}
      keyboard={!mutation.isPending}
    >
      <div onSubmit={(event) => event.stopPropagation()}>
        <Form
          form={form}
          name="environment-endpoint"
          layout="vertical"
          disabled={mutation.isPending}
          initialValues={endpoint ?? { variant: 'default', enabled: true }}
          onValuesChange={() => setDirty(true)}
          onFinish={(values) => mutation.mutate(values)}
        >
          <Form.Item
            name="service_id"
            label="服务"
            rules={[{ required: true, message: '请选择服务' }]}
          >
            <Select
              aria-label="地址所属服务"
              disabled={Boolean(endpoint) || mutation.isPending}
              options={services.map((item) => ({
                value: item.id,
                label: item.name,
                disabled: !item.enabled,
              }))}
            />
          </Form.Item>
          <Form.Item
            name="variant"
            label="地址版本（Variant）"
            rules={[{ required: true, whitespace: true, max: 80, message: '请输入地址版本' }]}
          >
            <Input />
          </Form.Item>
          <Form.Item
            name="base_url"
            label="服务地址"
            rules={[{ required: true, message: '请输入完整地址' }, { validator: validateAddress }]}
          >
            <Input />
          </Form.Item>
          <Form.Item name="enabled" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Space>
            <Typography.Text type="secondary">
              编辑地址会保留现有请求头、变量、密钥引用、超时与 TLS 配置。
            </Typography.Text>
          </Space>
        </Form>
      </div>
    </Modal>
  )
}

async function validateAddress(_: unknown, value: string) {
  if (!value) return
  try {
    const parsed = new URL(value)
    if (!['http:', 'https:'].includes(parsed.protocol) || !parsed.hostname) throw new Error()
  } catch {
    throw new Error('请输入完整的 HTTP 或 HTTPS 地址')
  }
}
