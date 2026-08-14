import { PlusOutlined, SafetyCertificateOutlined } from '@ant-design/icons'
import {
  Alert,
  Button,
  Card,
  Empty,
  Form,
  Input,
  Modal,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
} from 'antd'
import { useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import type { ServiceCatalogEntry, ServiceGraph } from '../features/contracts/contract-hub-service'
import {
  type ServiceCatalogInput,
  useServiceCatalog,
} from '../features/services/use-service-catalog'
import { projectPath } from '../features/projects/project-routing'
import { apiErrorMessage } from '../lib/api'

export default function ServiceCatalogPage() {
  const state = useServiceCatalog()
  const [searchParams] = useSearchParams()
  const [query, setQuery] = useState('')
  const [createOpen, setCreateOpen] = useState(false)
  const focusedId = focusedServiceId(searchParams.get('focus'))
  const serviceItems = state.services.data?.items
  const filtered = useMemo(() => filterServices(serviceItems ?? [], query), [query, serviceItems])
  const error = firstError([
    state.featureFlags.error,
    state.services.error,
    state.summary.error,
    state.graph.error,
  ])
  const featureResolved = state.featureFlags.isSuccess

  return (
    <>
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
          title={!state.canEdit ? '查看者无权登记服务' : undefined}
          onClick={() => setCreateOpen(true)}
        >
          新建服务
        </Button>
      </div>

      {error && (
        <Alert
          type="error"
          showIcon
          title="服务目录加载失败"
          description={apiErrorMessage(error)}
          className="service-catalog-alert"
        />
      )}
      <FeatureNotice resolved={featureResolved} enabled={state.featureEnabled} />

      <CatalogOverview
        loading={state.featureFlags.isLoading || state.summary.isLoading}
        values={state.summary.data}
      />
      <Card
        title="服务资产"
        loading={state.services.isLoading || state.graph.isLoading}
        extra={
          <Input.Search
            aria-label="搜索服务"
            allowClear
            placeholder="搜索名称、标识或描述"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        }
      >
        <CatalogContent
          enabled={state.featureEnabled}
          projectId={state.projectId}
          items={filtered}
          graph={state.graph.data}
          focusedId={focusedId}
        />
      </Card>
      <CreateServiceDialog
        open={createOpen}
        submitting={state.creating}
        onClose={() => setCreateOpen(false)}
        onCreate={async (input) => {
          if (await state.addService(input)) setCreateOpen(false)
        }}
      />
    </>
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

function CatalogContent({
  enabled,
  projectId,
  items,
  graph,
  focusedId,
}: {
  enabled: boolean
  projectId: string | null
  items: ServiceCatalogEntry[]
  graph: ServiceGraph | undefined
  focusedId: string | null
}) {
  if (!enabled) return <Empty description="功能未启用" />
  return <ServiceTable projectId={projectId} items={items} graph={graph} focusedId={focusedId} />
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
): number {
  return values ? values[key] : 0
}

function ServiceTable({
  projectId,
  items,
  graph,
  focusedId,
}: {
  projectId: string | null
  items: ServiceCatalogEntry[]
  graph: ServiceGraph | undefined
  focusedId: string | null
}) {
  if (!items.length) return <Empty description="暂无匹配服务" />
  const profiles = serviceProfiles(graph)
  return (
    <Table
      rowKey="id"
      pagination={{ pageSize: 10 }}
      dataSource={items}
      rowClassName={(record) => (record.id === focusedId ? 'service-catalog-row-focused' : '')}
      columns={[
        {
          title: '服务',
          render: (_, service) => (
            <Space orientation="vertical" size={0}>
              <Typography.Text strong>{service.display_name}</Typography.Text>
              <Typography.Text type="secondary" code>
                {service.service_key}
              </Typography.Text>
            </Space>
          ),
        },
        {
          title: '描述',
          dataIndex: 'description',
          ellipsis: true,
          render: (value: string) => value || '—',
        },
        {
          title: '契约类型',
          width: 180,
          render: (_, service) => (
            <ContractKindTags kinds={profiles.get(service.id)?.kinds ?? []} />
          ),
        },
        {
          title: '依赖角色',
          width: 140,
          render: (_, service) => dependencyRole(profiles.get(service.id)),
        },
        {
          title: '相关依赖',
          width: 110,
          render: (_, service) => profiles.get(service.id)?.edgeCount ?? 0,
        },
        {
          title: '更新时间',
          dataIndex: 'updated_at',
          width: 170,
          render: (value: string) => formatShanghaiTime(value),
        },
        {
          title: '操作',
          width: 130,
          render: (_, service) =>
            projectId ? (
              <Space>
                <Link
                  to={`${projectPath(projectId, 'contracts')}?focus=contract_service:${service.id}`}
                >
                  契约
                </Link>
                <Link to={`${projectPath(projectId, 'impact')}?service_id=${service.id}`}>
                  影响
                </Link>
              </Space>
            ) : null,
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

function ContractKindTags({ kinds }: { kinds: Array<'openapi' | 'pact'> }) {
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
  onClose,
  onCreate,
}: {
  open: boolean
  submitting: boolean
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
      onCancel={onClose}
      onOk={() => form.submit()}
      afterOpenChange={(visible) => {
        if (!visible) form.resetFields()
      }}
    >
      <Form
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

function filterServices(items: ServiceCatalogEntry[], query: string): ServiceCatalogEntry[] {
  const normalized = query.trim().toLocaleLowerCase('zh-CN')
  if (!normalized) return items
  return items.filter((item) =>
    [item.display_name, item.service_key, item.description].some((value) =>
      value.toLocaleLowerCase('zh-CN').includes(normalized),
    ),
  )
}

function focusedServiceId(value: string | null): string | null {
  if (!value?.startsWith('contract_service:')) return null
  return value.slice('contract_service:'.length) || null
}

function firstError(errors: unknown[]): unknown {
  return errors.find((error) => error !== null && error !== undefined)
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
