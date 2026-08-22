import { PlusOutlined, ReloadOutlined } from '@ant-design/icons'
import {
  Alert,
  Button,
  Card,
  Col,
  Form,
  Input,
  Row,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from 'antd'
import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  createRequestService,
  createServiceEndpoint,
  listRequestServices,
  listServiceEndpoints,
  setEnvironmentDefaultService,
  type CreateEndpointInput,
  type CreateRequestServiceInput,
} from '../features/service-targets/service-target-service'
import { useProjectContext } from '../features/projects/use-project-context'
import {
  listApis,
  listEnvironments,
  updateApiDefinition,
} from '../features/api-console/api-service'
import type { ApiDefinition, Environment, RequestService, ServiceEndpoint } from '../lib/api'
import { apiErrorMessage } from '../lib/api'

type ServiceForm = CreateRequestServiceInput
type EndpointForm = CreateEndpointInput

export default function RequestTargetsPage() {
  const { projectId } = useProjectContext()
  const [environmentId, setEnvironmentId] = useState<string>()
  const [serviceForm] = Form.useForm<ServiceForm>()
  const [endpointForm] = Form.useForm<EndpointForm>()
  const queryClient = useQueryClient()
  const [messageApi, contextHolder] = message.useMessage()

  const environments = useQuery({
    queryKey: ['request-target-environments', projectId],
    queryFn: () => listEnvironments(required(projectId)),
    enabled: Boolean(projectId),
  })
  const services = useQuery({
    queryKey: ['request-target-services', projectId],
    queryFn: () => listRequestServices(required(projectId)),
    enabled: Boolean(projectId),
  })
  const endpoints = useQuery({
    queryKey: [
      'request-target-endpoints',
      projectId,
      activeEnvironmentId(environments.data, environmentId),
    ],
    queryFn: () =>
      listServiceEndpoints(
        required(projectId),
        required(activeEnvironmentId(environments.data, environmentId)),
      ),
    enabled: Boolean(projectId && activeEnvironmentId(environments.data, environmentId)),
  })
  const apis = useQuery({
    queryKey: ['request-target-apis', projectId],
    queryFn: () => listApis(required(projectId), { page: 1, pageSize: 100 }),
    enabled: Boolean(projectId),
  })
  const environmentItems = listItems(environments.data)
  const serviceItems = listItems(services.data)
  const endpointItems = listItems(endpoints.data)
  const apiItems = pageItems(apis.data)
  const activeId = activeEnvironmentId(environmentItems, environmentId)

  const createService = useMutation({
    mutationFn: (input: ServiceForm) => createRequestService(required(projectId), input),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['request-target-services', projectId] })
      serviceForm.resetFields()
      messageApi.success('请求 Service 已创建')
    },
  })
  const createEndpoint = useMutation({
    mutationFn: (input: EndpointForm) =>
      createServiceEndpoint(
        required(projectId),
        required(activeEnvironmentId(environments.data, environmentId)),
        input,
      ),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: [
          'request-target-endpoints',
          projectId,
          activeEnvironmentId(environments.data, environmentId),
        ],
      })
      endpointForm.resetFields()
      messageApi.success('Endpoint Variant 已创建')
    },
  })
  const updateDefault = useMutation({
    mutationFn: (serviceId: string | null) =>
      setEnvironmentDefaultService(
        required(projectId),
        selectedEnvironment(
          required(activeEnvironmentId(environments.data, environmentId)),
          environments.data,
        ),
        serviceId,
      ),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ['request-target-environments', projectId],
      })
      messageApi.success('环境默认 Service 已更新')
    },
  })
  const updateApiService = useMutation({
    mutationFn: ({ apiId, serviceId }: { apiId: string; serviceId: string | null }) =>
      updateApiDefinition(required(projectId), apiId, { service_id: serviceId }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['request-target-apis', projectId] })
      messageApi.success('API 默认 Service 已更新')
    },
  })

  const error = environments.error ?? services.error ?? endpoints.error ?? apis.error
  const selected = environmentItems.find((item) => item.id === activeId)
  const serviceOptions = useMemo(() => toServiceOptions(serviceItems), [serviceItems])

  return (
    <>
      {contextHolder}
      <div className="page-heading">
        <div>
          <Typography.Title level={2}>请求目标</Typography.Title>
          <Typography.Text type="secondary">
            管理项目级 Service、环境 Endpoint Variant，并统一绑定 API 的默认请求目标。
          </Typography.Text>
        </div>
        <Button
          icon={<ReloadOutlined />}
          onClick={() => void queryClient.invalidateQueries({ queryKey: ['request-target'] })}
        >
          刷新
        </Button>
      </div>
      {error ? (
        <Alert
          type="error"
          showIcon
          className="page-alert"
          title="请求目标加载失败"
          description={apiErrorMessage(error)}
        />
      ) : null}
      <Row gutter={[16, 16]}>
        <Col xs={24} xl={9}>
          <ServiceCard
            services={serviceItems}
            loading={services.isLoading}
            form={serviceForm}
            submitting={createService.isPending}
            onFinish={(values) => createService.mutate(values)}
          />
        </Col>
        <Col xs={24} xl={15}>
          <EnvironmentEndpointCard
            environments={environments.data ?? []}
            selected={selected}
            environmentId={activeId}
            onEnvironmentChange={setEnvironmentId}
            serviceOptions={serviceOptions}
            endpointForm={endpointForm}
            endpoints={endpointItems}
            services={serviceItems}
            loading={environments.isLoading}
            endpointsLoading={endpoints.isLoading}
            endpointSubmitting={createEndpoint.isPending}
            defaultSubmitting={updateDefault.isPending}
            onDefaultChange={(value) => updateDefault.mutate(value)}
            onEndpointFinish={(values) => createEndpoint.mutate(values)}
          />
        </Col>
      </Row>
      <ApiServiceCard
        apis={apiItems}
        loading={apis.isLoading}
        serviceOptions={serviceOptions}
        onChange={(apiId, serviceId) => updateApiService.mutate({ apiId, serviceId })}
      />
    </>
  )
}

function ServiceCard({
  services,
  loading,
  form,
  submitting,
  onFinish,
}: {
  services: RequestService[]
  loading: boolean
  form: ReturnType<typeof Form.useForm<ServiceForm>>[0]
  submitting: boolean
  onFinish: (values: ServiceForm) => void
}) {
  return (
    <Card title="Service" loading={loading}>
      <Form<ServiceForm> form={form} layout="vertical" onFinish={onFinish}>
        <Form.Item name="service_key" label="Service Key" rules={[{ required: true }]}>
          <Input placeholder="orders" />
        </Form.Item>
        <Form.Item name="name" label="名称" rules={[{ required: true }]}>
          <Input placeholder="订单服务" />
        </Form.Item>
        <Form.Item name="description" label="描述">
          <Input.TextArea rows={2} />
        </Form.Item>
        <Button type="primary" htmlType="submit" icon={<PlusOutlined />} loading={submitting}>
          创建 Service
        </Button>
      </Form>
      <Table<RequestService>
        className="request-target-table"
        rowKey="id"
        size="small"
        pagination={false}
        dataSource={services}
        locale={{ emptyText: '暂无请求 Service' }}
        columns={[
          { title: 'Key', dataIndex: 'service_key' },
          { title: '名称', dataIndex: 'name' },
          {
            title: '状态',
            dataIndex: 'enabled',
            render: (enabled: boolean) => (
              <Tag color={enabled ? 'success' : 'default'}>{enabled ? '启用' : '停用'}</Tag>
            ),
          },
        ]}
      />
    </Card>
  )
}

function EnvironmentEndpointCard({
  environments,
  selected,
  environmentId,
  onEnvironmentChange,
  serviceOptions,
  endpointForm,
  endpoints,
  services,
  loading,
  endpointsLoading,
  endpointSubmitting,
  defaultSubmitting,
  onDefaultChange,
  onEndpointFinish,
}: {
  environments: Environment[]
  selected: Environment | undefined
  environmentId: string | undefined
  onEnvironmentChange: (value: string) => void
  serviceOptions: Array<{ value: string; label: string }>
  endpointForm: ReturnType<typeof Form.useForm<EndpointForm>>[0]
  endpoints: ServiceEndpoint[]
  services: RequestService[]
  loading: boolean
  endpointsLoading: boolean
  endpointSubmitting: boolean
  defaultSubmitting: boolean
  onDefaultChange: (value: string | null) => void
  onEndpointFinish: (values: EndpointForm) => void
}) {
  return (
    <Card
      title="环境 Endpoint Variant"
      extra={
        <Select
          aria-label="目标环境"
          style={{ minWidth: 180 }}
          value={environmentId}
          onChange={onEnvironmentChange}
          options={environments.map((item) => ({ value: item.id, label: item.name }))}
        />
      }
      loading={loading}
    >
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        {selected ? (
          <Space wrap>
            <Typography.Text>环境默认 Service</Typography.Text>
            <Select
              aria-label="环境默认 Service"
              allowClear
              style={{ minWidth: 260 }}
              value={selected.default_service_id ?? undefined}
              options={serviceOptions}
              onChange={(value?: string) => onDefaultChange(value ?? null)}
              loading={defaultSubmitting}
            />
          </Space>
        ) : null}
        <Form<EndpointForm> form={endpointForm} layout="inline" onFinish={onEndpointFinish}>
          <Form.Item name="service_id" rules={[{ required: true, message: '请选择 Service' }]}>
            <Select
              aria-label="Endpoint Service"
              placeholder="Service"
              options={serviceOptions}
              style={{ minWidth: 220 }}
            />
          </Form.Item>
          <Form.Item name="variant" initialValue="default">
            <Input aria-label="Endpoint Variant" placeholder="default" />
          </Form.Item>
          <Form.Item name="base_url" rules={[{ required: true, message: '请输入 Base URL' }]}>
            <Input
              aria-label="Endpoint Base URL"
              placeholder="https://orders.example.com"
              style={{ minWidth: 260 }}
            />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={endpointSubmitting}>
            添加 Endpoint
          </Button>
        </Form>
        <Table<ServiceEndpoint>
          rowKey="id"
          size="small"
          pagination={false}
          loading={endpointsLoading}
          dataSource={endpoints}
          locale={{ emptyText: '当前环境暂无 Endpoint Variant' }}
          columns={[
            {
              title: 'Service',
              dataIndex: 'service_id',
              render: (value: string) =>
                services.find((item) => item.id === value)?.service_key ?? value,
            },
            { title: 'Variant', dataIndex: 'variant' },
            { title: 'Base URL', dataIndex: 'base_url' },
            { title: 'Revision', dataIndex: 'revision' },
            {
              title: '状态',
              dataIndex: 'enabled',
              render: (enabled: boolean) => (
                <Tag color={enabled ? 'success' : 'default'}>{enabled ? '启用' : '停用'}</Tag>
              ),
            },
          ]}
        />
      </Space>
    </Card>
  )
}

function ApiServiceCard({
  apis,
  loading,
  serviceOptions,
  onChange,
}: {
  apis: ApiDefinition[]
  loading: boolean
  serviceOptions: Array<{ value: string; label: string }>
  onChange: (apiId: string, serviceId: string | null) => void
}) {
  return (
    <Card title="API 默认 Service" className="performance-card" loading={loading}>
      <Table<ApiDefinition>
        rowKey="id"
        size="small"
        pagination={false}
        dataSource={apis}
        locale={{ emptyText: '暂无 API 资产' }}
        columns={[
          { title: 'API', dataIndex: 'name' },
          { title: '版本', dataIndex: 'current_version', width: 80 },
          {
            title: '默认 Service',
            dataIndex: 'service_id',
            render: (value: string | null | undefined, item: ApiDefinition) => (
              <Select
                aria-label={`${item.name} 默认 Service`}
                allowClear
                style={{ minWidth: 260 }}
                value={value ?? undefined}
                options={serviceOptions}
                onChange={(serviceId?: string) => onChange(item.id, serviceId ?? null)}
              />
            ),
          },
        ]}
      />
    </Card>
  )
}

function required(value: string | null | undefined): string {
  if (!value) throw new Error('项目或环境尚未选择')
  return value
}

function selectedEnvironment(
  environmentId: string,
  environments: Environment[] | undefined,
): Environment {
  const environment = environments?.find((item) => item.id === environmentId)
  if (!environment) throw new Error('环境不存在')
  return environment
}

function activeEnvironmentId(
  environments: Environment[] | undefined,
  selectedId: string | undefined,
): string | undefined {
  return selectedId ?? environments?.[0]?.id
}

function listItems<T>(items: T[] | undefined): T[] {
  return items ?? []
}

function pageItems<T>(page: { items: T[] } | undefined): T[] {
  return page?.items ?? []
}

function toServiceOptions(services: RequestService[]): Array<{ value: string; label: string }> {
  return services.map((service) => ({
    value: service.id,
    label: `${service.name} · ${service.service_key}`,
  }))
}
