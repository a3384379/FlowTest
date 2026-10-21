import CatalogPagination from '../components/CatalogPagination'
import QueryFailureNotice from '../components/QueryFailureNotice'
import { useQuery } from '@tanstack/react-query'
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
  Space,
  Statistic,
  Table,
  Tabs,
  Tag,
  Typography,
  Upload,
} from 'antd'
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import ContractAutomationPanel from '../features/contracts/ContractAutomationPanel'
import { contractCoverage } from '../features/contracts/contract-coverage'
import ContractReferencePicker from '../features/contracts/ContractReferencePicker'
import ContractEvidenceViewer, {
  type ContractEvidenceSelection,
} from '../features/contracts/ContractEvidenceDrawer'
import ContractServiceContextNotice from '../features/services/ContractServiceContextNotice'
import { contractServiceLocation } from '../features/services/contract-service-location'
import { useContractServiceContext } from '../features/services/use-contract-service-context'

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
import { getContractService } from '../features/contracts/contract-hub-service'
import { useContractHub } from '../features/contracts/use-contract-hub'
import { useProjectContext } from '../features/projects/use-project-context'
import { apiErrorMessage, apiErrorTraceId } from '../lib/api'

type ServiceForm = { service_key: string; display_name: string; description: string }
type PactForm = { consumer_version: string; consumer: string; provider: string }
type OpenapiForm = { provider_service_id: string; provider_version: string }
type VerificationForm = {
  pact_id: string
  provider_version: string
  target_base_url: string
}

export default function ContractHubPage() {
  const { projectId } = useProjectContext()
  return <ContractHubWorkspace key={projectId ?? 'none'} />
}

function ContractHubWorkspace() {
  const [searchParams, setSearchParams] = useSearchParams()
  const activeTab = searchParams.get('tab') === 'automation' ? 'automation' : 'hub'
  const { projectId } = useProjectContext()
  const providerId = contractServiceLocation(searchParams).id
  function setProviderId(id: string) {
    const next = new URLSearchParams(searchParams)
    next.set('contractServiceId', id)
    next.delete('focus')
    setSearchParams(next)
  }
  const state = useContractHub(providerId)
  const serviceContext = useContractServiceContext(
    projectId,
    Boolean(state.flags.data?.contract_hub),
  )
  const services = pageItems(state.services.data)
  const pacts = pageItems(state.pacts.data)
  const openapiRuns = pageItems(state.openapiRuns.data)
  const checks = pageItems(state.checks.data)
  const [serviceDialog, setServiceDialog] = useState(false)
  const [pactDialog, setPactDialog] = useState<'upload' | 'broker' | null>(null)
  const [openapiDialog, setOpenapiDialog] = useState(false)
  const [verificationDialog, setVerificationDialog] = useState(false)
  const [evidence, setEvidence] = useState<ContractEvidenceSelection | null>(null)

  return (
    <>
      <Tabs
        activeKey={activeTab}
        onChange={(key) => {
          const next = new URLSearchParams(searchParams)
          if (key === 'automation') next.set('tab', key)
          else next.delete('tab')
          setSearchParams(next)
        }}
        items={[
          { key: 'hub', label: '契约中心' },
          { key: 'automation', label: '契约自动化' },
        ]}
      />
      {activeTab === 'automation' ? (
        <ContractAutomationPanel />
      ) : (
        <>
          <ContractHubHeader
            readOnly={!state.canEdit}
            brokerAvailable={Boolean(state.summary.data?.broker_available)}
            hasPacts={Boolean(catalogTotal(state.pacts))}
            onService={() => setServiceDialog(true)}
            onOpenapi={() => setOpenapiDialog(true)}
            onPact={() => setPactDialog('upload')}
            onBroker={() => setPactDialog('broker')}
            onVerify={() => setVerificationDialog(true)}
          />
          <ContractHubStatus state={state} />
          <ContractServiceContextNotice
            projectId={projectId}
            context={serviceContext}
            description="兼容矩阵按该服务作为提供方读取；项目契约目录仍显示全部项目资产。"
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
            readOnly={!state.canEdit || !serviceContext.ready}
            projectId={projectId}
            providerId={providerId}
            matrix={serviceContext.ready ? state.matrix.data : undefined}
            checks={checks}
            loading={state.matrix.isLoading}
            checking={state.checking}
            onProviderChange={setProviderId}
            onRunCheck={state.runCheck}
            onEvidence={setEvidence}
          />
          <div className="contract-hub-grid">
            <ServiceGraphPanel graph={state.graph.data} loading={state.graph.isLoading} />
            <FailedEvidencePanel
              checks={checks}
              available={state.checks.isSuccess}
              onEvidence={setEvidence}
            />
          </div>
          <div className="catalog-controls">
            <CatalogPagination query={state.services} label="服务目录" />
            <CatalogPagination query={state.pacts} label="Pact 契约" />
            <CatalogPagination query={state.openapiRuns} label="OpenAPI 契约" />
            <CatalogPagination query={state.checks} label="兼容判断" />
          </div>
          <UnifiedContractsPanel
            projectId={projectId}
            services={services}
            pacts={pacts}
            openapiRuns={openapiRuns}
            openapiTotal={catalogTotal(state.openapiRuns)}
            pactTotal={catalogTotal(state.pacts)}
            onEvidence={setEvidence}
            loading={state.pacts.isLoading || state.openapiRuns.isLoading}
          />
          <ServiceDialog
            readOnly={!state.canEdit}
            open={serviceDialog}
            submitting={state.creatingService}
            onClose={() => setServiceDialog(false)}
            onSubmit={async (input) => {
              if (await state.createService(input)) setServiceDialog(false)
            }}
          />
          <PactDialog
            readOnly={!state.canEdit}
            key={pactDialog ?? 'closed'}
            mode={pactDialog}
            submitting={state.importing}
            onClose={() => setPactDialog(null)}
            onSubmit={async (input) => {
              if (await state.importPact(input)) setPactDialog(null)
            }}
          />
          <OpenapiDialog
            readOnly={!state.canEdit}
            open={openapiDialog}
            projectId={projectId}
            submitting={state.importing}
            onClose={() => setOpenapiDialog(false)}
            onSubmit={async (input) => {
              if (await state.importOpenapi(input)) setOpenapiDialog(false)
            }}
          />
          <VerificationDialog
            readOnly={!state.canEdit}
            open={verificationDialog}
            projectId={projectId}
            submitting={state.verifying}
            onClose={() => setVerificationDialog(false)}
            onSubmit={async (input) => {
              if (await state.verifyProvider(input)) setVerificationDialog(false)
            }}
          />
          <ContractEvidenceViewer
            projectId={projectId}
            selection={evidence}
            onClose={() => setEvidence(null)}
          />
        </>
      )}
    </>
  )
}

function ContractHubStatus({ state }: { state: ReturnType<typeof useContractHub> }) {
  const queries = [
    state.flags,
    state.permissions,
    state.services,
    state.pacts,
    state.openapiRuns,
    state.summary,
    state.graph,
    state.matrix,
    state.checks,
  ]
  const failed = queries.filter((query) => query.isError)
  if (failed.length) {
    return (
      <Alert
        showIcon
        type="error"
        className="page-alert"
        title={apiErrorMessage(failed[0].error)}
        description={apiErrorTraceId(failed[0].error)}
        action={
          <Button
            aria-label="重试"
            onClick={() => void Promise.all(failed.map((query) => query.refetch()))}
          >
            重试
          </Button>
        }
      />
    )
  }
  if (state.flags.data?.contract_hub === false) {
    return <Alert showIcon type="info" className="page-alert" title="契约中心尚未启用" />
  }
  return null
}

function ContractHubHeader({
  readOnly,
  brokerAvailable,
  hasPacts,
  onService,
  onOpenapi,
  onPact,
  onBroker,
  onVerify,
}: {
  readOnly: boolean
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
        <Button
          aria-label="登记服务"
          icon={<PlusOutlined />}
          disabled={readOnly}
          onClick={onService}
        >
          登记服务
        </Button>
        <Button icon={<UploadOutlined />} disabled={readOnly} onClick={onOpenapi}>
          导入 OpenAPI
        </Button>
        <Button icon={<UploadOutlined />} disabled={readOnly} onClick={onPact}>
          导入 Pact
        </Button>
        {brokerAvailable ? (
          <Button icon={<CloudDownloadOutlined />} disabled={readOnly} onClick={onBroker}>
            从 Broker 导入
          </Button>
        ) : null}
        <Button
          type="primary"
          icon={<SafetyCertificateOutlined />}
          disabled={readOnly || !hasPacts}
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
    [
      'OpenAPI 契约',
      summary?.openapi_contract_count ?? '未提供',
      <FileProtectOutlined />,
      undefined,
    ],
    ['Pact 契约', summary?.pact_contract_count ?? '未提供', <ApartmentOutlined />, undefined],
    ['待验证', summary?.pending_verification_count ?? '未提供', undefined, '#d97706'],
    ['破坏性变更', summary?.breaking_change_count ?? '未提供', undefined, '#dc2626'],
  ] as const
  return (
    <Row gutter={16} className="performance-overview">
      {items.map(([title, value, prefix, color]) => (
        <Col xs={12} lg={6} key={title}>
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
  readOnly = false,
  projectId,
  providerId,
  matrix,
  checks,
  loading,
  checking,
  onProviderChange,
  onRunCheck,
  onEvidence,
}: {
  readOnly?: boolean
  projectId: string | null
  providerId: string | null
  matrix?: CompatibilityMatrix
  checks: DeploymentCheck[]
  loading: boolean
  checking: boolean
  onProviderChange: (value: string) => void
  onRunCheck: (input: { providerServiceId: string; providerVersion: string }) => Promise<boolean>
  onEvidence: (selection: ContractEvidenceSelection) => void
}) {
  const [providerVersion, setProviderVersion] = useState('')
  const [providerReady, setProviderReady] = useState(false)
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
      render: (_: unknown, row: CompatibilityMatrix['rows'][number]) => {
        const cell = row.cells.find((item) => item.provider_version === version)
        const target = compatibilityEvidence(row.pact_contract_version_id, cell?.verification_id)
        return (
          <Button
            type="text"
            aria-label={`查看${row.consumer_name} ${row.consumer_version}与${version}的兼容证据`}
            onClick={() => onEvidence(target)}
          >
            <CompatibilityStatus status={cell?.status ?? 'pending'} />
          </Button>
        )
      },
    })),
  ]
  return (
    <Card
      className="performance-card contract-compatibility"
      title="部署兼容矩阵"
      loading={loading}
      extra={
        <ContractReferencePicker
          projectId={projectId}
          kind="service"
          label="提供方服务"
          allowClear={false}
          value={providerId ?? undefined}
          onChange={(id) => {
            if (id) onProviderChange(id)
          }}
          onReadyChange={setProviderReady}
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
        <Empty description={matrixEmptyDescription(providerId, matrix)} />
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
          disabled={deploymentCheckDisabled(readOnly, providerId, providerVersion, providerReady)}
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
        {selectedCheck ? (
          <Button type="text" onClick={() => onEvidence({ kind: 'check', id: selectedCheck.id })}>
            <DecisionTag decision={selectedCheck.decision} />
          </Button>
        ) : null}
      </Space>
    </Card>
  )
}

function deploymentCheckDisabled(
  readOnly: boolean,
  providerId: string | null,
  version: string,
  providerReady: boolean,
): boolean {
  return readOnly || !providerReady || !providerId || !version.trim()
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

export function FailedEvidencePanel({
  checks,
  onEvidence,
  available = true,
}: {
  checks: DeploymentCheck[]
  onEvidence?: (selection: ContractEvidenceSelection) => void
  available?: boolean
}) {
  return (
    <Card title="发布判断证据" className="performance-card">
      {checks.length ? (
        <Space orientation="vertical" className="full-width">
          {checks.map((item) => (
            <Alert
              key={item.id}
              type={checkAlertType(item.decision)}
              showIcon
              title={`Provider ${item.provider_version} ${decisionText(item.decision)}`}
              description={`${blockerSummary(item.evidence)} · ${formatDate(item.created_at)}`}
              action={
                <Button
                  disabled={!onEvidence}
                  onClick={() => onEvidence?.({ kind: 'check', id: item.id })}
                >
                  查看逐项证据
                </Button>
              }
            />
          ))}
        </Space>
      ) : (
        <Empty description={available ? '暂无不可安全发布的判断' : '发布判断证据未提供'} />
      )}
    </Card>
  )
}

export function UnifiedContractsPanel({
  projectId,
  services,
  pacts,
  openapiRuns,
  loading,
  openapiTotal,
  pactTotal,
  onEvidence,
}: {
  projectId?: string | null
  services: ServiceCatalogEntry[]
  pacts: PactContract[]
  openapiRuns: ContractRun[]
  loading: boolean
  openapiTotal?: number | null
  pactTotal?: number | null
  onEvidence?: (selection: ContractEvidenceSelection) => void
}) {
  return (
    <Card title="统一契约资产" loading={loading} className="performance-card">
      <Tabs
        items={[
          {
            key: 'openapi',
            label: `OpenAPI（${catalogCountLabel(openapiTotal, openapiRuns.length)}）`,
            children: (
              <Table
                rowKey="id"
                size="small"
                pagination={false}
                scroll={{ x: 920 }}
                dataSource={openapiRuns}
                columns={[
                  { title: '文档', dataIndex: 'source_name' },
                  {
                    title: '提供方版本',
                    render: (_: unknown, item: ContractRun) => (
                      <ContractRunProvider
                        projectId={projectId}
                        run={item}
                        initialService={services.find(
                          (service) => service.id === item.provider_service_id,
                        )}
                      />
                    ),
                  },
                  {
                    title: '破坏性变更',
                    render: (_: unknown, item: ContractRun) => <BreakingChangeTag run={item} />,
                  },
                  {
                    title: 'Schema 覆盖率',
                    render: (_: unknown, item: ContractRun) =>
                      contractCoverage(
                        item.coverage.schema_coverage_percent,
                        item.coverage.schema_fields_total,
                        item.status === 'completed',
                      ).label,
                  },
                  {
                    title: '导入时间',
                    render: (_: unknown, item: ContractRun) => formatDate(item.created_at),
                  },
                  {
                    title: '证据',
                    render: (_: unknown, item: ContractRun) => (
                      <Button
                        disabled={!onEvidence}
                        onClick={() => onEvidence?.({ kind: 'run', id: item.id })}
                      >
                        查看固定分析
                      </Button>
                    ),
                  },
                ]}
              />
            ),
          },
          {
            key: 'pact',
            label: `Pact（${catalogCountLabel(pactTotal, pacts.length)}）`,
            children: (
              <Table
                rowKey="id"
                size="small"
                pagination={false}
                scroll={{ x: 920 }}
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
                  {
                    title: '证据',
                    render: (_: unknown, item: PactContract) => (
                      <Button
                        disabled={!onEvidence}
                        onClick={() => onEvidence?.({ kind: 'pact', id: item.id })}
                      >
                        查看固定契约
                      </Button>
                    ),
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

function ContractRunProvider({
  projectId,
  run,
  initialService,
}: {
  projectId?: string | null
  run: ContractRun
  initialService?: ServiceCatalogEntry
}) {
  if (!run.provider_service_id) return <>未绑定</>
  if (!projectId)
    return (
      <>
        {initialService?.display_name ?? run.provider_service_id} · {run.provider_version}
      </>
    )
  return (
    <ResolvedProvider
      projectId={projectId}
      id={run.provider_service_id}
      version={run.provider_version}
      initialService={initialService}
    />
  )
}

function ResolvedProvider({
  projectId,
  id,
  version,
  initialService,
}: {
  projectId: string
  id: string
  version: string | null
  initialService?: ServiceCatalogEntry
}) {
  const query = useQuery({
    queryKey: ['contract-service', projectId, id],
    queryFn: () => getContractService(projectId, id),
    initialData: initialService,
  })
  return (
    <Space orientation="vertical" size={0}>
      <Typography.Text>
        {query.data?.display_name ?? `服务ID：${id}`} · {version}
      </Typography.Text>
      <QueryFailureNotice queries={[query]} />
    </Space>
  )
}

function ServiceDialog({
  readOnly,
  open,
  submitting,
  onClose,
  onSubmit,
}: {
  readOnly: boolean
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
      okButtonProps={{ disabled: readOnly }}
      okText="登记"
      cancelText="取消"
      onCancel={submitting ? undefined : onClose}
      cancelButtonProps={{ disabled: submitting }}
      closable={!submitting}
      onOk={() => form.submit()}
      afterClose={() => form.resetFields()}
    >
      <Form form={form} layout="vertical" disabled={readOnly || submitting} onFinish={onSubmit}>
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
  readOnly,
  mode,
  submitting,
  onClose,
  onSubmit,
}: {
  readOnly: boolean
  mode: 'upload' | 'broker' | null
  submitting: boolean
  onClose: () => void
  onSubmit: (input: PactImportInput) => Promise<void>
}) {
  const [form] = Form.useForm<PactForm>()
  const [file, setFile] = useState<File | null>(null)
  const submit = async (values: PactForm) => {
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
      okButtonProps={{ disabled: readOnly || (mode === 'upload' && !file) }}
      onCancel={submitting ? undefined : onClose}
      cancelButtonProps={{ disabled: submitting }}
      closable={!submitting}
      onOk={() => form.submit()}
      afterClose={() => {
        form.resetFields()
        setFile(null)
      }}
    >
      <Form form={form} layout="vertical" disabled={readOnly || submitting} onFinish={submit}>
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
              fileList={file ? [{ uid: file.name, name: file.name, status: 'done' }] : []}
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
  readOnly,
  open,
  projectId,
  submitting,
  onClose,
  onSubmit,
}: {
  readOnly: boolean
  open: boolean
  projectId: string | null
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
  const [providerReady, setProviderReady] = useState(false)
  return (
    <Modal
      title="导入并绑定 OpenAPI"
      open={open}
      confirmLoading={submitting}
      okText="导入"
      cancelText="取消"
      okButtonProps={{ disabled: readOnly || !file || !providerReady }}
      onCancel={submitting ? undefined : onClose}
      cancelButtonProps={{ disabled: submitting }}
      closable={!submitting}
      onOk={() => form.submit()}
      afterClose={() => {
        form.resetFields()
        setFile(null)
      }}
    >
      <Form
        form={form}
        layout="vertical"
        disabled={readOnly || submitting}
        onFinish={(values) =>
          file
            ? onSubmit({
                file,
                providerServiceId: values.provider_service_id,
                providerVersion: values.provider_version,
              })
            : undefined
        }
      >
        <Form.Item label="OpenAPI 文档" required>
          <Upload
            maxCount={1}
            fileList={file ? [{ uid: file.name, name: file.name, status: 'done' }] : []}
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
          <ContractReferencePicker
            projectId={projectId}
            kind="service"
            label="提供方服务"
            disabled={readOnly || submitting}
            onReadyChange={setProviderReady}
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
  readOnly,
  open,
  projectId,
  submitting,
  onClose,
  onSubmit,
}: {
  readOnly: boolean
  open: boolean
  projectId: string | null
  submitting: boolean
  onClose: () => void
  onSubmit: (input: {
    pactId: string
    providerVersion: string
    targetBaseUrl: string
  }) => Promise<void>
}) {
  const [form] = Form.useForm<VerificationForm>()
  const [pactReady, setPactReady] = useState(false)
  return (
    <Modal
      title="执行提供方验证"
      open={open}
      confirmLoading={submitting}
      okButtonProps={{ disabled: readOnly || !pactReady }}
      okText="执行验证"
      cancelText="取消"
      onCancel={submitting ? undefined : onClose}
      cancelButtonProps={{ disabled: submitting }}
      closable={!submitting}
      onOk={() => form.submit()}
      afterClose={() => form.resetFields()}
    >
      <Form
        form={form}
        layout="vertical"
        disabled={readOnly || submitting}
        onFinish={(values) =>
          onSubmit({
            pactId: values.pact_id,
            providerVersion: values.provider_version,
            targetBaseUrl: values.target_base_url,
          })
        }
      >
        <Form.Item name="pact_id" label="Pact 契约" rules={[{ required: true }]}>
          <ContractReferencePicker
            projectId={projectId}
            kind="pact"
            label="Pact 契约"
            disabled={readOnly || submitting}
            onReadyChange={setPactReady}
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

function pageItems<T>(page?: { items: T[] }): T[] {
  return page?.items ?? []
}

function catalogTotal(query: { data?: { total: number } }): number | null {
  return query.data?.total ?? null
}

function catalogCountLabel(total: number | null | undefined, current: number): string {
  return total === null ? '总数未提供' : `共${total ?? current}项，本页${current}项`
}

function matrixEmptyDescription(providerId: string | null, matrix?: CompatibilityMatrix): string {
  if (!providerId) return '请先选择提供方'
  return matrix ? '该提供方暂无 Pact 契约' : '兼容矩阵尚未提供'
}

function blockerSummary(evidence: Record<string, unknown>): string {
  const value = evidence.blockers
  return Array.isArray(value) ? `${value.length} 项阻断证据` : '阻断证据未提供'
}

function BreakingChangeTag({ run }: { run: ContractRun }) {
  if (run.status !== 'completed') return <Tag color="warning">分析未成功</Tag>
  return (
    <Tag color={run.breaking_changes.length ? 'red' : 'green'}>
      {run.breaking_changes.length ? `${run.breaking_changes.length} 项` : '无'}
    </Tag>
  )
}

function compatibilityEvidence(
  pactId: string,
  verificationId?: string | null,
): ContractEvidenceSelection {
  return verificationId
    ? { kind: 'verification', id: verificationId }
    : { kind: 'pact', id: pactId }
}

function checkAlertType(decision: DeploymentCheck['decision']) {
  return { safe: 'success', unsafe: 'error', unknown: 'warning' }[decision] as
    'success' | 'error' | 'warning'
}

function decisionText(decision: DeploymentCheck['decision']): string {
  return { safe: '可安全发布', unsafe: '不可安全发布', unknown: '证据不足' }[decision]
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat('zh-CN', {
    dateStyle: 'short',
    timeStyle: 'short',
  }).format(new Date(value))
}
