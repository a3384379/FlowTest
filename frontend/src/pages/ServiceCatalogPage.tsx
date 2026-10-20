import { PlusOutlined, SafetyCertificateOutlined } from '@ant-design/icons'
import {
  Alert,
  Button,
  Card,
  Empty,
  Descriptions,
  Form,
  Input,
  Modal,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
} from 'antd'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import type { ServiceCatalogEntry, ServiceGraph } from '../features/contracts/contract-hub-service'
import {
  type ServiceCatalogInput,
  useServiceCatalog,
} from '../features/services/use-service-catalog'
import { contractServicePath } from '../features/services/contract-service-location'
import QueryFailureNotice from '../components/QueryFailureNotice'
import { useProjectContext } from '../features/projects/use-project-context'
import ServiceContractVersions from '../features/services/ServiceContractVersions'

export default function ServiceCatalogPage() {
  const { projectId } = useProjectContext()
  return <ServiceCatalogWorkspace key={projectId ?? 'none'} />
}

function ServiceCatalogWorkspace() {
  const state = useServiceCatalog()
  const [createOpen, setCreateOpen] = useState(false)
  const hasSelection = Boolean(state.selection.id || state.selection.error)
  const featureResolved = state.featureFlags.isSuccess

  return (
    <div className={`service-catalog-page${hasSelection ? ' has-selection' : ''}`}>
      <div className="page-heading">
        <div>
          <Typography.Title level={2}>服务目录</Typography.Title>
          <Typography.Text type="secondary">
            统一管理多协议服务、契约类型和上下游依赖，不保存 Credential 或 Secret。
          </Typography.Text>
        </div>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          disabled={!state.projectId || !state.featureEnabled || !state.canEdit}
          title={createPermissionHint(state)}
          onClick={() => setCreateOpen(true)}
        >
          新建服务
        </Button>
      </div>

      <QueryFailureNotice
        queries={[
          state.permissions,
          state.featureFlags,
          state.services,
          state.summary,
          state.graph,
        ]}
      />
      {state.scopeError && (
        <Alert
          type="error"
          showIcon
          title={state.scopeError}
          action={<Button onClick={state.resetScope}>重置目录范围</Button>}
        />
      )}
      <FeatureNotice resolved={featureResolved} enabled={state.featureEnabled} />

      <CatalogOverview
        loading={state.featureFlags.isLoading || state.summary.isLoading}
        values={state.summary.data}
      />
      <div
        className={`service-catalog-workspace${state.selection.id || state.selection.error ? ' has-selection' : ''}`}
      >
        <section aria-label="服务目录列表" className="service-catalog-list">
          <Card title="服务资产" loading={state.services.isLoading}>
            <Input.Search
              key={`${state.projectId}:${state.search}`}
              aria-label="搜索服务"
              allowClear
              placeholder="搜索全部服务名称、标识或描述"
              defaultValue={state.search}
              maxLength={200}
              onSearch={state.setSearch}
              style={{ marginBottom: 16 }}
            />
            <CatalogContent state={state} />
          </Card>
        </section>
        <ServiceDetails state={state} />
      </div>
      <CreateServiceDialog
        open={createOpen}
        canEdit={state.canEdit && state.featureEnabled}
        submitting={state.creating}
        onClose={() => setCreateOpen(false)}
        onCreate={async (input) => {
          if (await state.addService(input)) setCreateOpen(false)
        }}
      />
    </div>
  )
}

function FeatureNotice({ resolved, enabled }: { resolved: boolean; enabled: boolean }) {
  if (!resolved || enabled) return null
  return (
    <Alert
      type="warning"
      showIcon
      title="Contract Hub 未启用"
      description="服务目录保留稳定路由；由管理员启用 Contract Hub 后才会读取或写入服务资产。"
      className="service-catalog-alert"
    />
  )
}

function CatalogContent({ state }: { state: ReturnType<typeof useServiceCatalog> }) {
  if (!state.featureEnabled) return <Empty description="功能未启用" />
  if (state.scopeError || state.services.isError) return null
  return <ServiceTable state={state} />
}

type CatalogOverviewProps = {
  loading: boolean
  values:
    | {
        service_count: number
        openapi_contract_count: number
        pact_contract_count: number
        failed_verification_count: number
      }
    | undefined
}

function CatalogOverview({ loading, values }: CatalogOverviewProps) {
  const serviceCount = summaryValue(values, 'service_count')
  const openapiCount = summaryValue(values, 'openapi_contract_count')
  const pactCount = summaryValue(values, 'pact_contract_count')
  const failedCount = summaryValue(values, 'failed_verification_count')
  return (
    <div className="stat-grid service-catalog-overview">
      <Card loading={loading}>
        <Statistic title="服务数量" value={serviceCount} />
      </Card>
      <Card loading={loading}>
        <Statistic title="OpenAPI 契约" value={openapiCount} />
      </Card>
      <Card loading={loading}>
        <Statistic title="Pact 契约" value={pactCount} />
      </Card>
      <Card loading={loading}>
        <Statistic
          title="失败验证"
          value={failedCount}
          prefix={<SafetyCertificateOutlined />}
          styles={{ content: failedCount ? { color: '#cf1322' } : undefined }}
        />
      </Card>
    </div>
  )
}

function summaryValue(
  values: CatalogOverviewProps['values'],
  key: keyof NonNullable<CatalogOverviewProps['values']>,
): number | '—' {
  return values ? values[key] : '—'
}

function ServiceTable({ state }: { state: ReturnType<typeof useServiceCatalog> }) {
  const profiles = serviceProfiles(state.graph.data)
  return (
    <Table
      rowKey="id"
      dataSource={state.services.data?.items ?? []}
      locale={{ emptyText: '暂无匹配服务' }}
      pagination={{
        current: state.page,
        pageSize: 20,
        total: state.services.data?.total ?? 0,
        showSizeChanger: false,
        onChange: state.setPage,
        showTotal: (total) => `匹配 ${total} 个服务`,
      }}
      rowClassName={(record) =>
        record.id === state.selection.id ? 'service-catalog-row-focused' : ''
      }
      columns={[
        {
          title: '服务',
          render: (_: unknown, service: ServiceCatalogEntry) => (
            <Space orientation="vertical" size={0}>
              <Button
                type="link"
                style={{
                  padding: 0,
                  maxWidth: '100%',
                  whiteSpace: 'normal',
                  height: 'auto',
                  textAlign: 'left',
                }}
                onClick={() => state.selectService(service.id)}
              >
                {service.display_name}
              </Button>
              <Typography.Text type="secondary" code>
                {service.service_key}
              </Typography.Text>
              <Typography.Text type="secondary">
                {dependencyRole(profiles.get(service.id))}
              </Typography.Text>
            </Space>
          ),
        },
        {
          title: '契约',
          width: 110,
          render: (_: unknown, service: ServiceCatalogEntry) => (
            <ContractKindTags kinds={profiles.get(service.id)?.kinds} />
          ),
        },
      ]}
    />
  )
}

function ServiceDetails({ state }: { state: ReturnType<typeof useServiceCatalog> }) {
  return (
    <section aria-label="选中服务详情" className="service-catalog-detail">
      <Card
        title="服务详情"
        loading={state.featureEnabled && Boolean(state.selection.id) && state.selected.isPending}
        extra={
          (state.selection.id || state.selection.error) && (
            <Button onClick={() => state.selectService(null)}>返回服务列表</Button>
          )
        }
      >
        <ServiceDetailsBody state={state} />
      </Card>
    </section>
  )
}

function ServiceDetailsBody({ state }: { state: ReturnType<typeof useServiceCatalog> }) {
  const selected =
    state.featureEnabled && state.selected.isSuccess ? state.selected.data : undefined
  return (
    <>
      {state.selection.error && <Alert type="error" showIcon title={state.selection.error} />}
      <QueryFailureNotice queries={[state.selected]} />
      {!state.selection.id && !state.selection.error && (
        <Empty description="选择一个服务查看详情" />
      )}
      {selected && <ServiceDetailsContent state={state} service={selected} />}
    </>
  )
}

function ServiceDetailsContent({
  state,
  service,
}: {
  state: ReturnType<typeof useServiceCatalog>
  service: ServiceCatalogEntry
}) {
  const profile = serviceProfiles(state.graph.data).get(service.id)
  return (
    <Space orientation="vertical" size={16} style={{ width: '100%' }}>
      <Typography.Title level={4} style={{ margin: 0 }}>
        {service.display_name}
      </Typography.Title>
      <Descriptions
        column={1}
        size="small"
        bordered
        items={[
          {
            key: 'id',
            label: '目录服务 ID',
            children: (
              <Typography.Text code copyable>
                {service.id}
              </Typography.Text>
            ),
          },
          {
            key: 'key',
            label: '服务标识',
            children: <Typography.Text code>{service.service_key}</Typography.Text>,
          },
          { key: 'description', label: '描述', children: service.description || '未填写' },
          {
            key: 'kinds',
            label: '已知契约',
            children: <ContractKindTags kinds={profile?.kinds} />,
          },
          {
            key: 'role',
            label: '依赖角色',
            children: profile ? dependencyRole(profile) : '摘要未提供',
          },
          {
            key: 'updated',
            label: '更新时间（北京时间）',
            children: formatShanghaiTime(service.updated_at),
          },
        ]}
      />
      <Typography.Paragraph type="secondary" style={{ margin: 0 }}>
        这是契约目录服务；请求目标 Service 使用独立身份。下方展示已登记的 Pact
        依赖及最近已知验证，不能据此推断部署安全。下方版本记录来自固定的契约导入；完整验证记录请进入契约页面。
      </Typography.Paragraph>
      <Space wrap>
        <Link to={contractServicePath(state.projectId!, 'contracts', service.id)}>
          查看服务契约
        </Link>
        <Link to={contractServicePath(state.projectId!, 'impact', service.id)}>查看服务影响</Link>
      </Space>
      <ServiceContractVersions projectId={state.projectId!} serviceId={service.id} />
      <ServiceDependencies
        service={service}
        graph={state.graph.data}
        onSelect={state.selectService}
      />
    </Space>
  )
}

function ServiceDependencies({
  service,
  graph,
  onSelect,
}: {
  service: ServiceCatalogEntry
  graph?: ServiceGraph
  onSelect: (id: string) => void
}) {
  if (!graph) return <Typography.Text type="secondary">依赖摘要尚未提供</Typography.Text>
  const edges = graph.edges.filter(
    (edge) => edge.consumer_service_id === service.id || edge.provider_service_id === service.id,
  )
  const names = new Map(graph.nodes.map((node) => [node.id, node.display_name]))
  return (
    <Table
      size="small"
      dataSource={edges}
      rowKey={(edge) => `${edge.consumer_service_id}:${edge.provider_service_id}`}
      title={() => '已登记 Pact 依赖'}
      locale={{ emptyText: '未记录 Pact 依赖' }}
      pagination={{ pageSize: 5, hideOnSinglePage: true }}
      columns={[
        {
          title: '关联服务',
          render: (_: unknown, edge: ServiceGraph['edges'][number]) => {
            const upstream = edge.provider_service_id === service.id
            const id = upstream ? edge.consumer_service_id : edge.provider_service_id
            return (
              <Space orientation="vertical" size={0}>
                <Button type="link" onClick={() => onSelect(id)}>
                  {names.get(id) ?? id}
                </Button>
                <Typography.Text type="secondary">
                  {upstream ? '调用本服务' : '本服务调用'}
                </Typography.Text>
              </Space>
            )
          },
        },
        {
          title: '已知文档 / 消费者版本',
          render: (_: unknown, edge: ServiceGraph['edges'][number]) =>
            `${edge.pact_contract_count} / ${edge.latest_consumer_version}`,
        },
        {
          title: '最近验证',
          dataIndex: 'latest_status',
          render: (status: ServiceGraph['edges'][number]['latest_status']) => (
            <Tag color={status === 'passed' ? 'green' : status === 'failed' ? 'red' : undefined}>
              {status === 'passed' ? '通过' : status === 'failed' ? '失败' : '待验证'}
            </Tag>
          ),
        },
      ]}
    />
  )
}

type ServiceProfile = {
  kinds: Array<'openapi' | 'pact'>
  consumer: boolean
  provider: boolean
  edgeCount: number
}

function serviceProfiles(graph: ServiceGraph | undefined): Map<string, ServiceProfile> {
  const profiles = new Map<string, ServiceProfile>()
  for (const node of graph?.nodes ?? []) {
    profiles.set(node.id, {
      kinds: node.contract_kinds,
      consumer: false,
      provider: false,
      edgeCount: 0,
    })
  }
  for (const edge of graph?.edges ?? []) {
    updateProfile(profiles, edge.consumer_service_id, 'consumer')
    updateProfile(profiles, edge.provider_service_id, 'provider')
  }
  return profiles
}

function updateProfile(
  profiles: Map<string, ServiceProfile>,
  serviceId: string,
  role: 'consumer' | 'provider',
): void {
  const profile = profiles.get(serviceId) ?? {
    kinds: [],
    consumer: false,
    provider: false,
    edgeCount: 0,
  }
  profiles.set(serviceId, { ...profile, [role]: true, edgeCount: profile.edgeCount + 1 })
}

function ContractKindTags({ kinds }: { kinds?: Array<'openapi' | 'pact'> }) {
  if (!kinds) return <Tag>摘要未提供</Tag>
  if (!kinds.length) return <Tag>待关联</Tag>
  return (
    <Space size={4} wrap>
      {kinds.map((kind) => (
        <Tag key={kind} color={kind === 'openapi' ? 'blue' : 'purple'}>
          {kind === 'openapi' ? 'OpenAPI' : 'Pact'}
        </Tag>
      ))}
    </Space>
  )
}

function dependencyRole(profile: ServiceProfile | undefined): string {
  if (profile?.consumer && profile.provider) return '消费方 / 提供方'
  if (profile?.consumer) return '消费方'
  if (profile?.provider) return '提供方'
  return '未关联'
}

function CreateServiceDialog({
  open,
  submitting,
  canEdit,
  onClose,
  onCreate,
}: {
  open: boolean
  submitting: boolean
  canEdit: boolean
  onClose: () => void
  onCreate: (input: ServiceCatalogInput) => Promise<void>
}) {
  const [form] = Form.useForm<ServiceCatalogInput>()
  return (
    <Modal
      title="新建服务"
      open={open}
      okText="登记服务"
      cancelText="取消"
      confirmLoading={submitting}
      okButtonProps={{ disabled: !canEdit }}
      onCancel={onClose}
      onOk={() => form.submit()}
      afterOpenChange={(visible) => {
        if (!visible) form.resetFields()
      }}
    >
      <Form
        disabled={!canEdit}
        form={form}
        layout="vertical"
        preserve={false}
        initialValues={{ description: '' }}
        onFinish={(values) => void onCreate(values)}
      >
        <Form.Item
          label="服务标识"
          name="service_key"
          extra="小写字母开头，可使用数字、点、下划线或连字符。"
          rules={[
            { required: true, message: '请输入服务标识' },
            {
              pattern: /^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$/,
              message: '服务标识格式不正确',
            },
            { min: 2, max: 80 },
          ]}
        >
          <Input placeholder="orders-api" />
        </Form.Item>
        <Form.Item
          label="显示名称"
          name="display_name"
          rules={[{ required: true, whitespace: true, max: 160 }]}
        >
          <Input placeholder="订单服务" />
        </Form.Item>
        <Form.Item label="服务描述" name="description" rules={[{ max: 2000 }]}>
          <Input.TextArea rows={4} showCount maxLength={2000} />
        </Form.Item>
      </Form>
    </Modal>
  )
}

function formatShanghaiTime(value: string): string {
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(new Date(value))
}

function createPermissionHint(state: ReturnType<typeof useServiceCatalog>): string | undefined {
  if (state.permissions.isPending) return '正在读取项目权限'
  if (state.permissions.isError) return '权限读取失败，请重试'
  return state.canEdit ? undefined : '当前权限不能登记服务'
}
