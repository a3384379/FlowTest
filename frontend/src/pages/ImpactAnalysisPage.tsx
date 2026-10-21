import CatalogPagination from '../components/CatalogPagination'
import { BranchesOutlined, DeleteOutlined, LinkOutlined, PlusOutlined } from '@ant-design/icons'
import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Empty,
  Form,
  Input,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
} from 'antd'
import { useMemo, useState } from 'react'

import { apiErrorWithTrace, type Page } from '../lib/api'
import type {
  ImpactCatalog,
  ImpactMapping,
  ImpactRunInput,
  ImpactSourceKind,
  ImpactTargetType,
} from '../features/impact/impact-service'
import ImpactEvidenceWorkspace from '../features/impact/ImpactEvidenceWorkspace'
import { useImpactAnalysis } from '../features/impact/use-impact-analysis'
import QueryFailureNotice from '../components/QueryFailureNotice'
import ContractServiceContextNotice from '../features/services/ContractServiceContextNotice'
import { useProjectContext } from '../features/projects/use-project-context'

type MappingForm = {
  source_kind: ImpactSourceKind
  source_selector: string
  target: string
}

type AnalysisForm = {
  title: string
  source_ref: string
  git_diff?: string
  openapi_baseline?: string
  openapi_current?: string
  schema_baseline?: string
  schema_current?: string
}

const sourceLabels: Record<ImpactSourceKind, string> = {
  git: 'Git',
  openapi: 'OpenAPI',
  graphql: 'GraphQL',
  grpc: 'Proto / gRPC',
}

const targetLabels: Record<ImpactTargetType, string> = {
  test_case: '测试用例',
  workflow: '工作流',
  openapi_contract: 'OpenAPI 契约',
  pact_contract: 'Pact 契约',
  performance: '性能场景',
}

export default function ImpactAnalysisPage() {
  const { projectId } = useProjectContext()
  return <ImpactAnalysisWorkspace key={projectId ?? 'none'} />
}

function ImpactAnalysisWorkspace() {
  const state = useImpactAnalysis()
  const [mappingOpen, setMappingOpen] = useState(false)
  const [analysisOpen, setAnalysisOpen] = useState(false)
  const { detail, mappingPage, mappings, closed } = impactReadData(state)
  return (
    <>
      <ContractServiceContextNotice
        projectId={state.projectId}
        context={state.serviceContext}
        description="影响记录按冻结的目录服务标识精确关联；未记录关联的旧分析保留在项目范围。"
      />
      <div className="page-heading">
        <div>
          <Space align="center">
            <Typography.Title level={2}>变更影响分析</Typography.Title>
            <Tag color="purple">V3 · S28</Tag>
          </Space>
          <Typography.Text type="secondary">
            对 Git、OpenAPI、GraphQL 与 Proto 变更建立可解释影响图，生成智能测试选择与覆盖矩阵。
          </Typography.Text>
        </div>
        <Space>
          <Button
            disabled={!state.canEdit}
            icon={<LinkOutlined />}
            onClick={() => setMappingOpen(true)}
          >
            登记资产映射
          </Button>
          <Button
            disabled={!state.canEdit}
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setAnalysisOpen(true)}
          >
            新建影响分析
          </Button>
        </Space>
      </div>
      <QueryFailureNotice
        queries={[state.flags, state.permissions, state.mappings, state.catalog, state.runs]}
      />
      {state.flags.data?.impact_engine === false ? (
        <Alert showIcon className="page-alert" type="info" title="影响分析尚未启用" />
      ) : null}
      <Alert
        showIcon
        type="info"
        className="page-alert"
        title="确定性映射，不执行仓库命令"
        description="仅解析有边界的标准 unified diff 与平台内已登记 Schema 版本；每个推荐资产都保留命中选择器和变更路径。"
      />
      <div className="catalog-controls">
        <CatalogPagination query={state.mappings} label="影响映射" />
        <CatalogPagination query={state.runs} label="分析历史" />
      </div>
      <ImpactOverview detail={detail} mappingPage={mappingPage} closed={closed} />
      <AnalysisEvidenceState state={state} />
      <Row gutter={16}>
        <Col xs={24} lg={14}>
          <RunHistory
            runs={state.runs.data?.items ?? []}
            selectedRunId={state.selectedRunId}
            loading={state.runs.isLoading}
            onSelect={state.setSelectedRunId}
          />
        </Col>
        <Col xs={24} lg={10}>
          <MappingTable
            mappings={mappings}
            loading={state.mappings.isLoading}
            deleting={state.mappingPending}
            readOnly={!state.canEdit}
            onDelete={state.deleteMapping}
          />
        </Col>
      </Row>
      {mappingOpen ? (
        <MappingDialog
          open
          catalog={state.catalog.data}
          submitting={state.mappingPending}
          onClose={() => setMappingOpen(false)}
          onSubmit={async (input) => {
            const succeeded = await state.registerMapping(input)
            if (succeeded) setMappingOpen(false)
          }}
        />
      ) : null}
      {analysisOpen ? (
        <AnalysisDialog
          open
          catalog={state.catalog.data}
          submitting={state.analyzing}
          onClose={() => setAnalysisOpen(false)}
          onSubmit={async (input) => {
            const succeeded = await state.analyze(input)
            if (succeeded) setAnalysisOpen(false)
          }}
        />
      ) : null}
    </>
  )
}

function impactReadData(state: ReturnType<typeof useImpactAnalysis>) {
  const detail =
    state.serviceContext.ready && state.detail.isSuccess ? state.detail.data : undefined
  const mappingPage =
    state.serviceContext.enabled && state.mappings.isSuccess ? state.mappings.data : undefined
  return {
    detail,
    mappingPage,
    mappings: mappingPage?.items ?? [],
    closed: state.flags.data?.impact_engine === false,
  }
}

function AnalysisEvidenceState({ state }: { state: ReturnType<typeof useImpactAnalysis> }) {
  const detail =
    state.serviceContext.ready && state.detail.isSuccess ? state.detail.data : undefined
  return state.serviceContext.ready && state.detail.isError ? (
    <Alert
      showIcon
      type="error"
      title="所选影响分析读取失败"
      description={apiErrorWithTrace(state.detail.error)}
      action={<Button onClick={() => void state.detail.refetch()}>重试</Button>}
    />
  ) : (
    <AnalysisWorkspace
      detail={detail}
      state={state}
      loading={state.detail.isLoading}
      scoped={Boolean(state.serviceContext.selection.id)}
      unavailable={
        Boolean(state.serviceContext.selection.error) ||
        state.serviceContext.selected.isError ||
        state.runs.isError ||
        state.detail.isError
      }
    />
  )
}

function ImpactOverview({
  detail,
  mappingPage,
  closed,
}: {
  detail: ReturnType<typeof useImpactAnalysis>['detail']['data']
  mappingPage?: Page<ImpactMapping>
  closed: boolean
}) {
  return (
    <Row gutter={16} className="performance-overview">
      <Col xs={12} lg={6}>
        <Card>
          <Statistic
            title="变更项"
            value={detail?.change_count ?? '未提供'}
            prefix={<BranchesOutlined />}
          />
        </Card>
      </Col>
      <Col xs={12} lg={6}>
        <Card>
          <Statistic title="破坏性变更" value={detail?.summary.breaking_change_count ?? '未提供'} />
        </Card>
      </Col>
      <Col xs={12} lg={6}>
        <Card>
          <Statistic title="推荐资产" value={detail?.summary.selected_asset_count ?? '未提供'} />
        </Card>
      </Col>
      <Col xs={12} lg={6}>
        <Card>
          <Statistic
            title="项目显式映射"
            value={mappingCountLabel(mappingPage, closed)}
            prefix={<LinkOutlined />}
          />
          {mappingPage !== undefined && (
            <Typography.Text type="secondary">
              本页已载入 {mappingPage.items.length} 项
            </Typography.Text>
          )}
        </Card>
      </Col>
    </Row>
  )
}

function mappingCountLabel(
  page: Page<ImpactMapping> | undefined,
  closed: boolean,
): number | string {
  if (closed) return '已关闭'
  return page?.total ?? '未提供'
}

function AnalysisWorkspace({
  detail,
  state,
  loading,
  scoped,
  unavailable,
}: {
  detail: ReturnType<typeof useImpactAnalysis>['detail']['data']
  state: ReturnType<typeof useImpactAnalysis>
  loading: boolean
  scoped: boolean
  unavailable: boolean
}) {
  if (!detail)
    return <EmptyAnalysisWorkspace loading={loading} scoped={scoped} unavailable={unavailable} />
  return (
    <ImpactEvidenceWorkspace
      key={`${state.projectId}:${detail.id}`}
      projectId={state.projectId!}
      detail={detail}
      changeKey={state.selectedChangeKey}
      assetKey={state.selectedAssetKey}
      onChange={(key) => state.selectEvidence('change', key)}
      onAsset={(key) => state.selectEvidence('asset', key)}
    />
  )
}

function EmptyAnalysisWorkspace({
  loading,
  scoped,
  unavailable,
}: {
  loading: boolean
  scoped: boolean
  unavailable: boolean
}) {
  return (
    <Card className="performance-card" loading={loading}>
      {!loading ? (
        <Empty
          description={
            unavailable
              ? '请先恢复影响记录读取或修正服务定位'
              : scoped
                ? '当前服务未记录可确认的影响分析'
                : '登记映射并创建首个影响分析'
          }
        />
      ) : null}
    </Card>
  )
}

function RunHistory({
  runs,
  selectedRunId,
  loading,
  onSelect,
}: {
  runs: Array<{
    id: string
    title: string
    source_ref: string
    change_count: number
    summary: { coverage_percent: number }
    created_at: string
  }>
  selectedRunId: string | null
  loading: boolean
  onSelect: (value: string) => void
}) {
  return (
    <Card title="分析历史" className="performance-card">
      <Table
        rowKey="id"
        size="small"
        loading={loading}
        pagination={{ pageSize: 6 }}
        dataSource={runs}
        onRow={(item) => ({ onClick: () => onSelect(item.id) })}
        rowClassName={(item) => (item.id === selectedRunId ? 'impact-run-selected' : '')}
        columns={[
          { title: '名称', dataIndex: 'title' },
          { title: '来源引用', dataIndex: 'source_ref', render: (value: string) => value || '-' },
          { title: '变更', dataIndex: 'change_count', width: 70 },
          { title: '覆盖率', render: (_, item) => `${item.summary.coverage_percent}%` },
          {
            title: '创建时间',
            dataIndex: 'created_at',
            render: (value: string) => new Date(value).toLocaleString('zh-CN'),
          },
        ]}
      />
    </Card>
  )
}

function MappingTable({
  mappings,
  loading,
  readOnly,
  deleting,
  onDelete,
}: {
  mappings: ImpactMapping[]
  loading: boolean
  readOnly: boolean
  deleting: boolean
  onDelete: (id: string) => Promise<void>
}) {
  return (
    <Card title="显式资产映射" className="performance-card">
      <Table
        rowKey="id"
        size="small"
        loading={loading}
        pagination={{ pageSize: 6 }}
        dataSource={mappings}
        columns={[
          {
            title: '选择器',
            render: (_, item) => (
              <Space orientation="vertical" size={0}>
                <Typography.Text code>{item.source_selector}</Typography.Text>
                <Typography.Text type="secondary">{sourceLabels[item.source_kind]}</Typography.Text>
              </Space>
            ),
          },
          {
            title: '目标',
            render: (_, item) => (
              <Space orientation="vertical" size={0}>
                <Typography.Text>{item.target_name}</Typography.Text>
                <Typography.Text type="secondary">{targetLabels[item.target_type]}</Typography.Text>
              </Space>
            ),
          },
          {
            title: '',
            width: 48,
            render: (_, item) => (
              <Popconfirm title="确认删除此映射？" onConfirm={() => void onDelete(item.id)}>
                <Button
                  aria-label={`删除映射 ${item.source_selector}`}
                  type="text"
                  danger
                  loading={deleting}
                  disabled={readOnly}
                  icon={<DeleteOutlined />}
                />
              </Popconfirm>
            ),
          },
        ]}
      />
    </Card>
  )
}

function MappingDialog({
  open,
  catalog,
  submitting,
  onClose,
  onSubmit,
}: {
  open: boolean
  catalog?: ImpactCatalog
  submitting: boolean
  onClose: () => void
  onSubmit: (
    input: Pick<ImpactMapping, 'source_kind' | 'source_selector' | 'target_type' | 'target_id'>,
  ) => Promise<void>
}) {
  const [form] = Form.useForm<MappingForm>()
  const options = useMemo(
    () =>
      (catalog?.targets ?? []).map((item) => ({
        value: `${item.target_type}:${item.id}`,
        label: `${targetLabels[item.target_type]} · ${item.name}${item.version == null ? '' : ` · v${item.version}`}`,
      })),
    [catalog],
  )
  return (
    <Modal
      title="登记影响资产映射"
      open={open}
      onCancel={onClose}
      onOk={() => form.submit()}
      confirmLoading={submitting}
      destroyOnHidden
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={{ source_kind: 'git' }}
        onFinish={(values) => {
          const [target_type, target_id] = values.target.split(':') as [ImpactTargetType, string]
          void onSubmit({
            source_kind: values.source_kind,
            source_selector: values.source_selector,
            target_type,
            target_id,
          })
        }}
      >
        <Form.Item name="source_kind" label="变更来源" rules={[{ required: true }]}>
          <Select
            aria-label="变更来源"
            options={Object.entries(sourceLabels).map(([value, label]) => ({ value, label }))}
          />
        </Form.Item>
        <Form.Item
          name="source_selector"
          label="来源选择器"
          extra="精确匹配，或仅在末尾使用 * 进行前缀匹配"
          rules={[{ required: true, message: '请输入来源选择器' }, { max: 512 }]}
        >
          <Input placeholder="例如 backend/app/api/* 或 GET /users" />
        </Form.Item>
        <Form.Item
          name="target"
          label="关联平台资产"
          rules={[{ required: true, message: '请选择平台资产' }]}
        >
          <Select
            showSearch
            optionFilterProp="label"
            aria-label="关联平台资产"
            options={options}
            placeholder="选择 Case、Workflow、Contract 或性能场景"
          />
        </Form.Item>
      </Form>
    </Modal>
  )
}

function AnalysisDialog({
  open,
  catalog,
  submitting,
  onClose,
  onSubmit,
}: {
  open: boolean
  catalog?: ImpactCatalog
  submitting: boolean
  onClose: () => void
  onSubmit: (input: ImpactRunInput) => Promise<void>
}) {
  const [form] = Form.useForm<AnalysisForm>()
  const openapi = catalog?.targets.filter((item) => item.target_type === 'openapi_contract') ?? []
  const schemas = catalog?.schemas ?? []
  const openapiOptions = openapi.map((item) => ({
    value: item.id,
    label: `${item.name}${item.version == null ? '' : ` · v${item.version}`}`,
  }))
  const schemaOptions = schemas.map((item) => ({
    value: item.id,
    label: `${sourceLabels[item.protocol]} · ${item.name} · v${item.version}`,
  }))
  return (
    <Modal
      width={760}
      title="新建变更影响分析"
      open={open}
      onCancel={onClose}
      onOk={() => form.submit()}
      confirmLoading={submitting}
      destroyOnHidden
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={{ title: '变更影响分析' }}
        onFinish={(values) => submitAnalysis(form, values, onSubmit)}
      >
        <Row gutter={16}>
          <Col xs={24} lg={14}>
            <Form.Item
              name="title"
              label="分析名称"
              rules={[{ required: true, message: '请输入分析名称' }]}
            >
              <Input />
            </Form.Item>
          </Col>
          <Col xs={24} lg={10}>
            <Form.Item name="source_ref" label="来源引用">
              <Input placeholder="例如 feature/FT-128" />
            </Form.Item>
          </Col>
        </Row>
        <Form.Item
          name="git_diff"
          label="标准 Git unified diff"
          extra="最大 2 MB、500 个文件、100000 行；不会执行 git 或访问远端仓库"
        >
          <Input.TextArea
            aria-label="标准 Git unified diff"
            rows={7}
            placeholder={
              'diff --git a/backend/app.py b/backend/app.py\n--- a/backend/app.py\n+++ b/backend/app.py\n@@ -1 +1 @@'
            }
          />
        </Form.Item>
        <Descriptions title="OpenAPI 版本对比（可选）" size="small" column={2}>
          <Descriptions.Item label="基线">
            <Form.Item name="openapi_baseline" noStyle>
              <Select
                allowClear
                aria-label="OpenAPI 基线"
                style={{ width: 260 }}
                options={openapiOptions}
              />
            </Form.Item>
          </Descriptions.Item>
          <Descriptions.Item label="当前">
            <Form.Item name="openapi_current" noStyle>
              <Select
                allowClear
                aria-label="OpenAPI 当前版本"
                style={{ width: 260 }}
                options={openapiOptions}
              />
            </Form.Item>
          </Descriptions.Item>
        </Descriptions>
        <Descriptions
          title="GraphQL / Proto 版本对比（可选）"
          size="small"
          column={2}
          className="impact-schema-selectors"
        >
          <Descriptions.Item label="基线">
            <Form.Item name="schema_baseline" noStyle>
              <Select
                allowClear
                aria-label="Schema 基线"
                style={{ width: 260 }}
                options={schemaOptions}
              />
            </Form.Item>
          </Descriptions.Item>
          <Descriptions.Item label="当前">
            <Form.Item name="schema_current" noStyle>
              <Select
                allowClear
                aria-label="Schema 当前版本"
                style={{ width: 260 }}
                options={schemaOptions}
              />
            </Form.Item>
          </Descriptions.Item>
        </Descriptions>
      </Form>
    </Modal>
  )
}

function submitAnalysis(
  form: ReturnType<typeof Form.useForm<AnalysisForm>>[0],
  values: AnalysisForm,
  onSubmit: (input: ImpactRunInput) => Promise<void>,
): void {
  const gitDiff = values.git_diff?.trim() || undefined
  const openapiDiffs = referencePair(
    values.openapi_baseline,
    values.openapi_current,
    (baseline, current) => ({
      baseline_run_id: baseline,
      current_run_id: current,
    }),
  )
  const schemaDiffs = referencePair(
    values.schema_baseline,
    values.schema_current,
    (baseline, current) => ({
      baseline_artifact_id: baseline,
      current_artifact_id: current,
    }),
  )
  if (!gitDiff && openapiDiffs.length === 0 && schemaDiffs.length === 0) {
    form.setFields([{ name: 'git_diff', errors: ['至少提供 Git Diff 或一组完整 Schema 版本'] }])
    return
  }
  void onSubmit({
    title: values.title,
    source_ref: values.source_ref ?? '',
    git_diff: gitDiff,
    openapi_diffs: openapiDiffs,
    schema_diffs: schemaDiffs,
  })
}

function referencePair<T>(
  baseline: string | undefined,
  current: string | undefined,
  build: (baseline: string, current: string) => T,
): T[] {
  return baseline && current ? [build(baseline, current)] : []
}
