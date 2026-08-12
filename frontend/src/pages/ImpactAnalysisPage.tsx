import { BranchesOutlined, DeleteOutlined, LinkOutlined, PlusOutlined } from '@ant-design/icons'
import {
  Alert,
  Badge,
  Button,
  Card,
  Col,
  Descriptions,
  Empty,
  Form,
  Input,
  Modal,
  Popconfirm,
  Progress,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
} from 'antd'
import { useMemo, useState } from 'react'

import type {
  ImpactCatalog,
  ImpactChange,
  ImpactMapping,
  ImpactRunInput,
  ImpactSourceKind,
  ImpactTargetType,
  SelectedAsset,
} from '../features/impact/impact-service'
import { useImpactAnalysis } from '../features/impact/use-impact-analysis'

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
  const state = useImpactAnalysis()
  const [mappingOpen, setMappingOpen] = useState(false)
  const [analysisOpen, setAnalysisOpen] = useState(false)
  const detail = state.detail.data
  const mappings = state.mappings.data?.items ?? []
  return (
    <>
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
          <Button icon={<LinkOutlined />} onClick={() => setMappingOpen(true)}>
            登记资产映射
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setAnalysisOpen(true)}>
            新建影响分析
          </Button>
        </Space>
      </div>
      <Alert
        showIcon
        type="info"
        className="page-alert"
        title="确定性映射，不执行仓库命令"
        description="仅解析有边界的标准 unified diff 与平台内已登记 Schema 版本；每个推荐资产都保留命中选择器和变更路径。"
      />
      <ImpactOverview detail={detail} mappingCount={mappings.length} />
      <AnalysisWorkspace detail={detail} loading={state.detail.isLoading} />
      <CoverageMatrix detail={detail} />
      <Row gutter={16}>
        <Col span={14}>
          <RunHistory
            runs={state.runs.data?.items ?? []}
            selectedRunId={state.selectedRunId}
            loading={state.runs.isLoading}
            onSelect={state.setSelectedRunId}
          />
        </Col>
        <Col span={10}>
          <MappingTable
            mappings={mappings}
            loading={state.mappings.isLoading}
            deleting={state.mappingPending}
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

function ImpactOverview({
  detail,
  mappingCount,
}: {
  detail: ReturnType<typeof useImpactAnalysis>['detail']['data']
  mappingCount: number
}) {
  return (
    <Row gutter={16} className="performance-overview">
      <Col span={6}>
        <Card>
          <Statistic
            title="变更项"
            value={detail?.change_count ?? 0}
            prefix={<BranchesOutlined />}
          />
        </Card>
      </Col>
      <Col span={6}>
        <Card>
          <Statistic title="破坏性变更" value={detail?.summary.breaking_change_count ?? 0} />
        </Card>
      </Col>
      <Col span={6}>
        <Card>
          <Statistic title="推荐资产" value={detail?.summary.selected_asset_count ?? 0} />
        </Card>
      </Col>
      <Col span={6}>
        <Card>
          <Statistic title="显式映射" value={mappingCount} prefix={<LinkOutlined />} />
        </Card>
      </Col>
    </Row>
  )
}

function AnalysisWorkspace({
  detail,
  loading,
}: {
  detail: ReturnType<typeof useImpactAnalysis>['detail']['data']
  loading: boolean
}) {
  if (!detail) return <EmptyAnalysisWorkspace loading={loading} />
  return <AnalysisContent detail={detail} />
}

function EmptyAnalysisWorkspace({ loading }: { loading: boolean }) {
  return (
    <Card className="performance-card" loading={loading}>
      {!loading ? <Empty description="登记映射并创建首个影响分析" /> : null}
    </Card>
  )
}

function AnalysisContent({
  detail,
}: {
  detail: NonNullable<ReturnType<typeof useImpactAnalysis>['detail']['data']>
}) {
  return (
    <Card
      className="performance-card"
      title={`${detail.title} · ${detail.source_ref || '未指定来源引用'}`}
      extra={<Tag color="success">证据已保存</Tag>}
    >
      <div className="impact-workspace">
        <ImpactColumn title="① 变更" count={detail.changes.length}>
          {detail.changes.map((change) => (
            <ChangeItem key={change.key} change={change} />
          ))}
        </ImpactColumn>
        <ImpactColumn title="② 受影响资产" count={detail.graph.edges.length}>
          {detail.selection.selected_assets.map((asset) => (
            <AssetItem key={`${asset.target_type}:${asset.target_id}`} asset={asset} showReasons />
          ))}
          {detail.selection.selected_assets.length === 0 ? (
            <Empty description="暂无命中资产" />
          ) : null}
        </ImpactColumn>
        <ImpactColumn title="③ 推荐测试集" count={detail.selection.selected_assets.length}>
          {detail.selection.selected_assets.map((asset) => (
            <AssetItem key={`${asset.target_type}:${asset.target_id}`} asset={asset} />
          ))}
          {detail.selection.selected_assets.length === 0 ? (
            <Empty description="需要补充显式映射" />
          ) : null}
        </ImpactColumn>
      </div>
    </Card>
  )
}

function ImpactColumn({
  title,
  count,
  children,
}: {
  title: string
  count: number
  children: React.ReactNode
}) {
  return (
    <section className="impact-column">
      <div className="impact-column-title">
        <Typography.Text strong>{title}</Typography.Text>
        <Badge count={count} showZero />
      </div>
      <div className="impact-column-body">{children}</div>
    </section>
  )
}

function ChangeItem({ change }: { change: ImpactChange }) {
  const color =
    change.severity === 'breaking' ? 'error' : change.severity === 'warning' ? 'warning' : 'blue'
  return (
    <article className={`impact-item impact-item-${change.severity}`}>
      <Space wrap>
        <Tag color={color}>{severityLabel(change.severity)}</Tag>
        <Tag>{sourceLabels[change.source_kind]}</Tag>
      </Space>
      <Typography.Text strong>{change.label}</Typography.Text>
      <Typography.Text type="secondary">{change.detail}</Typography.Text>
    </article>
  )
}

function AssetItem({
  asset,
  showReasons = false,
}: {
  asset: SelectedAsset
  showReasons?: boolean
}) {
  return (
    <article className="impact-item">
      <Space wrap>
        <Tag color={asset.risk === 'high' ? 'error' : asset.risk === 'medium' ? 'warning' : 'blue'}>
          {riskLabel(asset.risk)}
        </Tag>
        <Tag>{targetLabels[asset.target_type]}</Tag>
      </Space>
      <Typography.Text strong>{asset.name}</Typography.Text>
      {showReasons ? (
        asset.reasons.map((reason) => (
          <Typography.Text type="secondary" key={reason}>
            {reason}
          </Typography.Text>
        ))
      ) : (
        <Typography.Text type="secondary">覆盖 {asset.change_keys.length} 个变更</Typography.Text>
      )}
    </article>
  )
}

function CoverageMatrix({
  detail,
}: {
  detail: ReturnType<typeof useImpactAnalysis>['detail']['data']
}) {
  const coverage = detail?.coverage
  return (
    <Card
      title="Test Mapping / Coverage Matrix"
      className="performance-card"
      extra={
        coverage ? <Progress type="circle" size={54} percent={coverage.coverage_percent} /> : null
      }
    >
      <Table
        rowKey="change_key"
        size="small"
        pagination={false}
        dataSource={coverage?.matrix ?? []}
        locale={{ emptyText: '暂无覆盖快照' }}
        columns={[
          { title: '变更', dataIndex: 'label' },
          {
            title: '来源',
            dataIndex: 'source_kind',
            render: (value: ImpactSourceKind) => sourceLabels[value],
          },
          { title: 'Case', dataIndex: 'case_count', width: 70 },
          { title: 'Workflow', dataIndex: 'workflow_count', width: 90 },
          { title: 'Contract', dataIndex: 'contract_count', width: 90 },
          { title: '性能', dataIndex: 'performance_count', width: 70 },
          {
            title: '覆盖',
            dataIndex: 'covered',
            render: (value: boolean) => (
              <Tag color={value ? 'success' : 'error'}>{value ? '已覆盖' : '缺口'}</Tag>
            ),
          },
        ]}
      />
      {coverage?.gaps.length ? (
        <Alert
          className="impact-gap-alert"
          type="warning"
          showIcon
          title={`${coverage.gaps.length} 个覆盖缺口`}
          description={coverage.gaps.map((gap) => gap.source_key).join('、')}
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
  deleting,
  onDelete,
}: {
  mappings: ImpactMapping[]
  loading: boolean
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
          <Col span={14}>
            <Form.Item
              name="title"
              label="分析名称"
              rules={[{ required: true, message: '请输入分析名称' }]}
            >
              <Input />
            </Form.Item>
          </Col>
          <Col span={10}>
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

function severityLabel(value: ImpactChange['severity']): string {
  return value === 'breaking' ? '破坏性' : value === 'warning' ? '需关注' : '信息'
}

function riskLabel(value: SelectedAsset['risk']): string {
  return value === 'high' ? '高风险' : value === 'medium' ? '中风险' : '常规'
}
