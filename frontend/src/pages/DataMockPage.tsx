import MockRouteWorkspace from '../features/data-sources/MockRouteWorkspace'
import {
  DeleteOutlined,
  LinkOutlined,
  PlusOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  App,
  Button,
  Card,
  Col,
  Form,
  Input,
  InputNumber,
  Popconfirm,
  Row,
  Select,
  Space,
  Switch,
  Table,
  Tabs,
  Tag,
  Typography,
} from 'antd'
import { useState } from 'react'
import { WorkflowResourceReturn } from '../flow/WorkflowResourceNavigation'
import QueryFailureNotice from '../components/QueryFailureNotice'

import {
  createCredential,
  createMockService,
  deleteCredential,
  listCredentials,
  listMockServices,
  updateMockService,
  type CredentialInput,
} from '../features/data-sources/data-source-service'
import { useProjectContext } from '../features/projects/use-project-context'
import { apiErrorMessage, type Credential, type MockService } from '../lib/api'

export default function DataMockPage() {
  const { projectId, currentProject } = useProjectContext()
  if (!projectId || !currentProject) return <Card>请选择项目</Card>
  const canEdit = currentProject.role !== 'viewer'
  return (
    <Space orientation="vertical" className="full-width" size="large">
      <div>
        <Typography.Title level={3}>数据与 Mock</Typography.Title>
        <Typography.Text type="secondary">
          Credential 值仅写入并加密保存；数据节点只执行白名单只读操作，Mock 不执行脚本。
        </Typography.Text>
        <WorkflowResourceReturn projectId={projectId} />
      </div>
      <Tabs
        items={[
          {
            key: 'credentials',
            label: 'Credential',
            children: <CredentialPanel projectId={projectId} canEdit={canEdit} />,
          },
          {
            key: 'mock',
            label: 'Mock 服务',
            children: <MockPanel projectId={projectId} canEdit={canEdit} />,
          },
        ]}
      />
    </Space>
  )
}

export function CredentialPanel({ projectId, canEdit }: { projectId: string; canEdit: boolean }) {
  const [form] = Form.useForm<CredentialInput>()
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const credentials = useQuery({
    queryKey: ['credentials', projectId],
    queryFn: () => listCredentials(projectId),
  })
  const mutation = useMutation({
    mutationFn: (input: CredentialInput) => createCredential(projectId, input),
    onSuccess: async () => {
      form.resetFields()
      await queryClient.invalidateQueries({ queryKey: ['credentials', projectId] })
      void message.success('Credential 已安全保存')
    },
    onError: (error) => void message.error(apiErrorMessage(error)),
  })
  const remove = useMutation({
    mutationFn: deleteCredential,
    onSuccess: async () => queryClient.invalidateQueries({ queryKey: ['credentials', projectId] }),
    onError: (error) => void message.error(apiErrorMessage(error)),
  })
  return (
    <Row gutter={16}>
      {canEdit && (
        <Col xs={24} xl={9}>
          <Card title="新建 Credential" size="small">
            <CredentialForm form={form} pending={mutation.isPending} onFinish={mutation.mutate} />
          </Card>
        </Col>
      )}
      <Col xs={24} xl={canEdit ? 15 : 24}>
        <Card title="Credential 元数据" size="small">
          <QueryFailureNotice queries={[credentials]} />
          <Table
            rowKey="id"
            size="small"
            loading={credentials.isLoading}
            dataSource={credentials.data ?? []}
            pagination={false}
            columns={[
              { title: '名称', dataIndex: 'name' },
              { title: '类型', dataIndex: 'kind', render: credentialKindLabel },
              {
                title: 'Secret 存储',
                dataIndex: 'secret_provider',
                render: (value: Credential['secret_provider']) =>
                  value === 'vault_kv_v2' ? 'Vault KV v2' : '平台加密',
              },
              { title: '目标', render: (_, item) => `${item.host}:${item.port}` },
              { title: '数据库', dataIndex: 'database_name', render: (value) => value || '-' },
              {
                title: 'TLS',
                dataIndex: 'tls_enabled',
                render: (value) => (value ? '开启' : '关闭'),
              },
              {
                title: '操作',
                width: 72,
                render: (_, item: Credential) =>
                  canEdit ? (
                    <Popconfirm
                      title="确认删除该 Credential？"
                      onConfirm={() => remove.mutate(item.id)}
                    >
                      <Button
                        danger
                        type="text"
                        icon={<DeleteOutlined />}
                        aria-label="删除 Credential"
                      />
                    </Popconfirm>
                  ) : null,
              },
            ]}
          />
        </Card>
      </Col>
    </Row>
  )
}

function CredentialForm({
  form,
  pending,
  onFinish,
}: {
  form: ReturnType<typeof Form.useForm<CredentialInput>>[0]
  pending: boolean
  onFinish: (input: CredentialInput) => void
}) {
  const kind = Form.useWatch('kind', form) ?? 'postgresql'
  return (
    <Form
      name="credential"
      form={form}
      layout="vertical"
      initialValues={{
        kind: 'postgresql',
        secret_provider: 'local',
        tls_enabled: true,
        database_name: '',
        username: '',
      }}
      onFinish={onFinish}
    >
      <Form.Item name="name" label="名称" rules={[{ required: true }]}>
        <Input placeholder="订单只读库" />
      </Form.Item>
      <Form.Item name="kind" label="类型" rules={[{ required: true }]}>
        <Select options={credentialKindOptions} />
      </Form.Item>
      <Form.Item
        name="secret_provider"
        label="Secret 存储"
        tooltip="Vault KV v2 需由系统管理员预先配置"
        rules={[{ required: true }]}
      >
        <Select
          options={[
            { value: 'local', label: '平台 AES-256-GCM 加密' },
            { value: 'vault_kv_v2', label: 'Vault KV v2' },
          ]}
        />
      </Form.Item>
      <Space align="start" className="full-width">
        <Form.Item name="host" label="Host" rules={[{ required: true }]}>
          <Input placeholder="db.example.com" />
        </Form.Item>
        <Form.Item name="port" label="Port">
          <InputNumber min={1} max={65535} placeholder={String(defaultPort(kind))} />
        </Form.Item>
      </Space>
      {(kind === 'postgresql' || kind === 'mysql') && (
        <Form.Item name="database_name" label="数据库" rules={[{ required: true }]}>
          <Input />
        </Form.Item>
      )}
      {kind !== 'grpc_mtls' && (
        <Form.Item name="username" label="用户名">
          <Input />
        </Form.Item>
      )}
      <Form.Item
        name="secret"
        label={kind === 'grpc_mtls' ? 'mTLS 材料（JSON）' : '密码/访问密钥'}
        rules={[{ required: true }]}
      >
        {kind === 'grpc_mtls' ? (
          <Input.TextArea
            rows={6}
            placeholder='{"private_key_pem":"...","certificate_chain_pem":"..."}'
          />
        ) : (
          <Input.Password autoComplete="new-password" />
        )}
      </Form.Item>
      <Form.Item name="tls_enabled" label="TLS" valuePropName="checked">
        <Switch />
      </Form.Item>
      <Button
        type="primary"
        htmlType="submit"
        loading={pending}
        icon={<SafetyCertificateOutlined />}
      >
        加密保存
      </Button>
    </Form>
  )
}

export function MockPanel({ projectId, canEdit }: { projectId: string; canEdit: boolean }) {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const services = useQuery({
    queryKey: ['mock-services', projectId],
    queryFn: () => listMockServices(projectId),
  })
  const selected = selectedMockService(services.data, selectedId)
  const createServiceMutation = useMutation({
    mutationFn: (input: { name: string; slug: string; description: string }) =>
      createMockService(projectId, input),
    onSuccess: async (created) => {
      setSelectedId(created.id)
      await queryClient.invalidateQueries({ queryKey: ['mock-services', projectId] })
      void message.success('Mock 服务已创建')
    },
    onError: (error) => void message.error(apiErrorMessage(error)),
  })
  const toggleMutation = useMutation({
    mutationFn: (service: MockService) =>
      updateMockService(projectId, service.id, { is_enabled: !service.is_enabled }),
    onSuccess: async () =>
      queryClient.invalidateQueries({ queryKey: ['mock-services', projectId] }),
    onError: (error) => void message.error(apiErrorMessage(error)),
  })
  return (
    <Space orientation="vertical" className="full-width">
      <QueryFailureNotice queries={[services]} />
      <EditableMockServiceForm
        canEdit={canEdit}
        pending={createServiceMutation.isPending}
        onFinish={createServiceMutation.mutate}
      />
      <Space wrap>
        <Select
          aria-label="Mock 服务"
          className="management-select"
          value={selected?.id}
          options={services.data?.map((item) => ({ value: item.id, label: item.name }))}
          onChange={setSelectedId}
        />
        <MockServiceSummary service={selected} canEdit={canEdit} onToggle={toggleMutation.mutate} />
      </Space>
      <SelectedMockWorkspace projectId={projectId} service={selected} canEdit={canEdit} />
    </Space>
  )
}

function EditableMockServiceForm({
  canEdit,
  pending,
  onFinish,
}: {
  canEdit: boolean
  pending: boolean
  onFinish: (input: { name: string; slug: string; description: string }) => void
}) {
  if (!canEdit) return null
  return <MockServiceForm pending={pending} onFinish={onFinish} />
}

function MockServiceSummary({
  service,
  canEdit,
  onToggle,
}: {
  service: MockService | undefined
  canEdit: boolean
  onToggle: (service: MockService) => void
}) {
  if (!service) return null
  return (
    <>
      <Tag color={service.is_enabled ? 'green' : 'default'}>
        {service.is_enabled ? '已启用' : '已停用'}
      </Tag>
      <Typography.Text copyable>
        <LinkOutlined /> /api/v1/mock/{service.slug}/
      </Typography.Text>
      {canEdit && (
        <Button onClick={() => onToggle(service)}>{service.is_enabled ? '停用' : '启用'}</Button>
      )}
    </>
  )
}

function SelectedMockWorkspace({
  projectId,
  service,
  canEdit,
}: {
  projectId: string
  service: MockService | undefined
  canEdit: boolean
}) {
  if (!service) return <Card>暂无 Mock 服务</Card>
  return <MockRouteWorkspace projectId={projectId} service={service} canEdit={canEdit} />
}

function selectedMockService(
  services: MockService[] | undefined,
  selectedId: string | null,
): MockService | undefined {
  return services?.find((item) => item.id === selectedId) ?? services?.at(0)
}

function MockServiceForm({
  pending,
  onFinish,
}: {
  pending: boolean
  onFinish: (input: { name: string; slug: string; description: string }) => void
}) {
  const [form] = Form.useForm<{ name: string; slug: string; description: string }>()
  return (
    <Card title="新建 Mock 服务" size="small">
      <Form
        name="mock-service"
        form={form}
        layout="inline"
        initialValues={{ description: '' }}
        onFinish={onFinish}
      >
        <Form.Item name="name" rules={[{ required: true }]}>
          <Input placeholder="用户服务 Mock" />
        </Form.Item>
        <Form.Item
          name="slug"
          rules={[
            { required: true },
            { pattern: /^[a-z][a-z0-9-]{2,79}$/, message: '使用小写字母、数字和连字符' },
          ]}
        >
          <Input placeholder="user-service" />
        </Form.Item>
        <Form.Item name="description">
          <Input placeholder="说明" />
        </Form.Item>
        <Button htmlType="submit" type="primary" loading={pending} icon={<PlusOutlined />}>
          新建
        </Button>
      </Form>
    </Card>
  )
}

const credentialKindOptions = [
  { value: 'postgresql', label: 'PostgreSQL' },
  { value: 'mysql', label: 'MySQL' },
  { value: 'redis', label: 'Redis' },
  { value: 'grpc_mtls', label: 'gRPC mTLS' },
]

function credentialKindLabel(kind: Credential['kind']) {
  return credentialKindOptions.find((item) => item.value === kind)?.label ?? kind
}

function defaultPort(kind: Credential['kind']): number {
  return { postgresql: 5432, mysql: 3306, redis: 6379, grpc_mtls: 443 }[kind]
}
