import { confidenceLabel } from '../features/test-engineering/design-confidence'
import { materializationBlocker } from '../features/test-engineering/design-review-rules'
import DesignCoverageSummary from '../features/test-engineering/DesignCoverageSummary'
import DesignEvidenceWorkspace from '../features/test-engineering/DesignEvidenceWorkspace'
import MaterializedDesignAssets from '../features/test-engineering/MaterializedDesignAssets'
import '../features/test-engineering/test-engineering.css'
import { apiErrorMessage, apiErrorTraceId } from '../lib/api'
import { ScenarioTable, CoverageTable } from '../features/test-engineering/DesignReviewTables'
import ApiResourceSelect from '../features/api-console/ApiResourceSelect'
import QueryFailureNotice from '../components/QueryFailureNotice'
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  Descriptions,
  Collapse,
  Form,
  Input,
  Layout,
  Row,
  Select,
  Space,
  Tag,
  Typography,
} from 'antd'
import type { FormInstance } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

import { listServiceEndpoints } from '../features/service-targets/service-target-service'
import type {
  OperationContract,
  EvidenceDetail,
  TestDesignDocument,
} from '../features/test-engineering/test-engineering-service'
import { useTestEngineering } from '../features/test-engineering/use-test-engineering'
import { useProjectContext } from '../features/projects/use-project-context'

type GenerationForm = {
  title: string
  api_definition_id: string
  environment_id: string
  endpoint_variant?: string
}

export default function TestEngineeringPage() {
  const { projectId } = useProjectContext()
  return <TestEngineeringWorkspace key={projectId ?? 'none'} />
}

function TestEngineeringWorkspace() {
  const [searchParams, setSearchParams] = useSearchParams()
  const navigate = useNavigate()
  const { modal } = App.useApp()
  const [dirty, setDirty] = useState(false)
  const state = useTestEngineering(searchParams.get('proposal'))
  const [form] = Form.useForm<GenerationForm>()
  const [scenarioIds, setScenarioIds] = useState<string[]>([])
  const design = state.proposal?.design ?? state.generation?.design ?? null
  const proposalId = state.proposal?.change_set_id
  useEffect(() => {
    const next = new URLSearchParams(searchParams)
    if (proposalId && searchParams.get('proposal') !== proposalId) next.set('proposal', proposalId)
    else if (!proposalId && state.generation && searchParams.has('proposal'))
      next.delete('proposal')
    else return
    setSearchParams(next, { replace: true })
  }, [proposalId, state.generation, searchParams, setSearchParams])
  function openAsset(path: string) {
    if (!dirty) {
      navigate(path)
      return
    }
    modal.confirm({
      title: '还有未保存的设计目标',
      content: '放弃这些输入并打开资产？',
      okText: '放弃并打开',
      cancelText: '留在当前页面',
      onOk: () => navigate(path),
    })
  }

  return (
    <Layout className="page-layout test-design-review">
      <Space orientation="vertical" size={20} style={{ width: '100%' }}>
        <div className="page-heading">
          <div>
            <Typography.Title level={2}>测试工程</Typography.Title>
            <Typography.Paragraph type="secondary">
              从接口契约生成测试场景、判断预期和覆盖缺口；人工审核通过后，才能生成工作流与测试用例草稿。
            </Typography.Paragraph>
          </div>
        </div>
        <Alert
          showIcon
          type="info"
          title="预览只读且不保存；创建设计草稿后，须人工审核通过再生成资产。"
        />
        <GenerationTargetCard
          state={state}
          form={form}
          scenarioIds={scenarioIds}
          onDirty={() => setDirty(true)}
          onSaved={() => setDirty(false)}
          onGenerated={() => setScenarioIds([])}
        />
        {state.error && (
          <Alert
            showIcon
            type="error"
            title={apiErrorMessage(state.error)}
            description={apiErrorTraceId(state.error)}
          />
        )}
        <GeneratedDesign
          design={design}
          state={state}
          scenarioIds={scenarioIds}
          onScenarioIdsChange={setScenarioIds}
          onOpen={openAsset}
        />
      </Space>
    </Layout>
  )
}

function GeneratedDesign({
  design,
  state,
  scenarioIds,
  onScenarioIdsChange,
  onOpen,
}: {
  design: TestDesignDocument | null
  state: ReturnType<typeof useTestEngineering>
  scenarioIds: string[]
  onScenarioIdsChange: (ids: string[]) => void
  onOpen: (path: string) => void
}) {
  if (!design) {
    return (
      <Card>
        <Typography.Text type="secondary">请选择 API 契约并生成预览。</Typography.Text>
      </Card>
    )
  }
  const { contractCompleteness, contractFingerprint, contract } = generationContext(state)
  return (
    <DesignReview
      key={state.proposal?.change_set_id ?? state.generation?.fingerprint ?? 'preview'}
      design={design}
      projectId={state.projectId!}
      onOpen={onOpen}
      evidenceDetails={state.proposal?.evidence_details ?? state.generation?.evidence_details}
      contract={contract}
      contractCompleteness={contractCompleteness}
      contractFingerprint={contractFingerprint}
      scenarioIds={scenarioIds}
      onScenarioIdsChange={onScenarioIdsChange}
      proposal={state.proposal}
      readOnly={!state.canEdit}
      acting={state.acting}
      onReview={state.reviewProposal}
      onApply={state.applyProposal}
    />
  )
}

function generationContext(state: ReturnType<typeof useTestEngineering>) {
  if (state.proposal) {
    return {
      contractCompleteness: state.proposal.contract_completeness,
      contractFingerprint: state.proposal.contract_fingerprint,
      contract: state.proposal.contract,
    }
  }
  return {
    contractCompleteness: state.generation?.contract_completeness,
    contractFingerprint: state.generation?.contract_fingerprint,
    contract: state.generation?.contract,
  }
}

function GenerationTargetCard({
  state,
  form,
  scenarioIds,
  onGenerated,
  onDirty,
  onSaved,
}: {
  state: ReturnType<typeof useTestEngineering>
  form: FormInstance<GenerationForm>
  scenarioIds: string[]
  onGenerated: () => void
  onDirty: () => void
  onSaved: () => void
}) {
  const endpointVariants = useEndpointVariants(state, form)
  async function generate(): Promise<void> {
    const apiDefinitionId = form.getFieldValue('api_definition_id')
    if (!apiDefinitionId) return
    if (await state.generateDesign(apiDefinitionId)) onGenerated()
  }
  async function createProposal(values: GenerationForm): Promise<void> {
    if (await state.createProposal({ ...values, scenario_ids: scenarioIds })) onSaved()
  }
  return (
    <Card title="生成来源与目标">
      <QueryFailureNotice
        queries={[
          state.apis,
          state.environments,
          state.linkedProposal,
          endpointVariants.query,
          state.permissions,
        ]}
      />
      <Form<GenerationForm>
        form={form}
        layout="vertical"
        onFinish={createProposal}
        disabled={state.acting || state.generating}
        onValuesChange={onDirty}
      >
        <Row gutter={16}>
          <Col xs={24} md={6}>
            <Form.Item name="api_definition_id" label="API 契约" rules={[{ required: true }]}>
              <ApiResourceSelect
                projectId={state.projectId}
                known={state.apis.data?.items ?? []}
                label="API 契约"
                onSelection={state.setSelectedApi}
                onChange={() => form.setFieldValue('endpoint_variant', undefined)}
              />
            </Form.Item>
          </Col>
          <Col xs={24} md={6}>
            <Form.Item name="environment_id" label="目标环境" rules={[{ required: true }]}>
              <Select
                aria-label="目标环境"
                loading={state.environments.isLoading}
                onChange={() => form.setFieldValue('endpoint_variant', undefined)}
                options={(state.environments.data ?? []).map((environment) => ({
                  value: environment.id,
                  label: environment.name,
                }))}
              />
            </Form.Item>
          </Col>
          <EndpointVariantField endpointVariants={endpointVariants} />
          <Col xs={24} md={endpointVariants.required ? 6 : 12}>
            <Form.Item name="title" label="测试设计名称" rules={[{ required: true }]}>
              <Input placeholder="订单创建契约测试" />
            </Form.Item>
          </Col>
        </Row>
        <Space wrap>
          <Button
            disabled={state.acting}
            loading={state.generating}
            onClick={() => void generate()}
          >
            只读生成预览
          </Button>
          <Button
            type="primary"
            htmlType="submit"
            loading={state.acting}
            disabled={!state.canEdit || !state.generation || Boolean(state.proposal)}
          >
            创建待审核草稿
          </Button>
        </Space>
      </Form>
    </Card>
  )
}

function EndpointVariantField({
  endpointVariants,
}: {
  endpointVariants: ReturnType<typeof useEndpointVariants>
}) {
  if (!endpointVariants.required) return null
  const placeholder = endpointVariants.options.length ? '选择运行变体' : '当前环境无可用变体'
  return (
    <Col xs={24} md={6}>
      <Form.Item name="endpoint_variant" label="服务端点" rules={[{ required: true }]}>
        <Select
          aria-label="服务端点"
          loading={endpointVariants.loading}
          options={endpointVariants.options}
          placeholder={placeholder}
        />
      </Form.Item>
    </Col>
  )
}

function useEndpointVariants(
  state: ReturnType<typeof useTestEngineering>,
  form: FormInstance<GenerationForm>,
) {
  const apiDefinitionId = Form.useWatch('api_definition_id', form)
  const environmentId = Form.useWatch('environment_id', form)
  const selectedApi = engineeringApi(state, apiDefinitionId)
  const serviceId = selectedApi?.service_id
  const query = useQuery({
    queryKey: ['test-engineering-endpoints', state.projectId, environmentId],
    queryFn: () => listServiceEndpoints(required(state.projectId), required(environmentId)),
    enabled: Boolean(state.projectId && environmentId && serviceId),
  })
  return {
    query,
    required: Boolean(serviceId),
    loading: query.isLoading,
    options: (query.data ?? [])
      .filter((endpoint) => endpoint.enabled && endpoint.service_id === serviceId)
      .map((endpoint) => ({ value: endpoint.variant, label: endpoint.variant })),
  }
}

function required(value: string | null | undefined): string {
  if (!value) throw new Error('project/environment id is required')
  return value
}

function DesignReview({
  readOnly,
  projectId,
  onOpen,
  evidenceDetails,
  design,
  contract,
  contractCompleteness,
  contractFingerprint,
  scenarioIds,
  onScenarioIdsChange,
  proposal,
  acting,
  onReview,
  onApply,
}: {
  readOnly: boolean
  projectId: string
  onOpen: (path: string) => void
  evidenceDetails?: EvidenceDetail[]
  design: TestDesignDocument
  contract?: OperationContract
  contractCompleteness?: string
  contractFingerprint?: string
  scenarioIds: string[]
  onScenarioIdsChange: (ids: string[]) => void
  proposal: ReturnType<typeof useTestEngineering>['proposal']
  acting: boolean
  onReview: (accept: boolean) => Promise<boolean>
  onApply: () => Promise<boolean>
}) {
  const coverage = design.coverage?.entries
  const [inspectedId, setInspectedId] = useState(design.scenarios[0]?.id)
  const scenario = design.scenarios.find((item) => item.id === inspectedId)
  return (
    <Space orientation="vertical" size={16} style={{ width: '100%' }}>
      <IntentReviewCard
        readOnly={readOnly}
        design={design}
        contract={contract}
        contractCompleteness={contractCompleteness}
        contractFingerprint={contractFingerprint}
        proposal={proposal}
        acting={acting}
        onReview={onReview}
        onApply={onApply}
      />
      {proposal?.applied && (
        <MaterializedDesignAssets projectId={projectId} proposal={proposal} onOpen={onOpen} />
      )}
      <Card title={`场景审核（${design.scenarios.length}项）`}>
        <ScenarioTable
          items={design.scenarios}
          selected={proposal?.scenario_ids ?? scenarioIds}
          disabled={readOnly || acting || Boolean(proposal)}
          onChange={onScenarioIdsChange}
          oracles={design.oracles}
          inspectedId={inspectedId}
          onInspect={setInspectedId}
        />
      </Card>
      <DesignEvidenceWorkspace
        design={design}
        scenario={scenario}
        evidenceDetails={evidenceDetails}
        projectId={projectId}
        onOpen={onOpen}
      />
      <Card title="完整设计覆盖与缺口" extra={<DesignCoverageSummary entries={coverage} />}>
        <CoverageTable items={coverage ?? []} />
      </Card>
    </Space>
  )
}

function IntentReviewCard({
  readOnly,
  design,
  contract,
  contractCompleteness,
  contractFingerprint,
  proposal,
  acting,
  onReview,
  onApply,
}: {
  readOnly: boolean
  design: TestDesignDocument
  contract?: OperationContract
  contractCompleteness?: string
  contractFingerprint?: string
  proposal: ReturnType<typeof useTestEngineering>['proposal']
  acting: boolean
  onReview: (accept: boolean) => Promise<boolean>
  onApply: () => Promise<boolean>
}) {
  return (
    <Card title="测试目标与审核状态">
      <Descriptions bordered size="small" column={{ xs: 1, sm: 2 }}>
        <Descriptions.Item label="测试目标">{design.intent.objective}</Descriptions.Item>
        <Descriptions.Item label="置信度">{confidenceLabel(design.confidence)}</Descriptions.Item>
        <Descriptions.Item label="来源证据">
          {design.evidence_refs.length} 条结构化引用
        </Descriptions.Item>
        <Descriptions.Item label="契约完整度">
          <Tag color={contractCompleteness === 'complete' ? 'green' : 'orange'}>
            {completenessLabel(contractCompleteness)}
          </Tag>
        </Descriptions.Item>

        <Descriptions.Item label="状态证据">{stateCapability(design)}</Descriptions.Item>
        <Descriptions.Item label="审核状态">
          <ProposalReviewStatus proposal={proposal} />
        </Descriptions.Item>
      </Descriptions>
      <Collapse
        items={[
          {
            key: 'diagnostics',
            label: '原始技术信息与诊断',
            children: (
              <>
                <Tag>S47</Tag>
                <Typography.Paragraph>
                  来源契约指纹：{contractFingerprint ?? '未提供'}
                </Typography.Paragraph>
                <pre className="test-design-json">
                  {JSON.stringify({ contract, design }, null, 2)}
                </pre>
              </>
            ),
          },
        ]}
      />
      <ContractOverview contract={contract} />
      <ContractAlerts design={design} contractCompleteness={contractCompleteness} />
      {design.warnings.map((warning) => (
        <Alert key={warning} type="warning" showIcon message={warning} />
      ))}
      <ProposalActions
        readOnly={readOnly}
        proposal={proposal}
        acting={acting}
        onReview={onReview}
        onApply={onApply}
      />
    </Card>
  )
}

function ContractOverview({ contract }: { contract?: OperationContract }) {
  if (!contract) {
    return (
      <Descriptions bordered size="small" column={{ xs: 1, sm: 2 }}>
        <Descriptions.Item label="操作标识">历史响应未提供</Descriptions.Item>
        <Descriptions.Item label="认证要求">unknown</Descriptions.Item>
        <Descriptions.Item label="参数位置">unknown</Descriptions.Item>
      </Descriptions>
    )
  }
  const parameterLocations = contract.parameters
    .map((parameter) => `${parameter.location}.${parameter.name}`)
    .join('、')
  const authName = contract.auth.name ? `:${contract.auth.name}` : ''
  return (
    <Descriptions bordered size="small" column={{ xs: 1, sm: 2 }}>
      <Descriptions.Item label="操作标识">
        {`${contract.service ?? 'default'} · ${contract.method} ${contract.path} · ${contract.operation}`}
      </Descriptions.Item>
      <Descriptions.Item label="认证要求">
        {`${contract.auth.required ? 'required' : 'optional'} · ${contract.auth.kind} · ${contract.auth.location ?? 'none'}${authName}`}
      </Descriptions.Item>
      <Descriptions.Item label="参数位置">{parameterLocations || '无显式参数'}</Descriptions.Item>
    </Descriptions>
  )
}

function ContractAlerts({
  design,
  contractCompleteness,
}: {
  design: TestDesignDocument
  contractCompleteness?: string
}) {
  return (
    <>
      {contractCompleteness === 'redacted_partial' ? (
        <Alert
          type="warning"
          showIcon
          title="来源契约已按策略处理"
          description="敏感 Enum 或示例值未进入持久化契约；相关场景仅保留为设计，需人工提供 secret:// 测试数据后才能生成可执行草稿。"
        />
      ) : null}
      {design.review_requirements.includes('evidence_conflict') ? (
        <Alert
          type="warning"
          showIcon
          title="来源证据存在冲突"
          description="确定性规范证据存在双向语义冲突；依赖这些冲突来源的场景需要人工复核。"
        />
      ) : null}
    </>
  )
}

function ProposalReviewStatus({
  proposal,
}: {
  proposal: ReturnType<typeof useTestEngineering>['proposal']
}) {
  if (!proposal) return <>未创建设计草稿</>
  return (
    <Tag color={reviewColor(proposal.review_status)}>
      {{ pending: '待审核', accepted: '已接受', rejected: '已拒绝' }[proposal.review_status]}
    </Tag>
  )
}

function stateCapability(design: TestDesignDocument): string {
  return design.review_requirements.includes('state_evidence_unavailable')
    ? '缺少显式状态证据'
    : '未启用'
}

function ProposalActions({
  readOnly,
  proposal,
  acting,
  onReview,
  onApply,
}: {
  readOnly: boolean
  proposal: ReturnType<typeof useTestEngineering>['proposal']
  acting: boolean
  onReview: (accept: boolean) => Promise<boolean>
  onApply: () => Promise<boolean>
}) {
  if (!proposal) return null
  const blocker = materializationBlocker(proposal)
  return (
    <Space wrap style={{ marginTop: 16 }}>
      {proposal.review_status === 'pending' ? (
        <>
          <Button
            type="primary"
            disabled={readOnly}
            loading={acting}
            onClick={() => void onReview(true)}
          >
            接受设计草稿
          </Button>
          <Button danger disabled={readOnly} loading={acting} onClick={() => void onReview(false)}>
            拒绝设计草稿
          </Button>
        </>
      ) : null}
      {proposal.review_status === 'accepted' && !proposal.applied ? (
        <Space orientation="vertical">
          {blocker && <Alert showIcon type="warning" title={blocker} />}
          <Button
            type="primary"
            disabled={readOnly || Boolean(blocker)}
            loading={acting}
            onClick={() => void onApply()}
          >
            生成工作流与用例草稿
          </Button>
        </Space>
      ) : null}
      {proposal.applied ? <Tag color="green">已生成资产草稿</Tag> : null}
    </Space>
  )
}

function reviewColor(status: 'pending' | 'accepted' | 'rejected'): string {
  if (status === 'accepted') return 'green'
  if (status === 'rejected') return 'default'
  return 'orange'
}

function engineeringApi(state: ReturnType<typeof useTestEngineering>, id: string | undefined) {
  if (state.selectedApi?.id === id) return state.selectedApi
  return state.apis.data?.items.find((api) => api.id === id)
}

function completenessLabel(value?: string): string {
  const labels: Record<string, string> = {
    complete: '完整',
    partial: '部分信息',
    legacy_partial: '历史信息不完整',
    redacted_partial: '按策略处理的部分信息',
  }
  return labels[value ?? ''] ?? '未提供'
}
