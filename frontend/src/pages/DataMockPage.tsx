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

import {
  createCredential,
  createMockRoute,
  createMockService,
  deleteCredential,
  deleteMockRoute,
  listCredentials,
  listMockLogs,
  listMockRoutes,
  listMockServices,
  updateMockService,
  type CredentialInput,
  type MockRouteInput,
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

function MockRouteWorkspace({
  projectId,
  service,
  canEdit,
}: {
  projectId: string
  service: MockService
  canEdit: boolean
}) {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const routes = useQuery({
    queryKey: ['mock-routes', projectId, service.id],
    queryFn: () => listMockRoutes(projectId, service.id),
  })
  const logs = useQuery({
    queryKey: ['mock-logs', projectId, service.id],
    queryFn: () => listMockLogs(projectId, service.id),
    refetchInterval: 2_000,
  })
  const createRouteMutation = useMutation({
    mutationFn: (input: MockRouteInput) => createMockRoute(projectId, service.id, input),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['mock-routes', projectId, service.id] })
      void message.success('Mock 路由已创建')
    },
    onError: (error) => void message.error(apiErrorMessage(error)),
  })
  const removeRouteMutation = useMutation({
    mutationFn: (routeId: string) => deleteMockRoute(projectId, service.id, routeId),
    onSuccess: async () =>
      queryClient.invalidateQueries({ queryKey: ['mock-routes', projectId, service.id] }),
    onError: (error) => void message.error(apiErrorMessage(error)),
  })
  return (
    <Row gutter={16}>
      {canEdit && (
        <Col xs={24} xl={9}>
          <MockRouteForm
            pending={createRouteMutation.isPending}
            onFinish={createRouteMutation.mutate}
          />
        </Col>
      )}
      <Col xs={24} xl={canEdit ? 15 : 24}>
        <Tabs
          items={[
            {
              key: 'routes',
              label: '路由规则',
              children: (
                <Table
                  rowKey="id"
                  size="small"
                  loading={routes.isLoading}
                  dataSource={routes.data ?? []}
                  pagination={false}
                  columns={[
                    { title: '名称', dataIndex: 'name' },
                    { title: '方法', dataIndex: 'method' },
                    { title: '路径', dataIndex: 'path_pattern' },
                    { title: '场景', dataIndex: 'scenario', render: (value) => value || '默认' },
                    { title: '状态码', dataIndex: 'response_status' },
                    {
                      title: '操作',
                      render: (_, item) =>
                        canEdit ? (
                          <Popconfirm
                            title="确认删除路由？"
                            onConfirm={() => removeRouteMutation.mutate(item.id)}
                          >
                            <Button
                              type="text"
                              danger
                              icon={<DeleteOutlined />}
                              aria-label="删除 Mock 路由"
                            />
                          </Popconfirm>
                        ) : null,
                    },
                  ]}
                />
              ),
            },
            {
              key: 'logs',
              label: '请求日志',
              children: (
                <Table
                  rowKey="id"
                  size="small"
                  loading={logs.isLoading}
                  dataSource={logs.data?.items ?? []}
                  columns={[
                    { title: '时间', dataIndex: 'created_at' },
                    { title: '方法', dataIndex: 'method' },
                    { title: '路径', dataIndex: 'path' },
                    {
                      title: '匹配',
                      dataIndex: 'matched',
                      render: (value) => (value ? '是' : '否'),
                    },
                    { title: '状态码', dataIndex: 'response_status' },
                    { title: '耗时', dataIndex: 'duration_ms', render: (value) => `${value} ms` },
                  ]}
                />
              ),
            },
          ]}
        />
      </Col>
    </Row>
  )
}

function MockRouteForm({
  pending,
  onFinish,
}: {
  pending: boolean
  onFinish: (input: MockRouteInput) => void
}) {
  const [form] = Form.useForm<Record<string, unknown>>()
  return (
    <Card title="新增路由规则" size="small">
      <Form
        name="mock-route"
        form={form}
        layout="vertical"
        initialValues={{
          method: 'GET',
          response_status: 200,
          delay_ms: 0,
          priority: 0,
          is_enabled: true,
          query_conditions: '{}',
          header_conditions: '{}',
          response_headers: '{}',
          response_body: '{}',
        }}
        onFinish={(values) => onFinish(mockRouteInput(values))}
      >
        <Form.Item name="name" label="名称" rules={[{ required: true }]}>
          <Input />
        </Form.Item>
        <Space align="start">
          <Form.Item name="method" label="方法">
            <Select className="method-select" options={httpMethodOptions} />
          </Form.Item>
          <Form.Item name="path_pattern" label="路径" rules={[{ required: true }]}>
            <Input placeholder="/users/{user_id}" />
          </Form.Item>
        </Space>
        <Form.Item name="scenario" label="场景（可选）">
          <Input placeholder="happy" />
        </Form.Item>
        <Form.Item name="query_conditions" label="Query 条件（JSON）" rules={[jsonRule]}>
          <Input.TextArea rows={2} className="code-input" />
        </Form.Item>
        <Form.Item name="header_conditions" label="Header 条件（JSON）" rules={[jsonRule]}>
          <Input.TextArea rows={2} className="code-input" />
        </Form.Item>
        <Form.Item name="response_body" label="响应模板（JSON）" rules={[jsonRule]}>
          <Input.TextArea rows={5} className="code-input" />
        </Form.Item>
        <Form.Item name="response_headers" label="响应 Header（JSON）" rules={[jsonRule]}>
          <Input.TextArea rows={2} className="code-input" />
        </Form.Item>
        <Space align="start">
          <Form.Item name="response_status" label="状态码">
            <InputNumber min={100} max={599} />
          </Form.Item>
          <Form.Item name="delay_ms" label="延迟 ms">
            <InputNumber min={0} max={30000} />
          </Form.Item>
          <Form.Item name="priority" label="优先级">
            <InputNumber min={-1000} max={1000} />
          </Form.Item>
        </Space>
        <Button type="primary" htmlType="submit" loading={pending}>
          保存路由
        </Button>
      </Form>
    </Card>
  )
}

function mockRouteInput(values: Record<string, unknown>): MockRouteInput {
  return {
    name: String(values.name),
    method: values.method as MockRouteInput['method'],
    path_pattern: String(values.path_pattern),
    query_conditions: jsonRecord(values.query_conditions),
    header_conditions: jsonRecord(values.header_conditions),
    response_status: Number(values.response_status),
    response_headers: jsonRecord(values.response_headers),
    response_body: JSON.parse(String(values.response_body)),
    delay_ms: Number(values.delay_ms),
    scenario: values.scenario ? String(values.scenario) : null,
    priority: Number(values.priority),
    is_enabled: true,
  }
}

function jsonRecord(value: unknown): Record<string, string> {
  return JSON.parse(String(value)) as Record<string, string>
}

const jsonRule = {
  validator: async (_: unknown, value: string) => {
    try {
      JSON.parse(value)
      return Promise.resolve()
    } catch {
      return Promise.reject(new Error('请输入有效 JSON'))
    }
  },
}

const credentialKindOptions = [
  { value: 'postgresql', label: 'PostgreSQL' },
  { value: 'mysql', label: 'MySQL' },
  { value: 'redis', label: 'Redis' },
  { value: 'grpc_mtls', label: 'gRPC mTLS' },
]
const httpMethodOptions = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE'].map((value) => ({
  value,
  label: value,
}))

function credentialKindLabel(kind: Credential['kind']) {
  return credentialKindOptions.find((item) => item.value === kind)?.label ?? kind
}

function defaultPort(kind: Credential['kind']): number {
  return { postgresql: 5432, mysql: 3306, redis: 6379, grpc_mtls: 443 }[kind]
}
