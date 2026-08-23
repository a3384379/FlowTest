import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Form,
  Input,
  Layout,
  Progress,
  Row,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd'
import type { FormInstance } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { listServiceEndpoints } from '../features/service-targets/service-target-service'
import type {
  CoverageEntry,
  OracleSpec,
  ScenarioCandidate,
  TestDesignDocument,
} from '../features/test-engineering/test-engineering-service'
import { useTestEngineering } from '../features/test-engineering/use-test-engineering'

type GenerationForm = {
  title: string
  api_definition_id: string
  environment_id: string
  endpoint_variant?: string
}

export default function TestEngineeringPage() {
  const state = useTestEngineering()
  const [form] = Form.useForm<GenerationForm>()
  const [scenarioIds, setScenarioIds] = useState<string[]>([])
  const design = state.proposal?.design ?? state.generation?.design ?? null

  return (
    <Layout className="page-layout">
      <Space orientation="vertical" size={20} style={{ width: '100%' }}>
        <div className="page-heading">
          <div>
            <Typography.Title level={2}>Test Engineering</Typography.Title>
            <Typography.Paragraph type="secondary">
              从契约 Evidence 确定性生成 Scenario、Oracle 与 Coverage；只有经人工审核的 Draft
              才能进入现有 Workflow / TestCase 执行体系。
            </Typography.Paragraph>
          </div>
          <Tag color="blue">S47</Tag>
        </div>
        <Alert
          showIcon
          type="info"
          title="Generate 只读且不持久化；Proposal 为 Draft，必须 Review 后才能 Apply。"
        />
        <GenerationTargetCard
          state={state}
          form={form}
          scenarioIds={scenarioIds}
          onGenerated={() => setScenarioIds([])}
        />
        <GeneratedDesign
          design={design}
          state={state}
          scenarioIds={scenarioIds}
          onScenarioIdsChange={setScenarioIds}
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
}: {
  design: TestDesignDocument | null
  state: ReturnType<typeof useTestEngineering>
  scenarioIds: string[]
  onScenarioIdsChange: (ids: string[]) => void
}) {
  if (!design) {
    return (
      <Card>
        <Typography.Text type="secondary">请选择 API 契约并生成预览。</Typography.Text>
      </Card>
    )
  }
  const contractCompleteness =
    state.proposal?.contract_completeness ?? state.generation?.contract_completeness
  const contractFingerprint =
    state.proposal?.contract_fingerprint ?? state.generation?.contract_fingerprint
  return (
    <DesignReview
      design={design}
      contractCompleteness={contractCompleteness}
      contractFingerprint={contractFingerprint}
      scenarioIds={scenarioIds}
      onScenarioIdsChange={onScenarioIdsChange}
      proposal={state.proposal}
      acting={state.acting}
      onReview={state.reviewProposal}
      onApply={state.applyProposal}
    />
  )
}

function GenerationTargetCard({
  state,
  form,
  scenarioIds,
  onGenerated,
}: {
  state: ReturnType<typeof useTestEngineering>
  form: FormInstance<GenerationForm>
  scenarioIds: string[]
  onGenerated: () => void
}) {
  const endpointVariants = useEndpointVariants(state, form)
  async function generate(): Promise<void> {
    const apiDefinitionId = form.getFieldValue('api_definition_id')
    if (!apiDefinitionId) return
    if (await state.generateDesign(apiDefinitionId)) onGenerated()
  }
  async function createProposal(values: GenerationForm): Promise<void> {
    await state.createProposal({ ...values, scenario_ids: scenarioIds })
  }
  return (
    <Card title="生成来源与物化目标">
      <Form<GenerationForm> form={form} layout="vertical" onFinish={createProposal}>
        <Row gutter={16}>
          <Col xs={24} md={6}>
            <Form.Item name="api_definition_id" label="API 契约" rules={[{ required: true }]}>
              <Select
                aria-label="API 契约"
                loading={state.apis.isLoading}
                onChange={() => form.setFieldValue('endpoint_variant', undefined)}
                options={(state.apis.data?.items ?? []).map((api) => ({
                  value: api.id,
                  label: `${api.name} · v${api.current_version}`,
                  disabled: !api.is_active,
                }))}
              />
            </Form.Item>
          </Col>
          <Col xs={24} md={6}>
            <Form.Item name="environment_id" label="物化环境" rules={[{ required: true }]}>
              <Select
                aria-label="物化环境"
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
            <Form.Item name="title" label="Test Design 名称" rules={[{ required: true }]}>
              <Input placeholder="订单创建契约测试" />
            </Form.Item>
          </Col>
        </Row>
        <Space wrap>
          <Button loading={state.generating} onClick={() => void generate()}>
            只读生成预览
          </Button>
          <Button
            type="primary"
            htmlType="submit"
            loading={state.acting}
            disabled={!state.generation || Boolean(state.proposal)}
          >
            创建待审核 Draft
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
      <Form.Item name="endpoint_variant" label="Endpoint Variant" rules={[{ required: true }]}>
        <Select
          aria-label="Endpoint Variant"
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
  const selectedApi = state.apis.data?.items.find((api) => api.id === apiDefinitionId)
  const serviceId = selectedApi?.service_id
  const query = useQuery({
    queryKey: ['test-engineering-endpoints', state.projectId, environmentId],
    queryFn: () => listServiceEndpoints(required(state.projectId), required(environmentId)),
    enabled: Boolean(state.projectId && environmentId && serviceId),
  })
  return {
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
  design,
  contractCompleteness,
  contractFingerprint,
  scenarioIds,
  onScenarioIdsChange,
  proposal,
  acting,
  onReview,
  onApply,
}: {
  design: TestDesignDocument
  contractCompleteness?: string
  contractFingerprint?: string
  scenarioIds: string[]
  onScenarioIdsChange: (ids: string[]) => void
  proposal: ReturnType<typeof useTestEngineering>['proposal']
  acting: boolean
  onReview: (accept: boolean) => Promise<boolean>
  onApply: () => Promise<boolean>
}) {
  const covered = design.coverage.entries.filter((entry) => entry.covered).length
  const total = design.coverage.entries.length
  const percent = total ? Math.round((covered * 100) / total) : 100
  return (
    <Space orientation="vertical" size={16} style={{ width: '100%' }}>
      <Card title="Test Intent / 审核状态">
        <Descriptions bordered size="small" column={2}>
          <Descriptions.Item label="Intent">{design.intent.objective}</Descriptions.Item>
          <Descriptions.Item label="Confidence">
            {(design.confidence * 100).toFixed(0)}%
          </Descriptions.Item>
          <Descriptions.Item label="Evidence">
            {design.evidence_refs.length} 条结构化引用
          </Descriptions.Item>
          <Descriptions.Item label="Contract Completeness">
            <Tag color={contractCompleteness === 'complete' ? 'green' : 'orange'}>
              {contractCompleteness ?? 'unknown'}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label="Contract Fingerprint">
            <Typography.Text code copyable>
              {contractFingerprint ?? 'unknown'}
            </Typography.Text>
          </Descriptions.Item>
          <Descriptions.Item label="Evidence Selection">
            API canonical + {Math.max(0, design.evidence_refs.length - 1)} 条关联 Evidence
          </Descriptions.Item>
          <Descriptions.Item label="State Capability">
            {design.review_requirements.includes('state_evidence_unavailable')
              ? '缺少显式状态证据'
              : '未启用'}
          </Descriptions.Item>
          <Descriptions.Item label="Review">
            {proposal ? (
              <Tag color={reviewColor(proposal.review_status)}>{proposal.review_status}</Tag>
            ) : (
              '未创建 Draft'
            )}
          </Descriptions.Item>
        </Descriptions>
        {design.warnings.map((warning) => (
          <Alert key={warning} type="warning" showIcon message={warning} />
        ))}
        <ProposalActions
          proposal={proposal}
          acting={acting}
          onReview={onReview}
          onApply={onApply}
        />
      </Card>
      <Card title={`Scenario Review · ${design.scenarios.length}`}>
        <ScenarioTable
          items={design.scenarios}
          selected={proposal?.scenario_ids ?? scenarioIds}
          disabled={Boolean(proposal)}
          onChange={onScenarioIdsChange}
        />
      </Card>
      <Row gutter={16}>
        <Col xs={24} xl={12}>
          <Card title="Oracle / Evidence Priority">
            <OracleTable items={design.oracles} />
          </Card>
        </Col>
        <Col xs={24} xl={12}>
          <Card
            title="Coverage / Gap"
            extra={<Progress width={46} type="circle" percent={percent} />}
          >
            <CoverageTable items={design.coverage.entries} />
          </Card>
        </Col>
      </Row>
      <Card title="Evidence References">
        <Table
          rowKey="id"
          size="small"
          pagination={false}
          dataSource={design.evidence_refs}
          columns={[
            { title: 'Type', dataIndex: 'source_type' },
            { title: 'Source', dataIndex: 'source_ref', ellipsis: true },
            { title: 'Revision', dataIndex: 'revision', ellipsis: true },
          ]}
        />
      </Card>
    </Space>
  )
}

function ProposalActions({
  proposal,
  acting,
  onReview,
  onApply,
}: {
  proposal: ReturnType<typeof useTestEngineering>['proposal']
  acting: boolean
  onReview: (accept: boolean) => Promise<boolean>
  onApply: () => Promise<boolean>
}) {
  if (!proposal) return null
  return (
    <Space wrap style={{ marginTop: 16 }}>
      {proposal.review_status === 'pending' ? (
        <>
          <Button type="primary" loading={acting} onClick={() => void onReview(true)}>
            接受 Draft
          </Button>
          <Button danger loading={acting} onClick={() => void onReview(false)}>
            拒绝 Draft
          </Button>
        </>
      ) : null}
      {proposal.review_status === 'accepted' && !proposal.applied ? (
        <Button type="primary" loading={acting} onClick={() => void onApply()}>
          物化为 Workflow / TestCase
        </Button>
      ) : null}
      {proposal.applied ? <Tag color="green">已进入执行体系</Tag> : null}
    </Space>
  )
}

function ScenarioTable({
  items,
  selected,
  disabled,
  onChange,
}: {
  items: ScenarioCandidate[]
  selected: string[]
  disabled: boolean
  onChange: (ids: string[]) => void
}) {
  return (
    <Table
      rowKey="id"
      size="small"
      pagination={false}
      dataSource={items}
      rowSelection={{
        selectedRowKeys: selected,
        onChange: (keys) => onChange(keys.map(String)),
        getCheckboxProps: (scenario) => ({
          disabled: disabled || !materializableScenario(scenario),
          name: materializableScenario(scenario)
            ? scenario.title
            : '仅设计：需要补全前置条件或可执行 Oracle',
        }),
      }}
      columns={[
        { title: 'Kind', dataIndex: 'kind' },
        { title: '标题', dataIndex: 'title' },
        {
          title: 'Location',
          render: (_: unknown, scenario: ScenarioCandidate) =>
            scenario.mutations.map((mutation) => mutation.location).join(', ') || 'request',
        },
        {
          title: 'Parameter Path',
          render: (_: unknown, scenario: ScenarioCandidate) =>
            scenario.mutations.map((mutation) => mutation.path).join(', ') || '-',
        },
        {
          title: 'Mutation',
          render: (_: unknown, scenario: ScenarioCandidate) =>
            scenario.mutations.map((mutation) => mutation.operation).join(', ') || '-',
        },
        {
          title: '预期分类',
          dataIndex: 'expected_category',
          render: (value: string) => <Tag>{value}</Tag>,
        },
        {
          title: '可执行性',
          render: (_: unknown, scenario: ScenarioCandidate) =>
            materializableScenario(scenario) ? (
              <Tag color="green">可物化</Tag>
            ) : (
              <Tag color="orange">仅设计</Tag>
            ),
        },
        {
          title: 'Evidence',
          render: (_: unknown, scenario: ScenarioCandidate) => scenario.evidence_refs.length,
        },
      ]}
    />
  )
}

function OracleTable({ items }: { items: OracleSpec[] }) {
  return (
    <Table
      rowKey="id"
      size="small"
      pagination={false}
      dataSource={items}
      columns={[
        { title: 'Kind', dataIndex: 'kind' },
        { title: 'Operator', dataIndex: 'operator' },
        { title: 'Expected', dataIndex: 'expected', render: (value) => JSON.stringify(value) },
        { title: 'Evidence', render: (_, item) => item.evidence_refs.length },
        {
          title: 'Review',
          render: (_, item) =>
            item.requires_review ? <Tag color="orange">需要</Tag> : <Tag color="green">确定性</Tag>,
        },
      ]}
    />
  )
}

function CoverageTable({ items }: { items: CoverageEntry[] }) {
  return (
    <Table
      rowKey={(item) => `${item.dimension}:${item.target_ref}:${item.requirement}`}
      size="small"
      pagination={{ pageSize: 8 }}
      dataSource={items}
      columns={[
        { title: 'Dimension', dataIndex: 'dimension' },
        { title: 'Requirement', dataIndex: 'requirement', ellipsis: true },
        {
          title: '状态',
          dataIndex: 'covered',
          render: (value: boolean) =>
            value ? <Tag color="green">已覆盖</Tag> : <Tag color="red">Gap</Tag>,
        },
      ]}
    />
  )
}

function reviewColor(status: 'pending' | 'accepted' | 'rejected'): string {
  if (status === 'accepted') return 'green'
  if (status === 'rejected') return 'default'
  return 'orange'
}

function materializableScenario(scenario: ScenarioCandidate): boolean {
  return (
    !scenario.requires_review &&
    scenario.deterministic &&
    !scenario.mutations.some(
      (mutation) => mutation.location === 'path' && mutation.operation === 'omit',
    )
  )
}
