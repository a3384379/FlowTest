import { EditOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons'
import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Form,
  Input,
  InputNumber,
  Modal,
  Row,
  Select,
  Space,
  Switch,
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
  checkServiceEndpointConnectivity,
  getServiceTargetImpactPreview,
  listRequestServices,
  listServiceEndpoints,
  setEnvironmentDefaultService,
  updateRequestService,
  updateServiceEndpoint,
  type CreateEndpointInput,
  type CreateRequestServiceInput,
  type EndpointConnectivity,
  type ServiceTargetImpactPreview,
  type UpdateEndpointInput,
  type UpdateRequestServiceInput,
} from '../features/service-targets/service-target-service'
import { listSecrets } from '../features/projects/asset-service'
import { useProjectContext } from '../features/projects/use-project-context'
import {
  listApis,
  listEnvironments,
  updateApiDefinition,
} from '../features/api-console/api-service'
import type {
  ApiDefinition,
  Environment,
  RequestService,
  SecretMetadata,
  ServiceEndpoint,
} from '../lib/api'
import { apiErrorMessage } from '../lib/api'

type ServiceForm = CreateRequestServiceInput
type EndpointForm = CreateEndpointInput
type ServiceEditForm = UpdateRequestServiceInput
type EndpointEditForm = Omit<UpdateEndpointInput, 'headers' | 'variables'> & {
  headers_json: string
  variables_json: string
}

type ImpactEditTarget =
  { kind: 'service'; service: RequestService } | { kind: 'endpoint'; endpoint: ServiceEndpoint }

export default function RequestTargetsPage() {
  const { projectId } = useProjectContext()
  const [environmentId, setEnvironmentId] = useState<string>()
  const [serviceForm] = Form.useForm<ServiceForm>()
  const [endpointForm] = Form.useForm<EndpointForm>()
  const [serviceEditForm] = Form.useForm<ServiceEditForm>()
  const [endpointEditForm] = Form.useForm<EndpointEditForm>()
  const [editingTarget, setEditingTarget] = useState<ImpactEditTarget>()
  const [impactPreview, setImpactPreview] = useState<ServiceTargetImpactPreview>()
  const [connectivity, setConnectivity] = useState<Record<string, EndpointConnectivity>>({})
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
  const secrets = useQuery({
    queryKey: ['request-target-secrets', projectId],
    queryFn: () => listSecrets(required(projectId)),
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
  const prepareEdit = useMutation({
    mutationFn: (target: ImpactEditTarget) =>
      loadImpactPreview(required(projectId), target).then((preview) => ({ preview, target })),
    onSuccess: ({ preview, target }) => {
      setImpactPreview(preview)
      setEditingTarget(target)
      setEditFormValues(target, serviceEditForm, endpointEditForm)
    },
    onError: (reason) => messageApi.error(apiErrorMessage(reason)),
  })
  const updateService = useMutation({
    mutationFn: ({ serviceId, input }: { serviceId: string; input: ServiceEditForm }) =>
      updateRequestService(required(projectId), serviceId, input),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['request-target-services', projectId] })
      closeEdit(setEditingTarget, setImpactPreview)
      messageApi.success('Service 已更新')
    },
    onError: (reason) => messageApi.error(apiErrorMessage(reason)),
  })
  const updateEndpoint = useMutation({
    mutationFn: ({ endpointId, input }: { endpointId: string; input: EndpointEditForm }) =>
      updateServiceEndpoint(required(projectId), endpointId, endpointEditPayload(input)),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['request-target-endpoints', projectId] })
      closeEdit(setEditingTarget, setImpactPreview)
      messageApi.success('Endpoint 已更新')
    },
    onError: (reason) => messageApi.error(apiErrorMessage(reason)),
  })
  const checkConnectivity = useMutation({
    mutationFn: (endpointId: string) =>
      checkServiceEndpointConnectivity(required(projectId), endpointId),
    onSuccess: (result) => {
      setConnectivity((current) => ({ ...current, [result.endpoint_id]: result }))
      messageApi.success('Connectivity 检查已完成')
    },
    onError: (reason) => messageApi.error(apiErrorMessage(reason)),
  })

  const error =
    environments.error ?? services.error ?? endpoints.error ?? apis.error ?? secrets.error
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
            onEdit={(service) => prepareEdit.mutate({ kind: 'service', service })}
            editLoading={prepareEdit.isPending}
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
            secrets={listItems(secrets.data)}
            connectivity={connectivity}
            loading={environments.isLoading}
            endpointsLoading={endpoints.isLoading}
            endpointSubmitting={createEndpoint.isPending}
            defaultSubmitting={updateDefault.isPending}
            onDefaultChange={(value) => updateDefault.mutate(value)}
            onEndpointFinish={(values) => createEndpoint.mutate(values)}
            onEditEndpoint={(endpoint) => prepareEdit.mutate({ kind: 'endpoint', endpoint })}
            onCheckConnectivity={(endpointId) => checkConnectivity.mutate(endpointId)}
            actionLoading={prepareEdit.isPending || checkConnectivity.isPending}
          />
        </Col>
      </Row>
      <ApiServiceCard
        apis={apiItems}
        loading={apis.isLoading}
        serviceOptions={serviceOptions}
        onChange={(apiId, serviceId) => updateApiService.mutate({ apiId, serviceId })}
      />
      <RequestTargetEditModal
        target={editingTarget}
        impact={impactPreview}
        services={serviceItems}
        secrets={listItems(secrets.data)}
        serviceForm={serviceEditForm}
        endpointForm={endpointEditForm}
        submitting={updateService.isPending || updateEndpoint.isPending}
        onCancel={() => closeEdit(setEditingTarget, setImpactPreview)}
        onServiceFinish={(values) => {
          if (editingTarget?.kind === 'service') {
            updateService.mutate({ serviceId: editingTarget.service.id, input: values })
          }
        }}
        onEndpointFinish={(values) => {
          if (editingTarget?.kind === 'endpoint') {
            updateEndpoint.mutate({ endpointId: editingTarget.endpoint.id, input: values })
          }
        }}
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
  onEdit,
  editLoading,
}: {
  services: RequestService[]
  loading: boolean
  form: ReturnType<typeof Form.useForm<ServiceForm>>[0]
  submitting: boolean
  onFinish: (values: ServiceForm) => void
  onEdit: (service: RequestService) => void
  editLoading: boolean
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
          {
            title: '操作',
            render: (_value: unknown, service: RequestService) => (
              <Button
                type="link"
                size="small"
                icon={<EditOutlined />}
                loading={editLoading}
                onClick={() => onEdit(service)}
              >
                影响预览 / 编辑
              </Button>
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
  secrets,
  connectivity,
  loading,
  endpointsLoading,
  endpointSubmitting,
  defaultSubmitting,
  onDefaultChange,
  onEndpointFinish,
  onEditEndpoint,
  onCheckConnectivity,
  actionLoading,
}: {
  environments: Environment[]
  selected: Environment | undefined
  environmentId: string | undefined
  onEnvironmentChange: (value: string) => void
  serviceOptions: Array<{ value: string; label: string }>
  endpointForm: ReturnType<typeof Form.useForm<EndpointForm>>[0]
  endpoints: ServiceEndpoint[]
  services: RequestService[]
  secrets: SecretMetadata[]
  connectivity: Record<string, EndpointConnectivity>
  loading: boolean
  endpointsLoading: boolean
  endpointSubmitting: boolean
  defaultSubmitting: boolean
  onDefaultChange: (value: string | null) => void
  onEndpointFinish: (values: EndpointForm) => void
  onEditEndpoint: (endpoint: ServiceEndpoint) => void
  onCheckConnectivity: (endpointId: string) => void
  actionLoading: boolean
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
            {
              title: 'Timeout',
              render: (_value: unknown, item: ServiceEndpoint) =>
                `${item.connect_timeout_ms}/${item.read_timeout_ms} ms`,
            },
            {
              title: 'TLS',
              dataIndex: 'tls_verify',
              render: (enabled: boolean) => (enabled ? '校验' : '不校验'),
            },
            { title: 'Proxy Ref', dataIndex: 'proxy_ref', render: nullableText },
            {
              title: 'Headers / Variables',
              render: (_value: unknown, item: ServiceEndpoint) =>
                `${Object.keys(item.headers).length} / ${Object.keys(item.variables ?? {}).length}`,
            },
            {
              title: 'Secret Refs',
              render: (_value: unknown, item: ServiceEndpoint) =>
                secretReferenceSummary(item.secret_refs, secrets),
            },
            {
              title: 'Health / Expected',
              render: (_value: unknown, item: ServiceEndpoint) =>
                `${item.health_check_path ?? '-'} / ${item.health_expected_status ?? '-'}`,
            },
            { title: 'Revision', dataIndex: 'revision' },
            {
              title: '状态',
              dataIndex: 'enabled',
              render: (enabled: boolean) => (
                <Tag color={enabled ? 'success' : 'default'}>{enabled ? '启用' : '停用'}</Tag>
              ),
            },
            {
              title: 'Connectivity',
              render: (_value: unknown, item: ServiceEndpoint) => (
                <Space>
                  <ConnectivityTag result={connectivity[item.id]} />
                  <Button
                    size="small"
                    loading={actionLoading}
                    onClick={() => onCheckConnectivity(item.id)}
                  >
                    检查
                  </Button>
                </Space>
              ),
            },
            {
              title: '操作',
              render: (_value: unknown, item: ServiceEndpoint) => (
                <Button
                  type="link"
                  size="small"
                  icon={<EditOutlined />}
                  loading={actionLoading}
                  onClick={() => onEditEndpoint(item)}
                >
                  影响预览 / 编辑
                </Button>
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

function RequestTargetEditModal({
  target,
  impact,
  services,
  secrets,
  serviceForm,
  endpointForm,
  submitting,
  onCancel,
  onServiceFinish,
  onEndpointFinish,
}: {
  target: ImpactEditTarget | undefined
  impact: ServiceTargetImpactPreview | undefined
  services: RequestService[]
  secrets: SecretMetadata[]
  serviceForm: ReturnType<typeof Form.useForm<ServiceEditForm>>[0]
  endpointForm: ReturnType<typeof Form.useForm<EndpointEditForm>>[0]
  submitting: boolean
  onCancel: () => void
  onServiceFinish: (values: ServiceEditForm) => void
  onEndpointFinish: (values: EndpointEditForm) => void
}) {
  const isService = target?.kind === 'service'
  const activeForm = isService ? serviceForm : endpointForm
  return (
    <Modal
      open={Boolean(target)}
      width={860}
      title={isService ? 'Service 影响预览 / 编辑' : 'Endpoint 影响预览 / 编辑'}
      okText="保存变更"
      cancelText="取消"
      confirmLoading={submitting}
      onCancel={onCancel}
      onOk={() => activeForm.submit()}
      destroyOnHidden
    >
      <ImpactPreviewPanel impact={impact} />
      {isService ? (
        <ServiceEditFields form={serviceForm} onFinish={onServiceFinish} />
      ) : (
        <EndpointEditFields
          form={endpointForm}
          endpoint={target?.kind === 'endpoint' ? target.endpoint : undefined}
          services={services}
          secrets={secrets}
          onFinish={onEndpointFinish}
        />
      )}
    </Modal>
  )
}

function ImpactPreviewPanel({ impact }: { impact: ServiceTargetImpactPreview | undefined }) {
  if (!impact) return null
  return (
    <Alert
      className="page-alert"
      type="warning"
      showIcon
      title="保存前请确认下游影响"
      description={
        <Descriptions size="small" column={1}>
          <Descriptions.Item label="Affected APIs">
            {impactSummary(impact.affected_apis)}
          </Descriptions.Item>
          <Descriptions.Item label="Affected Workflows">
            {impactSummary(impact.affected_workflows)}
          </Descriptions.Item>
          <Descriptions.Item label="Affected Test Plans">
            {impactSummary(impact.affected_test_plans)}
          </Descriptions.Item>
          <Descriptions.Item label="Affected Scheduled Runs">
            {impactSummary(impact.affected_scheduled_runs)}
          </Descriptions.Item>
          <Descriptions.Item label="Affected Release Gates">
            {impactSummary(impact.affected_release_gates)}
          </Descriptions.Item>
        </Descriptions>
      }
    />
  )
}

function ServiceEditFields({
  form,
  onFinish,
}: {
  form: ReturnType<typeof Form.useForm<ServiceEditForm>>[0]
  onFinish: (values: ServiceEditForm) => void
}) {
  return (
    <Form<ServiceEditForm> form={form} layout="vertical" onFinish={onFinish}>
      <Row gutter={16}>
        <Col span={12}>
          <Form.Item name="name" label="名称" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item name="owner_team" label="Owner Team">
            <Input />
          </Form.Item>
        </Col>
      </Row>
      <Form.Item name="service_type" label="Service Type">
        <Select
          options={['http', 'https', 'grpc', 'graphql', 'other'].map((value) => ({
            value,
            label: value,
          }))}
        />
      </Form.Item>
      <Form.Item name="description" label="描述">
        <Input.TextArea rows={2} />
      </Form.Item>
      <Form.Item name="enabled" label="Enable / Disable Service" valuePropName="checked">
        <Switch />
      </Form.Item>
    </Form>
  )
}

function EndpointEditFields({
  form,
  endpoint,
  services,
  secrets,
  onFinish,
}: {
  form: ReturnType<typeof Form.useForm<EndpointEditForm>>[0]
  endpoint: ServiceEndpoint | undefined
  services: RequestService[]
  secrets: SecretMetadata[]
  onFinish: (values: EndpointEditForm) => void
}) {
  const service = services.find((item) => item.id === endpoint?.service_id)
  return (
    <Form<EndpointEditForm> form={form} layout="vertical" onFinish={onFinish}>
      <Descriptions size="small" column={2}>
        <Descriptions.Item label="Service">
          {service ? `${service.name} · ${service.service_key}` : '-'}
        </Descriptions.Item>
        <Descriptions.Item label="Revision">r{endpoint?.revision ?? '-'}</Descriptions.Item>
      </Descriptions>
      <Row gutter={16}>
        <Col span={8}>
          <Form.Item name="variant" label="Endpoint Variant" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
        </Col>
        <Col span={16}>
          <Form.Item name="base_url" label="Base URL" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
        </Col>
      </Row>
      <Row gutter={16}>
        <Col span={8}>
          <Form.Item name="connect_timeout_ms" label="Connect Timeout (ms)">
            <InputNumber min={100} max={300_000} style={{ width: '100%' }} />
          </Form.Item>
        </Col>
        <Col span={8}>
          <Form.Item name="read_timeout_ms" label="Read Timeout (ms)">
            <InputNumber min={100} max={300_000} style={{ width: '100%' }} />
          </Form.Item>
        </Col>
        <Col span={4}>
          <Form.Item name="tls_verify" label="TLS Verify" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Col>
        <Col span={4}>
          <Form.Item name="enabled" label="Enabled" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Col>
      </Row>
      <Form.Item name="proxy_ref" label="Proxy Ref">
        <Input />
      </Form.Item>
      <Form.Item name="headers_json" label="Headers (JSON)" rules={[jsonRecordRule()]}>
        <Input.TextArea rows={3} />
      </Form.Item>
      <Form.Item name="variables_json" label="Variables (JSON)" rules={[jsonRecordRule()]}>
        <Input.TextArea rows={3} />
      </Form.Item>
      <Form.Item name="secret_refs" label="Secret Refs（仅选择引用，不展示明文）">
        <Select
          mode="multiple"
          options={secrets.map((secret) => ({ value: secret.name, label: secret.name }))}
        />
      </Form.Item>
      <Row gutter={16}>
        <Col span={16}>
          <Form.Item name="health_check_path" label="Health Check Path">
            <Input placeholder="/health" />
          </Form.Item>
        </Col>
        <Col span={8}>
          <Form.Item name="health_expected_status" label="Expected Status">
            <InputNumber min={100} max={599} style={{ width: '100%' }} />
          </Form.Item>
        </Col>
      </Row>
    </Form>
  )
}

function ConnectivityTag({ result }: { result: EndpointConnectivity | undefined }) {
  if (!result) return <Tag>未检查</Tag>
  const healthy = result.status === 'reachable'
  return (
    <Tag color={healthy ? 'success' : 'warning'}>
      {result.status} {result.http_status ?? result.error_code ?? ''}
    </Tag>
  )
}

function impactSummary(items: Array<{ name: string }>): string {
  return items.length ? `${items.length}: ${items.map((item) => item.name).join(', ')}` : '0'
}

function loadImpactPreview(
  projectId: string,
  target: ImpactEditTarget,
): Promise<ServiceTargetImpactPreview> {
  const serviceId = target.kind === 'service' ? target.service.id : target.endpoint.service_id
  return getServiceTargetImpactPreview(projectId, serviceId)
}

function setEditFormValues(
  target: ImpactEditTarget,
  serviceForm: ReturnType<typeof Form.useForm<ServiceEditForm>>[0],
  endpointForm: ReturnType<typeof Form.useForm<EndpointEditForm>>[0],
) {
  if (target.kind === 'service') {
    serviceForm.setFieldsValue(target.service)
    return
  }
  endpointForm.setFieldsValue({
    ...target.endpoint,
    headers_json: JSON.stringify(target.endpoint.headers, null, 2),
    variables_json: JSON.stringify(target.endpoint.variables ?? {}, null, 2),
  })
}

function endpointEditPayload(values: EndpointEditForm): UpdateEndpointInput {
  const { headers_json, variables_json, ...input } = values
  return {
    ...input,
    headers: parseJsonRecord(headers_json),
    variables: parseJsonRecord(variables_json),
  }
}

function parseJsonRecord(value: string): Record<string, string> {
  const parsed: unknown = JSON.parse(value || '{}')
  if (!isStringRecord(parsed)) throw new Error('JSON 必须是字符串键值对')
  return parsed
}

function isStringRecord(value: unknown): value is Record<string, string> {
  return (
    typeof value === 'object' &&
    value !== null &&
    !Array.isArray(value) &&
    Object.values(value).every((item) => typeof item === 'string')
  )
}

function jsonRecordRule() {
  return {
    validator: async (_rule: unknown, value: string) => {
      parseJsonRecord(value)
    },
    message: '请输入字符串键值对 JSON',
  }
}

function nullableText(value: string | null | undefined): string {
  return value || '-'
}

function secretReferenceSummary(refs: string[], secrets: SecretMetadata[]): string {
  const known = new Set(secrets.map((secret) => secret.name))
  const available = refs.filter((ref) => known.has(ref)).length
  return `${refs.length} refs / ${available} available`
}

function closeEdit(
  setTarget: (value: ImpactEditTarget | undefined) => void,
  setImpact: (value: ServiceTargetImpactPreview | undefined) => void,
) {
  setTarget(undefined)
  setImpact(undefined)
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
