import TargetChangeComparison from '../features/service-targets/TargetChangeComparison'
import BindingReviewModal, {
  type BindingCandidate,
} from '../features/service-targets/BindingReviewModal'
import TargetResolutionPreview from '../features/service-targets/TargetResolutionPreview'
import TargetDraftGuard from '../features/service-targets/TargetDraftGuard'
import TargetImpactPanel from '../features/service-targets/TargetImpactPanel'
import EnvironmentEndpointCard from '../features/service-targets/EnvironmentEndpointCard'
import EnvironmentMapEditor from '../features/api-console/EnvironmentMapEditor'
import {
  mapValue,
  parseEnvironmentMap,
  type EnvironmentMapValue,
} from '../features/api-console/environment-map'
import CatalogPagination from '../components/CatalogPagination'
import { invalidateRequestTargets } from '../features/service-targets/request-target-cache'
import { useCatalogQuery } from '../lib/catalog-query'
import { EditOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons'
import {
  Alert,
  Button,
  Card,
  Col,
  Collapse,
  Descriptions,
  Form,
  Input,
  InputNumber,
  Modal,
  Row,
  Select,
  Switch,
  Table,
  Space,
  Tag,
  Typography,
  message,
} from 'antd'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
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
  type TargetPreviewChange,
} from '../features/service-targets/service-target-service'
import { listSecrets } from '../features/projects/asset-service'
import { useEnvironmentSelection } from '../features/projects/environment-selection'
import { useProjectContext } from '../features/projects/use-project-context'
import { useProjectCapabilities } from '../features/projects/use-project-capabilities'
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
  headers_map: EnvironmentMapValue
  variables_map: EnvironmentMapValue
}

type ImpactEditTarget =
  { kind: 'service'; service: RequestService } | { kind: 'endpoint'; endpoint: ServiceEndpoint }

export default function RequestTargetsPage() {
  const { projectId } = useProjectContext()
  return projectId ? (
    <RequestTargetsWorkspace key={projectId} projectId={projectId} />
  ) : (
    <Alert type="info" title="请先选择项目" />
  )
}

function RequestTargetsWorkspace({ projectId }: { projectId: string }) {
  const { canEdit, permissions } = useProjectCapabilities()
  const [serviceForm] = Form.useForm<ServiceForm>()
  const [endpointForm] = Form.useForm<EndpointForm>()
  const [serviceEditForm] = Form.useForm<ServiceEditForm>()
  const [endpointEditForm] = Form.useForm<EndpointEditForm>()
  const [selectedServiceId, setSelectedServiceId] = useState<string>()
  const [editingTarget, setEditingTarget] = useState<ImpactEditTarget & { session: number }>()
  const [editDirty, setEditDirty] = useState(false)
  const [bindingCandidate, setBindingCandidate] = useState<BindingCandidate>()
  const session = useRef({ active: true, edit: 0, binding: 0 })
  useEffect(() => {
    const current = session.current
    current.active = true
    return () => {
      current.active = false
      current.edit += 1
      current.binding += 1
    }
  }, [])
  const [impactPreview, setImpactPreview] = useState<ServiceTargetImpactPreview>()
  const [connectivity, setConnectivity] = useState<Record<string, EndpointConnectivity>>({})
  const queryClient = useQueryClient()
  const [messageApi, contextHolder] = message.useMessage()

  const environments = useQuery({
    queryKey: ['request-target-environments', projectId],
    queryFn: () => listEnvironments(required(projectId)),
    enabled: Boolean(projectId),
  })
  const {
    environmentId,
    selectEnvironment: setEnvironmentId,
    selectionInvalid: environmentSelectionInvalid,
    environmentPlaceholder,
    environmentStatus,
  } = useEnvironmentSelection(projectId, environments.data)
  const environmentContext = useRef(environmentId)
  useLayoutEffect(() => {
    environmentContext.current = environmentId
  }, [environmentId])
  const services = useQuery({
    queryKey: ['request-target-services', projectId],
    queryFn: () => listRequestServices(required(projectId)),
    enabled: Boolean(projectId),
  })
  const endpoints = useQuery({
    queryKey: ['request-target-endpoints', projectId, environmentId],
    queryFn: () => listServiceEndpoints(required(projectId), required(environmentId)),
    enabled: Boolean(projectId && environmentId),
  })
  const apis = useCatalogQuery('request-target-apis', projectId, (page) =>
    listApis(required(projectId), { page, pageSize: 20 }),
  )
  const secrets = useQuery({
    queryKey: ['request-target-secrets', projectId],
    queryFn: () => listSecrets(required(projectId)),
    enabled: Boolean(projectId),
  })
  const environmentItems = listItems(environments.data)
  const serviceItems = listItems(services.data)
  const endpointItems = listItems(endpoints.data)
  const apiItems = pageItems(apis.data)

  const createService = useMutation({
    mutationFn: (input: ServiceForm) => createRequestService(editable(projectId, canEdit), input),
    onSuccess: async () => {
      await invalidateRequestTargets(queryClient, projectId)
      if (!session.current.active) return
      serviceForm.resetFields()
      messageApi.success('逻辑服务已创建')
    },
    onError: (reason) => {
      if (session.current.active) messageApi.error(apiErrorMessage(reason))
    },
  })
  const createEndpoint = useMutation({
    mutationFn: (input: EndpointForm) =>
      createServiceEndpoint(editable(projectId, canEdit), required(environmentId), input),
    onSuccess: async (result) => {
      await invalidateRequestTargets(queryClient, projectId)
      if (!session.current.active || environmentContext.current !== result.environment_id) return
      endpointForm.resetFields()
      messageApi.success('部署地址变体已创建')
    },
    onError: (reason) => {
      if (session.current.active) messageApi.error(apiErrorMessage(reason))
    },
  })
  const updateDefault = useMutation({
    mutationFn: (candidate: Extract<BindingCandidate, { kind: 'environment' }>) => {
      if (candidate.environment.id !== environmentId)
        throw new Error('管理环境已切换，请重新编辑候选')
      return setEnvironmentDefaultService(
        editable(projectId, canEdit),
        candidate.environment,
        candidate.serviceId,
      )
    },
    onSuccess: async (_result, candidate) => {
      await invalidateRequestTargets(queryClient, projectId)
      if (!session.current.active || session.current.binding !== candidate.session) return
      setBindingCandidate(undefined)
      messageApi.success('环境默认服务已更新')
    },
  })
  const updateApiService = useMutation({
    mutationFn: (candidate: Extract<BindingCandidate, { kind: 'api' }>) =>
      updateApiDefinition(editable(projectId, canEdit), candidate.api.id, {
        service_id: candidate.serviceId,
      }),
    onSuccess: async (_result, candidate) => {
      await invalidateRequestTargets(queryClient, projectId)
      if (!session.current.active || session.current.binding !== candidate.session) return
      setBindingCandidate(undefined)
      messageApi.success('接口默认服务已更新')
    },
  })
  const prepareEdit = useMutation({
    mutationFn: ({
      target,
      request,
      environment,
    }: {
      target: ImpactEditTarget
      request: number
      environment: string | null
    }) =>
      loadImpactPreview(required(projectId), target).then((preview) => ({
        preview,
        target,
        request,
        environment,
      })),
    onSuccess: ({ preview, target, request, environment }) => {
      if (
        !session.current.active ||
        request !== session.current.edit ||
        environment !== environmentContext.current
      )
        return
      setEditDirty(false)
      setImpactPreview(preview)
      setEditingTarget({ ...target, session: request })
      setEditFormValues(target, serviceEditForm, endpointEditForm)
    },
    onError: (reason, input) => {
      if (
        session.current.active &&
        input.request === session.current.edit &&
        input.environment === environmentContext.current
      )
        messageApi.error(apiErrorMessage(reason))
    },
  })
  function openEdit(target: ImpactEditTarget) {
    prepareEdit.mutate({
      target,
      request: ++session.current.edit,
      environment: environmentContext.current,
    })
  }
  function cancelEdit() {
    session.current.edit += 1
    setEditDirty(false)
    setEditingTarget(undefined)
    setImpactPreview(undefined)
  }
  const updateService = useMutation({
    mutationFn: ({
      serviceId,
      input,
    }: {
      serviceId: string
      input: ServiceEditForm
      session: number
    }) => updateRequestService(editable(projectId, canEdit), serviceId, input),
    onSuccess: async (_result, input) => {
      await invalidateRequestTargets(queryClient, projectId)
      if (!session.current.active || input.session !== session.current.edit) return
      cancelEdit()
      messageApi.success('逻辑服务已更新')
    },
    onError: (reason) => {
      if (session.current.active) messageApi.error(apiErrorMessage(reason))
    },
  })
  const updateEndpoint = useMutation({
    mutationFn: ({
      endpointId,
      input,
      environment,
    }: {
      endpointId: string
      input: EndpointEditForm
      session: number
      environment: string
    }) => {
      if (environmentContext.current !== environment)
        throw new Error('管理环境已切换，请重新编辑地址候选')
      return updateServiceEndpoint(
        editable(projectId, canEdit),
        endpointId,
        endpointEditPayload(input),
      )
    },
    onSuccess: async (_result, input) => {
      await invalidateRequestTargets(queryClient, projectId)
      if (!session.current.active || input.session !== session.current.edit) return
      cancelEdit()
      messageApi.success('部署地址已更新')
    },
    onError: (reason) => {
      if (session.current.active) messageApi.error(apiErrorMessage(reason))
    },
  })
  const checkConnectivity = useMutation({
    mutationFn: (endpointId: string) =>
      checkServiceEndpointConnectivity(required(projectId), endpointId),
    onSuccess: (result) => {
      setConnectivity((current) => ({ ...current, [result.endpoint_id]: result }))
      messageApi.success('连通性检查已完成')
    },
    onError: (reason) => messageApi.error(apiErrorMessage(reason)),
  })

  const error = [
    permissions.error,
    environments.error,
    services.error,
    endpoints.error,
    apis.error,
    secrets.error,
  ].find(Boolean)
  const selected = environmentItems.find((item) => item.id === environmentId)
  const selectedService = chooseService(serviceItems, selectedServiceId, selected)
  const serviceOptions = toServiceOptions(serviceItems)

  return (
    <>
      {contextHolder}
      <TargetDraftGuard
        projectId={projectId}
        dirty={hasTargetDraft(canEdit, bindingCandidate, editDirty)}
      />
      <div className="page-heading">
        <div>
          <Typography.Title level={2}>请求目标</Typography.Title>
          <Typography.Text type="secondary">
            逻辑服务代表一个业务模块，地址变体是该服务在所选环境中的部署地址。请求按节点服务覆盖、接口默认服务、环境默认服务的顺序解析。
          </Typography.Text>
        </div>
        <Button
          icon={<ReloadOutlined />}
          onClick={() => void invalidateRequestTargets(queryClient, projectId)}
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
            readOnly={!canEdit}
            services={serviceItems}
            loading={services.isLoading}
            form={serviceForm}
            submitting={createService.isPending}
            onFinish={(values) => createService.mutate(values)}
            onEdit={(service) => openEdit({ kind: 'service', service })}
            editLoading={prepareEdit.isPending}
            selectedId={selectedService?.id}
            onSelect={setSelectedServiceId}
          />
        </Col>
        <Col xs={24} xl={15}>
          <EnvironmentEndpointCard
            readOnly={!canEdit}
            environments={environmentItems}
            selected={selected}
            environmentId={environmentId}
            onEnvironmentChange={setEnvironmentId}
            environmentSelectionInvalid={environmentSelectionInvalid}
            environmentPlaceholder={environmentPlaceholder}
            environmentStatus={environmentStatus}
            serviceOptions={serviceOptions}
            endpointForm={endpointForm}
            endpoints={endpointItems}
            service={selectedService}
            secrets={listItems(secrets.data)}
            connectivity={connectivity}
            loading={environments.isLoading}
            endpointsLoading={endpoints.isLoading}
            endpointSubmitting={createEndpoint.isPending}
            defaultSubmitting={updateDefault.isPending}
            onDefaultChange={(value) => {
              updateDefault.reset()
              setBindingCandidate({
                kind: 'environment',
                environment: selectedEnvironment(required(environmentId), environments.data),
                serviceId: value,
                session: ++session.current.binding,
              })
            }}
            onEndpointFinish={(values) => createEndpoint.mutate(values)}
            onEditEndpoint={(endpoint) => openEdit({ kind: 'endpoint', endpoint })}
            onCheckConnectivity={(endpointId) => checkConnectivity.mutate(endpointId)}
            actionLoading={prepareEdit.isPending || checkConnectivity.isPending}
          />
        </Col>
      </Row>
      <CatalogPagination query={apis} label="接口默认服务" />
      <ApiServiceCard
        readOnly={!canEdit}
        apis={apiItems}
        loading={apis.isLoading}
        serviceOptions={serviceOptions}
        onChange={(apiId, serviceId) => {
          const api = apiItems.find((item) => item.id === apiId)
          if (!api) return
          updateApiService.reset()
          setBindingCandidate({ kind: 'api', api, serviceId, session: ++session.current.binding })
        }}
      />
      {bindingCandidate && (
        <BindingReviewModal
          key={bindingCandidate.session}
          projectId={projectId}
          environmentId={environmentId}
          candidate={bindingCandidate}
          services={serviceItems}
          readOnly={!canEdit}
          submitting={updateDefault.isPending || updateApiService.isPending}
          error={bindingError(bindingCandidate, updateDefault.error, updateApiService.error)}
          onCancel={() => {
            session.current.binding += 1
            setBindingCandidate(undefined)
          }}
          onSave={() => {
            if (bindingCandidate.kind === 'environment') updateDefault.mutate(bindingCandidate)
            else updateApiService.mutate(bindingCandidate)
          }}
        />
      )}
      {editingTarget && (
        <RequestTargetEditModal
          key={editingTarget.session}
          projectId={projectId}
          environmentId={environmentId}
          onDirty={() => setEditDirty(true)}
          readOnly={targetIsReadOnly(canEdit, editingTarget, environmentId)}
          target={editingTarget}
          impact={impactPreview}
          services={serviceItems}
          secrets={listItems(secrets.data)}
          serviceForm={serviceEditForm}
          endpointForm={endpointEditForm}
          submitting={updateService.isPending || updateEndpoint.isPending}
          onCancel={cancelEdit}
          onServiceFinish={(values) => {
            if (editingTarget?.kind === 'service') {
              updateService.mutate({
                serviceId: editingTarget.service.id,
                input: values,
                session: editingTarget.session,
              })
            }
          }}
          onEndpointFinish={(values) => {
            if (editingTarget?.kind === 'endpoint') {
              updateEndpoint.mutate({
                endpointId: editingTarget.endpoint.id,
                input: values,
                session: editingTarget.session,
                environment: editingTarget.endpoint.environment_id,
              })
            }
          }}
        />
      )}
    </>
  )
}

function ServiceCard({
  readOnly,
  services,
  loading,
  form,
  submitting,
  onFinish,
  onEdit,
  editLoading,
  selectedId,
  onSelect,
}: {
  readOnly: boolean
  services: RequestService[]
  loading: boolean
  form: ReturnType<typeof Form.useForm<ServiceForm>>[0]
  submitting: boolean
  onFinish: (values: ServiceForm) => void
  onEdit: (service: RequestService) => void
  editLoading: boolean
  selectedId?: string
  onSelect: (id: string) => void
}) {
  const selected = services.find((item) => item.id === selectedId)
  return (
    <Card title="逻辑服务" loading={loading}>
      <div className="request-target-mobile-service-picker">
        <Select
          aria-label="逻辑服务目录"
          value={selectedId}
          options={toServiceOptions(services)}
          onChange={onSelect}
          style={{ width: '100%' }}
        />
        <Button
          disabled={!selected}
          onClick={() => {
            if (selected) onEdit(selected)
          }}
          loading={editLoading}
          style={{ marginTop: 8 }}
        >
          编辑所选逻辑服务
        </Button>
      </div>

      <Table<RequestService>
        className="request-target-table request-target-service-list"
        rowClassName={(item) => (item.id === selectedId ? 'request-target-row-selected' : '')}
        rowKey="id"
        size="small"
        pagination={false}
        dataSource={services}
        locale={{ emptyText: '暂无请求 Service' }}
        columns={[
          {
            title: '服务',
            render: (_value, item) => (
              <div>
                <Button type="link" onClick={() => onSelect(item.id)}>
                  {item.name}
                </Button>
                <Typography.Text type="secondary" style={{ display: 'block' }}>
                  {item.service_key}
                </Typography.Text>
              </div>
            ),
          },
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
      <Collapse
        style={{ marginTop: 16 }}
        items={[
          {
            key: 'create',
            label: '新建逻辑服务',
            children: (
              <Form<ServiceForm>
                name="request-service-create"
                form={form}
                layout="vertical"
                onFinish={onFinish}
                disabled={readOnly}
              >
                <Form.Item
                  name="service_key"
                  label="服务标识（跨环境保持一致）"
                  rules={[{ required: true }]}
                >
                  <Input placeholder="orders" />
                </Form.Item>
                <Form.Item name="name" label="名称" rules={[{ required: true }]}>
                  <Input placeholder="订单服务" />
                </Form.Item>
                <Form.Item name="description" label="描述">
                  <Input.TextArea rows={2} />
                </Form.Item>
                <Button
                  type="primary"
                  htmlType="submit"
                  icon={<PlusOutlined />}
                  loading={submitting}
                >
                  创建逻辑服务
                </Button>
              </Form>
            ),
          },
        ]}
      />
    </Card>
  )
}

function ApiServiceCard({
  readOnly,
  apis,
  loading,
  serviceOptions,
  onChange,
}: {
  readOnly: boolean
  apis: ApiDefinition[]
  loading: boolean
  serviceOptions: Array<{ value: string; label: string }>
  onChange: (apiId: string, serviceId: string | null) => void
}) {
  return (
    <Card title="接口默认服务（项目目录）" className="performance-card" loading={loading}>
      <Typography.Paragraph type="secondary">
        下方按项目目录分页显示接口。接口绑定优先于环境默认服务；修改先生成候选，确认后才会保存为新的接口版本，固定历史版本保持原绑定。
      </Typography.Paragraph>
      {!apis.length && <Typography.Text type="secondary">暂无 API 资产</Typography.Text>}
      <div className="request-target-api-bindings">
        {apis.map((item) => (
          <Card key={item.id} size="small">
            <Space wrap style={{ marginBottom: 12 }}>
              <Typography.Text strong>{item.name}</Typography.Text>
              <Tag>当前 v{item.current_version}</Tag>
            </Space>
            <Select
              aria-label={`${item.name} 默认服务`}
              allowClear
              disabled={readOnly}
              style={{ width: '100%', minWidth: 0 }}
              value={item.service_id ?? undefined}
              options={serviceOptions}
              placeholder="继承环境默认服务"
              onChange={(serviceId?: string) => onChange(item.id, serviceId ?? null)}
            />
          </Card>
        ))}
      </div>
    </Card>
  )
}

function RequestTargetEditModal({
  projectId,
  environmentId,
  readOnly,
  target,
  impact,
  services,
  secrets,
  serviceForm,
  endpointForm,
  submitting,
  onCancel,
  onDirty,
  onServiceFinish,
  onEndpointFinish,
}: {
  projectId: string
  environmentId: string | null
  readOnly: boolean
  target: ImpactEditTarget
  impact: ServiceTargetImpactPreview | undefined
  services: RequestService[]
  secrets: SecretMetadata[]
  serviceForm: ReturnType<typeof Form.useForm<ServiceEditForm>>[0]
  endpointForm: ReturnType<typeof Form.useForm<EndpointEditForm>>[0]
  submitting: boolean
  onDirty: () => void
  onCancel: () => void
  onServiceFinish: (values: ServiceEditForm) => void
  onEndpointFinish: (values: EndpointEditForm) => void
}) {
  const [review, setReview] = useState<
    { kind: 'service'; values: ServiceEditForm } | { kind: 'endpoint'; values: EndpointEditForm }
  >()
  const [ready, setReady] = useState(false)
  const isService = target.kind === 'service'
  const fieldsReadonly = readOnly || Boolean(review)
  const activeForm = isService ? serviceForm : endpointForm
  return (
    <Modal
      open={Boolean(target)}
      width={860}
      title={isService ? '逻辑服务影响预览 / 编辑' : '部署地址影响预览 / 编辑'}
      okText={review ? '确认保存' : '分析影响与目标'}
      mask={{ closable: false }}
      closable={!submitting}
      cancelButtonProps={{ disabled: submitting }}
      cancelText="取消"
      confirmLoading={submitting}
      okButtonProps={{ disabled: readOnly || Boolean(review && !ready) }}
      onCancel={onCancel}
      onOk={() => {
        if (!review) {
          activeForm.submit()
          return
        }
        if (review.kind === 'service') onServiceFinish(review.values)
        else onEndpointFinish(review.values)
      }}
      destroyOnHidden
    >
      {!review && <TargetImpactPanel projectId={projectId} impact={impact} />}
      {isService ? (
        <ServiceEditFields
          readOnly={fieldsReadonly}
          form={serviceForm}
          onDirty={onDirty}
          onFinish={(values) => setReview({ kind: 'service', values })}
        />
      ) : (
        <EndpointEditFields
          readOnly={fieldsReadonly}
          form={endpointForm}
          onDirty={onDirty}
          endpoint={editedEndpoint(target)}
          services={services}
          secrets={secrets}
          onFinish={(values) => setReview({ kind: 'endpoint', values })}
        />
      )}
      {review && (
        <Space orientation="vertical" className="full-width" style={{ marginTop: 16 }}>
          <Alert
            type="warning"
            title="候选已锁定，尚未保存"
            description="当前表单是待保存候选。返回修改会重新分析同一对象；确认保存才会写入服务器。"
          />
          <Button
            disabled={submitting}
            onClick={() => {
              setReview(undefined)
              setReady(false)
            }}
          >
            返回修改候选
          </Button>
          <ReviewedComparison target={target} review={review} />
          <TargetResolutionPreview
            projectId={projectId}
            environmentId={environmentId}
            change={reviewChange(target, review)}
            onReady={setReady}
          />
        </Space>
      )}
    </Modal>
  )
}

function ServiceEditFields({
  readOnly,
  form,
  onFinish,
  onDirty,
}: {
  readOnly: boolean
  form: ReturnType<typeof Form.useForm<ServiceEditForm>>[0]
  onDirty: () => void
  onFinish: (values: ServiceEditForm) => void
}) {
  return (
    <Form<ServiceEditForm>
      name="request-service-edit"
      form={form}
      layout="vertical"
      onFinish={onFinish}
      onValuesChange={onDirty}
      disabled={readOnly}
    >
      <Row gutter={16}>
        <Col xs={24} md={12}>
          <Form.Item name="name" label="名称" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
        </Col>
        <Col xs={24} md={12}>
          <Form.Item name="owner_team" label="负责团队">
            <Input />
          </Form.Item>
        </Col>
      </Row>
      <Form.Item name="service_type" label="服务协议">
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
      <Form.Item name="enabled" label="启用服务" valuePropName="checked">
        <Switch />
      </Form.Item>
    </Form>
  )
}

function EndpointEditFields({
  readOnly,
  form,
  endpoint,
  services,
  secrets,
  onFinish,
  onDirty,
}: {
  readOnly: boolean
  form: ReturnType<typeof Form.useForm<EndpointEditForm>>[0]
  endpoint: ServiceEndpoint | undefined
  services: RequestService[]
  secrets: SecretMetadata[]
  onDirty: () => void
  onFinish: (values: EndpointEditForm) => void
}) {
  const service = services.find((item) => item.id === endpoint?.service_id)
  return (
    <Form<EndpointEditForm>
      name="request-endpoint-edit"
      form={form}
      layout="vertical"
      onFinish={onFinish}
      onValuesChange={onDirty}
      disabled={readOnly}
    >
      <Descriptions size="small" column={2}>
        <Descriptions.Item label="逻辑服务">
          {service ? `${service.name} · ${service.service_key}` : '-'}
        </Descriptions.Item>
        <Descriptions.Item label="配置修订">r{endpoint?.revision ?? '-'}</Descriptions.Item>
      </Descriptions>
      <Row gutter={16}>
        <Col xs={24} md={8}>
          <Form.Item name="variant" label="地址变体（Variant）" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
        </Col>
        <Col xs={24} md={16}>
          <Form.Item name="base_url" label="部署地址" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
        </Col>
      </Row>
      <Form.Item name="enabled" label="启用地址" valuePropName="checked">
        <Switch />
      </Form.Item>
      <Collapse
        items={[
          {
            key: 'connection',
            label: '连接、TLS 与代理',
            forceRender: true,
            children: (
              <>
                <Row gutter={16}>
                  <Col xs={24} md={12}>
                    <Form.Item name="connect_timeout_ms" label="连接超时（毫秒）">
                      <InputNumber min={100} max={300_000} style={{ width: '100%' }} />
                    </Form.Item>
                  </Col>
                  <Col xs={24} md={12}>
                    <Form.Item name="read_timeout_ms" label="读取超时（毫秒）">
                      <InputNumber min={100} max={300_000} style={{ width: '100%' }} />
                    </Form.Item>
                  </Col>
                </Row>
                <Form.Item name="tls_verify" label="校验 TLS 证书" valuePropName="checked">
                  <Switch />
                </Form.Item>
                <Form.Item name="proxy_ref" label="代理引用">
                  <Input />
                </Form.Item>
              </>
            ),
          },
          {
            key: 'maps',
            label: '请求头与变量',
            forceRender: true,
            children: (
              <>
                <Form.Item name="headers_map" label="地址请求头" rules={[mapRule('headers')]}>
                  <EnvironmentMapEditor kind="headers" readOnly={readOnly} />
                </Form.Item>
                <Form.Item name="variables_map" label="地址变量" rules={[mapRule('variables')]}>
                  <EnvironmentMapEditor kind="variables" readOnly={readOnly} />
                </Form.Item>
              </>
            ),
          },
          {
            key: 'secrets',
            label: '凭据引用',
            forceRender: true,
            children: (
              <Form.Item name="secret_refs" label="仅选择引用，不展示明文">
                <Select
                  mode="multiple"
                  options={secretOptions(secrets, endpoint?.secret_refs ?? [])}
                />
              </Form.Item>
            ),
          },
          {
            key: 'health',
            label: '健康检查设置',
            forceRender: true,
            children: (
              <>
                <Form.Item name="health_check_path" label="检查相对路径">
                  <Input placeholder="/health" />
                </Form.Item>
                <Form.Item name="health_expected_status" label="预期状态码">
                  <InputNumber min={100} max={599} style={{ width: '100%' }} />
                </Form.Item>
                <Typography.Paragraph type="secondary">
                  保存和影响预览均不探测目标。需要验证时，在地址详情中显式检查连通性。
                </Typography.Paragraph>
              </>
            ),
          },
        ]}
      />
    </Form>
  )
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
    headers_map: mapValue(target.endpoint.headers),
    variables_map: mapValue(target.endpoint.variables ?? {}),
  })
}

function endpointEditPayload(values: EndpointEditForm): UpdateEndpointInput {
  const { headers_map, variables_map, ...input } = values
  return {
    ...input,
    headers: parseEnvironmentMap(headers_map, 'headers'),
    variables: parseEnvironmentMap(variables_map, 'variables'),
  }
}

function required(value: string | null | undefined): string {
  if (!value) throw new Error('项目或环境尚未选择')
  return value
}

function editable(projectId: string | null, canEdit: boolean): string {
  if (!canEdit) throw new Error('当前项目只读')
  return required(projectId)
}

function selectedEnvironment(
  environmentId: string,
  environments: Environment[] | undefined,
): Environment {
  const environment = environments?.find((item) => item.id === environmentId)
  if (!environment) throw new Error('环境不存在')
  return environment
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

function mapRule(kind: 'headers' | 'variables') {
  return {
    validator: async (_rule: unknown, value: EnvironmentMapValue) => {
      parseEnvironmentMap(value, kind)
    },
  }
}
function secretOptions(secrets: SecretMetadata[], refs: string[]) {
  const names = new Set(secrets.map((item) => item.name))
  return [
    ...secrets.map((item) => ({ value: item.name, label: item.name })),
    ...refs
      .filter((name) => !names.has(name))
      .map((name) => ({ value: name, label: `${name}（引用已不可用）` })),
  ]
}

function reviewChange(
  target: ImpactEditTarget,
  review:
    { kind: 'service'; values: ServiceEditForm } | { kind: 'endpoint'; values: EndpointEditForm },
): TargetPreviewChange {
  if (target.kind === 'service' && review.kind === 'service')
    return { kind: 'service', service_id: target.service.id, enabled: review.values.enabled }
  if (target.kind === 'endpoint' && review.kind === 'endpoint')
    return {
      kind: 'endpoint',
      endpoint_id: target.endpoint.id,
      variant: review.values.variant,
      base_url: review.values.base_url,
      enabled: review.values.enabled,
      variables: parseEnvironmentMap(review.values.variables_map, 'variables'),
    }
  throw new Error('候选类型与编辑对象不一致')
}

function chooseService(
  services: RequestService[],
  id: string | undefined,
  environment: Environment | undefined,
) {
  return (
    services.find((item) => item.id === id) ??
    services.find((item) => item.id === environment?.default_service_id) ??
    services[0]
  )
}
function bindingError(candidate: BindingCandidate, environmentError: unknown, apiError: unknown) {
  return candidate.kind === 'environment' ? environmentError : apiError
}
function editedEndpoint(target: ImpactEditTarget) {
  return target.kind === 'endpoint' ? target.endpoint : undefined
}

function hasTargetDraft(
  canEdit: boolean,
  binding: BindingCandidate | undefined,
  editDirty: boolean,
) {
  return canEdit && Boolean(binding || editDirty)
}

function targetIsReadOnly(
  canEdit: boolean,
  target: ImpactEditTarget,
  environmentId: string | null,
) {
  return (
    !canEdit || (target.kind === 'endpoint' && target.endpoint.environment_id !== environmentId)
  )
}

function ReviewedComparison({
  target,
  review,
}: {
  target: ImpactEditTarget
  review:
    { kind: 'service'; values: ServiceEditForm } | { kind: 'endpoint'; values: EndpointEditForm }
}) {
  if (target.kind === 'service' && review.kind === 'service')
    return <TargetChangeComparison kind="service" before={target.service} after={review.values} />
  if (target.kind === 'endpoint' && review.kind === 'endpoint')
    return (
      <TargetChangeComparison
        kind="endpoint"
        before={target.endpoint}
        after={endpointEditPayload(review.values)}
      />
    )
  return null
}
