import {
  ApartmentOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  CloudDownloadOutlined,
  FileProtectOutlined,
  PlusOutlined,
  SafetyCertificateOutlined,
  UploadOutlined,
} from '@ant-design/icons'
import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Form,
  Input,
  Modal,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tabs,
  Tag,
  Typography,
  Upload,
} from 'antd'
import { useState } from 'react'

import type { ContractRun } from '../lib/api'
import type {
  CompatibilityMatrix,
  ContractHubSummary,
  DeploymentCheck,
  PactContract,
  PactImportInput,
  ServiceCatalogEntry,
  ServiceGraph,
} from '../features/contracts/contract-hub-service'
import { useContractHub } from '../features/contracts/use-contract-hub'

type ServiceForm = { service_key: string; display_name: string; description: string }
type PactForm = { consumer_version: string; consumer: string; provider: string }
type OpenapiForm = { provider_service_id: string; provider_version: string }
type VerificationForm = {
  pact_id: string
  provider_version: string
  target_base_url: string
}

export default function ContractHubPage() {
  const [providerId, setProviderId] = useState<string | null>(null)
  const state = useContractHub(providerId)
  const services = pageItems(state.services.data)
  const pacts = pageItems(state.pacts.data)
  const openapiRuns = pageItems(state.openapiRuns.data)
  const checks = pageItems(state.checks.data)
  const providers = providerServices(services, pacts)
  const [serviceDialog, setServiceDialog] = useState(false)
  const [pactDialog, setPactDialog] = useState<'upload' | 'broker' | null>(null)
  const [openapiDialog, setOpenapiDialog] = useState(false)
  const [verificationDialog, setVerificationDialog] = useState(false)

  return (
    <>
      <ContractHubHeader
        brokerAvailable={Boolean(state.summary.data?.broker_available)}
        hasPacts={pacts.length > 0}
        onService={() => setServiceDialog(true)}
        onOpenapi={() => setOpenapiDialog(true)}
        onPact={() => setPactDialog('upload')}
        onBroker={() => setPactDialog('broker')}
        onVerify={() => setVerificationDialog(true)}
      />
      <Alert
        showIcon
        type="info"
        className="page-alert"
        title="Pact 文档按不可信输入处理"
        description="仅支持 HTTP Exact Matcher；拒绝 Secret、Cookie、任意 Matching Rule、Generator 和 Plugin。Provider 请求继续受项目出站策略约束。"
      />
      <ContractOverview summary={state.summary.data} loading={state.summary.isLoading} />
      <CompatibilityPanel
        providers={providers}
        providerId={providerId}
        matrix={state.matrix.data}
        checks={checks}
        loading={state.matrix.isLoading}
        checking={state.checking}
        onProviderChange={setProviderId}
        onRunCheck={state.runCheck}
      />
      <div className="contract-hub-grid">
        <ServiceGraphPanel graph={state.graph.data} loading={state.graph.isLoading} />
        <FailedEvidencePanel checks={checks} />
      </div>
      <UnifiedContractsPanel
        services={services}
        pacts={pacts}
        openapiRuns={openapiRuns}
        loading={state.pacts.isLoading || state.openapiRuns.isLoading}
      />
      <ServiceDialog
        open={serviceDialog}
        submitting={state.creatingService}
        onClose={() => setServiceDialog(false)}
        onSubmit={async (input) => {
          if (await state.createService(input)) setServiceDialog(false)
        }}
      />
      <PactDialog
        key={pactDialog ?? 'closed'}
        mode={pactDialog}
        submitting={state.importing}
        onClose={() => setPactDialog(null)}
        onSubmit={async (input) => {
          if (await state.importPact(input)) setPactDialog(null)
        }}
      />
      <OpenapiDialog
        open={openapiDialog}
        services={services}
        submitting={state.importing}
        onClose={() => setOpenapiDialog(false)}
        onSubmit={async (input) => {
          if (await state.importOpenapi(input)) setOpenapiDialog(false)
        }}
      />
      <VerificationDialog
        open={verificationDialog}
        pacts={pacts}
        submitting={state.verifying}
        onClose={() => setVerificationDialog(false)}
        onSubmit={async (input) => {
          if (await state.verifyProvider(input)) setVerificationDialog(false)
        }}
      />
    </>
  )
}

function ContractHubHeader({
  brokerAvailable,
  hasPacts,
  onService,
  onOpenapi,
  onPact,
  onBroker,
  onVerify,
}: {
  brokerAvailable: boolean
  hasPacts: boolean
  onService: () => void
  onOpenapi: () => void
  onPact: () => void
  onBroker: () => void
  onVerify: () => void
}) {
  return (
    <div className="page-heading">
      <div>
        <Space align="center">
          <Typography.Title level={2}>契约中心</Typography.Title>
          <Tag color="geekblue">V3 · S27</Tag>
        </Space>
        <Typography.Text type="secondary">
          统一管理 OpenAPI 与 Consumer-Driven Contract，形成服务依赖和可审计的发布兼容判断。
        </Typography.Text>
      </div>
      <Space wrap>
        <Button icon={<PlusOutlined />} onClick={onService}>
          登记服务
        </Button>
        <Button icon={<UploadOutlined />} onClick={onOpenapi}>
          导入 OpenAPI
        </Button>
        <Button icon={<UploadOutlined />} onClick={onPact}>
          导入 Pact
        </Button>
        {brokerAvailable ? (
          <Button icon={<CloudDownloadOutlined />} onClick={onBroker}>
            从 Broker 导入
          </Button>
        ) : null}
        <Button
          type="primary"
          icon={<SafetyCertificateOutlined />}
          disabled={!hasPacts}
          onClick={onVerify}
        >
          执行提供方验证
        </Button>
      </Space>
    </div>
  )
}

export function ContractOverview({
  summary,
  loading,
}: {
  summary?: ContractHubSummary
  loading: boolean
}) {
  const items = [
    ['OpenAPI 契约', summary?.openapi_contract_count ?? 0, <FileProtectOutlined />, undefined],
    ['Pact 契约', summary?.pact_contract_count ?? 0, <ApartmentOutlined />, undefined],
    ['待验证', summary?.pending_verification_count ?? 0, undefined, '#d97706'],
    ['破坏性变更', summary?.breaking_change_count ?? 0, undefined, '#dc2626'],
  ] as const
  return (
    <Row gutter={16} className="performance-overview">
      {items.map(([title, value, prefix, color]) => (
        <Col span={6} key={title}>
          <Card loading={loading}>
            <Statistic
              title={title}
              value={value}
              prefix={prefix}
              styles={{ content: { color } }}
            />
          </Card>
        </Col>
      ))}
    </Row>
  )
}

export function CompatibilityPanel({
  providers,
  providerId,
  matrix,
  checks,
  loading,
  checking,
  onProviderChange,
  onRunCheck,
}: {
  providers: ServiceCatalogEntry[]
  providerId: string | null
  matrix?: CompatibilityMatrix
  checks: DeploymentCheck[]
  loading: boolean
  checking: boolean
  onProviderChange: (value: string) => void
  onRunCheck: (input: { providerServiceId: string; providerVersion: string }) => Promise<boolean>
}) {
  const [providerVersion, setProviderVersion] = useState('')
  const selectedCheck = checks.find(
    (item) =>
      item.provider_service_id === providerId && item.provider_version === providerVersion.trim(),
  )
  const columns = [
    {
      title: '消费者版本',
      key: 'consumer',
      render: (_: unknown, row: CompatibilityMatrix['rows'][number]) => (
        <Typography.Text strong>
          {row.consumer_name} · {row.consumer_version}
        </Typography.Text>
      ),
    },
    ...(matrix?.provider_versions ?? []).map((version) => ({
      title: `${matrix?.provider_name ?? 'Provider'} ${version}`,
      key: version,
      render: (_: unknown, row: CompatibilityMatrix['rows'][number]) => (
        <CompatibilityStatus
          status={row.cells.find((cell) => cell.provider_version === version)?.status ?? 'pending'}
        />
      ),
    })),
  ]
  return (
    <Card
      className="performance-card"
      title="部署兼容矩阵"
      loading={loading}
      extra={
        <Select
          aria-label="提供方服务"
          placeholder="选择提供方"
          value={providerId ?? undefined}
          onChange={onProviderChange}
          options={providers.map((item) => ({ value: item.id, label: item.display_name }))}
          className="contract-provider-select"
        />
      }
    >
      {providerId && matrix?.rows.length ? (
        <Table
          rowKey="pact_contract_version_id"
          size="small"
          pagination={false}
          columns={columns}
          dataSource={matrix.rows}
          scroll={{ x: true }}
        />
      ) : (
        <Empty description={providerId ? '该提供方暂无 Pact 契约' : '请先选择提供方'} />
      )}
      <Space wrap className="contract-release-check">
        <Input
          aria-label="待发布提供方版本"
          placeholder="待发布版本，例如 2.4.0"
          value={providerVersion}
          onChange={(event) => setProviderVersion(event.target.value)}
        />
        <Button
          type="primary"
          loading={checking}
          disabled={!providerId || !providerVersion.trim()}
          onClick={() =>
            providerId &&
            void onRunCheck({
              providerServiceId: providerId,
              providerVersion: providerVersion.trim(),
            })
          }
        >
          判断是否可安全发布
        </Button>
        {selectedCheck ? <DecisionTag decision={selectedCheck.decision} /> : null}
      </Space>
    </Card>
  )
}

export function ServiceGraphPanel({ graph, loading }: { graph?: ServiceGraph; loading: boolean }) {
  const names = new Map(graph?.nodes.map((node) => [node.id, node.display_name]))
  return (
    <Card title="服务依赖契约" loading={loading} className="performance-card">
      {graph?.edges.length ? (
        <div className="contract-graph" aria-label="服务依赖图">
          {graph.edges.map((edge) => (
            <div
              className={`contract-graph-edge contract-graph-edge-${edge.latest_status}`}
              key={`${edge.consumer_service_id}-${edge.provider_service_id}`}
            >
              <div className="contract-graph-node">
                <strong>{names.get(edge.consumer_service_id)}</strong>
                <span>Consumer · {edge.latest_consumer_version}</span>
              </div>
              <div className="contract-graph-arrow">→</div>
              <div className="contract-graph-node">
                <strong>{names.get(edge.provider_service_id)}</strong>
                <span>Provider · {edge.pact_contract_count} 份 Pact</span>
              </div>
              <CompatibilityStatus status={edge.latest_status} />
            </div>
          ))}
        </div>
      ) : (
        <Empty description="导入 Pact 后生成服务依赖图" />
      )}
    </Card>
  )
}

export function FailedEvidencePanel({ checks }: { checks: DeploymentCheck[] }) {
  const failed = checks.filter((item) => item.decision === 'unsafe')
  return (
    <Card title="发布判断证据" className="performance-card">
      {failed.length ? (
        <Space orientation="vertical" className="full-width">
          {failed.slice(0, 5).map((item) => (
            <Alert
              key={item.id}
              type="error"
              showIcon
              title={`Provider ${item.provider_version} 不可安全发布`}
              description={`${evidenceCount(item.evidence, 'blockers')} 项阻断证据 · ${formatDate(item.created_at)}`}
            />
          ))}
        </Space>
      ) : (
        <Empty description="暂无不可安全发布的判断" />
      )}
    </Card>
  )
}

export function UnifiedContractsPanel({
  services,
  pacts,
  openapiRuns,
  loading,
}: {
  services: ServiceCatalogEntry[]
  pacts: PactContract[]
  openapiRuns: ContractRun[]
  loading: boolean
}) {
  const names = new Map(services.map((item) => [item.id, item.display_name]))
  return (
    <Card title="统一契约资产" loading={loading} className="performance-card">
      <Tabs
        items={[
          {
            key: 'openapi',
            label: `OpenAPI（${openapiRuns.length}）`,
            children: (
              <Table
                rowKey="id"
                size="small"
                pagination={false}
                dataSource={openapiRuns}
                columns={[
                  { title: '文档', dataIndex: 'source_name' },
                  {
                    title: '提供方版本',
                    render: (_: unknown, item: ContractRun) =>
                      item.provider_service_id
                        ? `${names.get(item.provider_service_id) ?? '未知服务'} · ${item.provider_version}`
                        : '未绑定',
                  },
                  {
                    title: '破坏性变更',
                    render: (_: unknown, item: ContractRun) => (
                      <Tag color={item.breaking_changes.length ? 'red' : 'green'}>
                        {item.breaking_changes.length ? `${item.breaking_changes.length} 项` : '无'}
                      </Tag>
                    ),
                  },
                  {
                    title: 'Schema 覆盖率',
                    render: (_: unknown, item: ContractRun) =>
                      `${item.coverage.schema_coverage_percent.toFixed(1)}%`,
                  },
                  {
                    title: '导入时间',
                    render: (_: unknown, item: ContractRun) => formatDate(item.created_at),
                  },
                ]}
              />
            ),
          },
          {
            key: 'pact',
            label: `Pact（${pacts.length}）`,
            children: (
              <Table
                rowKey="id"
                size="small"
                pagination={false}
                dataSource={pacts}
                columns={[
                  {
                    title: 'Consumer → Provider',
                    render: (_: unknown, item: PactContract) =>
                      `${item.consumer_name} → ${item.provider_name}`,
                  },
                  { title: '消费者版本', dataIndex: 'consumer_version' },
                  {
                    title: 'Interaction',
                    dataIndex: 'interaction_count',
                    align: 'right' as const,
                  },
                  {
                    title: '来源',
                    render: (_: unknown, item: PactContract) => (
                      <Tag color={item.source_type === 'broker' ? 'blue' : undefined}>
                        {item.source_type === 'broker' ? 'Pact Broker' : '本地上传'}
                      </Tag>
                    ),
                  },
                  {
                    title: '导入时间',
                    render: (_: unknown, item: PactContract) => formatDate(item.created_at),
                  },
                ]}
              />
            ),
          },
        ]}
      />
    </Card>
  )
}

function ServiceDialog({
  open,
  submitting,
  onClose,
  onSubmit,
}: {
  open: boolean
  submitting: boolean
  onClose: () => void
  onSubmit: (input: ServiceForm) => Promise<void>
}) {
  const [form] = Form.useForm<ServiceForm>()
  return (
    <Modal
      title="登记服务"
      open={open}
      confirmLoading={submitting}
      okText="登记"
      cancelText="取消"
      onCancel={onClose}
      onOk={() => void form.validateFields().then(onSubmit)}
      afterClose={() => form.resetFields()}
    >
      <Form form={form} layout="vertical">
        <Form.Item name="service_key" label="服务标识" rules={[{ required: true }]}>
          <Input placeholder="orders-api" />
        </Form.Item>
        <Form.Item name="display_name" label="显示名称" rules={[{ required: true }]}>
          <Input placeholder="订单服务" />
        </Form.Item>
        <Form.Item name="description" label="说明" initialValue="">
          <Input.TextArea rows={3} />
        </Form.Item>
      </Form>
    </Modal>
  )
}

function PactDialog({
  mode,
  submitting,
  onClose,
  onSubmit,
}: {
  mode: 'upload' | 'broker' | null
  submitting: boolean
  onClose: () => void
  onSubmit: (input: PactImportInput) => Promise<void>
}) {
  const [form] = Form.useForm<PactForm>()
  const [file, setFile] = useState<File | null>(null)
  const submit = async () => {
    const values = await form.validateFields()
    if (mode === 'broker') {
      await onSubmit({
        kind: 'broker',
        consumer: values.consumer,
        provider: values.provider,
        consumerVersion: values.consumer_version,
      })
    } else if (file) {
      await onSubmit({ kind: 'upload', document: file, consumerVersion: values.consumer_version })
    }
  }
  return (
    <Modal
      title={mode === 'broker' ? '从 Pact Broker 导入' : '导入 Pact 文档'}
      open={mode !== null}
      confirmLoading={submitting}
      okText="导入"
      cancelText="取消"
      okButtonProps={{ disabled: mode === 'upload' && !file }}
      onCancel={onClose}
      onOk={() => void submit()}
      afterClose={() => {
        form.resetFields()
        setFile(null)
      }}
    >
      <Form form={form} layout="vertical">
        {mode === 'broker' ? (
          <>
            <Form.Item name="consumer" label="Consumer" rules={[{ required: true }]}>
              <Input />
            </Form.Item>
            <Form.Item name="provider" label="Provider" rules={[{ required: true }]}>
              <Input />
            </Form.Item>
          </>
        ) : (
          <Form.Item label="Pact JSON" required>
            <Upload
              accept="application/json,.json"
              maxCount={1}
              beforeUpload={(selected) => {
                setFile(selected)
                return false
              }}
              onRemove={() => setFile(null)}
            >
              <Button icon={<UploadOutlined />}>选择 Pact 文档</Button>
            </Upload>
          </Form.Item>
        )}
        <Form.Item name="consumer_version" label="消费者版本" rules={[{ required: true }]}>
          <Input placeholder="web-42" />
        </Form.Item>
      </Form>
    </Modal>
  )
}

function OpenapiDialog({
  open,
  services,
  submitting,
  onClose,
  onSubmit,
}: {
  open: boolean
  services: ServiceCatalogEntry[]
  submitting: boolean
  onClose: () => void
  onSubmit: (input: {
    file: File
    providerServiceId: string
    providerVersion: string
  }) => Promise<void>
}) {
  const [form] = Form.useForm<OpenapiForm>()
  const [file, setFile] = useState<File | null>(null)
  return (
    <Modal
      title="导入并绑定 OpenAPI"
      open={open}
      confirmLoading={submitting}
      okText="导入"
      cancelText="取消"
      okButtonProps={{ disabled: !file }}
      onCancel={onClose}
      onOk={() =>
        void form.validateFields().then((values) =>
          file
            ? onSubmit({
                file,
                providerServiceId: values.provider_service_id,
                providerVersion: values.provider_version,
              })
            : undefined,
        )
      }
      afterClose={() => {
        form.resetFields()
        setFile(null)
      }}
    >
      <Form form={form} layout="vertical">
        <Form.Item label="OpenAPI 文档" required>
          <Upload
            maxCount={1}
            beforeUpload={(selected) => {
              setFile(selected)
              return false
            }}
            onRemove={() => setFile(null)}
          >
            <Button icon={<UploadOutlined />}>选择 OpenAPI 文档</Button>
          </Upload>
        </Form.Item>
        <Form.Item name="provider_service_id" label="提供方服务" rules={[{ required: true }]}>
          <Select
            options={services.map((item) => ({ value: item.id, label: item.display_name }))}
          />
        </Form.Item>
        <Form.Item name="provider_version" label="提供方版本" rules={[{ required: true }]}>
          <Input placeholder="2.4.0" />
        </Form.Item>
      </Form>
    </Modal>
  )
}

function VerificationDialog({
  open,
  pacts,
  submitting,
  onClose,
  onSubmit,
}: {
  open: boolean
  pacts: PactContract[]
  submitting: boolean
  onClose: () => void
  onSubmit: (input: {
    pactId: string
    providerVersion: string
    targetBaseUrl: string
  }) => Promise<void>
}) {
  const [form] = Form.useForm<VerificationForm>()
  return (
    <Modal
      title="执行提供方验证"
      open={open}
      confirmLoading={submitting}
      okText="执行验证"
      cancelText="取消"
      onCancel={onClose}
      onOk={() =>
        void form.validateFields().then((values) =>
          onSubmit({
            pactId: values.pact_id,
            providerVersion: values.provider_version,
            targetBaseUrl: values.target_base_url,
          }),
        )
      }
      afterClose={() => form.resetFields()}
    >
      <Form form={form} layout="vertical">
        <Form.Item name="pact_id" label="Pact 契约" rules={[{ required: true }]}>
          <Select
            options={pacts.map((item) => ({
              value: item.id,
              label: `${item.consumer_name} ${item.consumer_version} → ${item.provider_name}`,
            }))}
          />
        </Form.Item>
        <Form.Item name="provider_version" label="提供方版本" rules={[{ required: true }]}>
          <Input placeholder="2.4.0" />
        </Form.Item>
        <Form.Item
          name="target_base_url"
          label="Provider Origin"
          rules={[
            { required: true },
            { pattern: /^https?:\/\/[^\s]+$/, message: '请输入 HTTP/HTTPS 地址' },
          ]}
          extra="只允许无凭据、Query 和 Path 的 HTTP/HTTPS Origin；网络访问受项目策略约束。"
        >
          <Input placeholder="http://orders-api:8080" />
        </Form.Item>
      </Form>
    </Modal>
  )
}

export function CompatibilityStatus({ status }: { status: 'passed' | 'failed' | 'pending' }) {
  if (status === 'passed')
    return (
      <Tag icon={<CheckCircleOutlined />} color="success">
        通过
      </Tag>
    )
  if (status === 'failed')
    return (
      <Tag icon={<CloseCircleOutlined />} color="error">
        失败
      </Tag>
    )
  return <Tag color="warning">待验证</Tag>
}

export function DecisionTag({ decision }: { decision: DeploymentCheck['decision'] }) {
  const labels = { safe: '可安全发布', unsafe: '不可安全发布', unknown: '证据不足' }
  const colors = { safe: 'success', unsafe: 'error', unknown: 'warning' }
  return <Tag color={colors[decision]}>{labels[decision]}</Tag>
}

function providerServices(services: ServiceCatalogEntry[], pacts: PactContract[]) {
  const providerIds = new Set(pacts.map((item) => item.provider_service_id))
  return services.filter((item) => providerIds.has(item.id))
}

function pageItems<T>(page?: { items: T[] }): T[] {
  return page?.items ?? []
}

function evidenceCount(evidence: Record<string, unknown>, key: string): number {
  const value = evidence[key]
  return Array.isArray(value) ? value.length : 0
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat('zh-CN', {
    dateStyle: 'short',
    timeStyle: 'short',
  }).format(new Date(value))
}
