import { useQuery } from '@tanstack/react-query'
import {
  Alert,
  Button,
  Descriptions,
  Drawer,
  Empty,
  Select,
  Space,
  Spin,
  Table,
  Tabs,
  Tag,
  Typography,
} from 'antd'
import { Link } from 'react-router-dom'
import { useId } from 'react'
import {
  apiErrorMessage,
  type Environment,
  type TestCase,
  type TestCaseDefinition,
  type TestSuite,
  type TestSuiteItem,
  type Workflow,
} from '../../lib/api'
import { projectPath } from '../projects/project-routing'
import {
  getAsset,
  listAssetPlans,
  type AssetKind,
  type PublishedAssetTarget,
} from './asset-workspace-service'
import { listTestCaseVersions, listTestSuiteVersions } from './test-asset-service'
import AssetRunEvidence from './AssetRunEvidence'
import type { useAssetHistory } from './use-asset-history'

export type AssetDetailProps = {
  projectId: string
  kind: AssetKind
  id: string
  version?: number | 'draft'
  workflows: Workflow[]
  environments: Environment[]
  cases: TestCase[]
  history: ReturnType<typeof useAssetHistory>
  canEdit: boolean
  canExecute: boolean
  onVersion: (version: number | 'draft') => void
  onClose: () => void
  onEditCase: (item: TestCase) => void
  onEditSuite: (item: TestSuite) => void
  onPlan: (target: PublishedAssetTarget, execute: boolean) => void
}

export default function AssetDetailDrawer(props: AssetDetailProps) {
  const titleId = useId()
  const asset = useQuery({
    queryKey: ['test-asset', props.projectId, props.kind, props.id],
    queryFn: () => getAsset(props.projectId, props.kind, props.id),
  })
  return (
    <Drawer
      open
      title={<span id={titleId}>测试资产详情</span>}
      aria-labelledby={titleId}
      size={520}
      className="asset-detail-drawer"
      onClose={props.onClose}
      destroyOnHidden
    >
      {asset.isPending && <Spin aria-label="读取资产详情" />}
      {asset.error && <AssetQueryError error={asset.error} onRetry={() => void asset.refetch()} />}
      {asset.data && <AssetDetailBody {...props} asset={asset.data} />}
    </Drawer>
  )
}

function AssetDetailBody(props: AssetDetailProps & { asset: TestCase | TestSuite }) {
  const { asset } = props
  const capabilities = {
    canEdit: props.canEdit && !asset.archived_at,
    canExecute: props.canExecute && !asset.archived_at,
  }
  return (
    <>
      <Typography.Title level={4}>{asset.name}</Typography.Title>
      <Typography.Paragraph type="secondary">
        {asset.description || '暂无说明'}
      </Typography.Paragraph>
      {asset.archived_at && <Alert type="info" title="此资产已删除，历史版本与执行证据仍可查看" />}
      <Space wrap>
        {asset.tags.map((tag) => (
          <Tag key={tag}>{tag}</Tag>
        ))}
      </Space>
      {props.kind === 'case' ? (
        <CaseDetail {...props} {...capabilities} asset={asset as TestCase} />
      ) : (
        <SuiteDetail {...props} {...capabilities} asset={asset as TestSuite} />
      )}
    </>
  )
}

function CaseDetail(props: AssetDetailProps & { asset: TestCase }) {
  const versions = useQuery({
    queryKey: ['test-case-versions', props.projectId, props.id],
    queryFn: () => listTestCaseVersions(props.projectId, props.id),
  })
  const availableVersions = versions.data ?? []
  const selected = props.version ?? props.asset.current_version ?? 'draft'
  const published = versions.data?.find((version) => version.version === selected)
  const definition = selected === 'draft' ? props.asset.draft_definition : published?.definition
  return (
    <>
      <DetailActions
        {...props}
        asset={props.asset}
        selected={selected}
        versions={availableVersions}
        published={Boolean(published)}
        onEdit={() => props.onEditCase(props.asset)}
      />
      {versions.error && (
        <AssetQueryError error={versions.error} onRetry={() => void versions.refetch()} />
      )}
      <Tabs
        animated={false}
        items={[
          {
            key: 'binding',
            label: '绑定与版本',
            children: definition ? (
              <CaseBinding
                projectId={props.projectId}
                definition={definition}
                workflows={props.workflows}
                environments={props.environments}
                draft={selected === 'draft'}
              />
            ) : (
              <Empty
                description={
                  versions.isPending ? '正在读取发布版本' : '指定发布版本不存在，未切换到其他版本'
                }
              />
            ),
          },
          {
            key: 'runs',
            label: '执行与报告',
            children: (
              <AssetRunEvidence
                {...props}
                versions={availableVersions.map((item) => item.version)}
              />
            ),
          },
          { key: 'plans', label: '关联计划', children: <RelatedPlans {...props} /> },
        ]}
      />
    </>
  )
}

function SuiteDetail(props: AssetDetailProps & { asset: TestSuite }) {
  const versions = useQuery({
    queryKey: ['test-suite-versions', props.projectId, props.id],
    queryFn: () => listTestSuiteVersions(props.projectId, props.id),
  })
  const availableVersions = versions.data ?? []
  const selected = props.version ?? props.asset.current_version ?? 'draft'
  const published = versions.data?.find((version) => version.version === selected)
  const definition = selected === 'draft' ? props.asset.draft_definition : published?.definition
  return (
    <>
      <DetailActions
        {...props}
        asset={props.asset}
        selected={selected}
        versions={availableVersions}
        published={Boolean(published)}
        onEdit={() => props.onEditSuite(props.asset)}
      />
      {versions.error && (
        <AssetQueryError error={versions.error} onRetry={() => void versions.refetch()} />
      )}
      <Tabs
        animated={false}
        items={[
          {
            key: 'members',
            label: '固定用例版本',
            children: definition ? (
              <SuiteMembers {...props} items={definition.items} draft={selected === 'draft'} />
            ) : (
              <Empty
                description={
                  versions.isPending ? '正在读取发布版本' : '指定发布版本不存在，未切换到其他版本'
                }
              />
            ),
          },
          {
            key: 'runs',
            label: '执行与报告',
            children: (
              <AssetRunEvidence
                {...props}
                versions={availableVersions.map((item) => item.version)}
              />
            ),
          },
          { key: 'plans', label: '关联计划', children: <RelatedPlans {...props} /> },
        ]}
      />
    </>
  )
}

function DetailActions(
  props: AssetDetailProps & {
    asset: TestCase | TestSuite
    selected: number | 'draft'
    versions: Array<{ version: number }>
    published: boolean
    onEdit: () => void
  },
) {
  const target = {
    kind: props.kind,
    id: props.id,
    name: props.asset.name,
    version: Number(props.selected),
  }
  return (
    <div className="asset-detail-actions">
      <Select
        aria-label="查看资产版本"
        value={props.selected}
        onChange={props.onVersion}
        options={[
          { value: 'draft', label: '当前草稿' },
          ...props.versions.map((item) => ({
            value: item.version,
            label: `已发布 v${item.version}`,
          })),
        ]}
      />
      <Typography.Paragraph type="secondary">
        {props.selected === 'draft'
          ? '草稿仅用于编辑；先发布后才能加入计划或执行。'
          : `正在查看不可变的发布版本 v${props.selected}。`}
      </Typography.Paragraph>
      <Space wrap>
        <Button disabled={!props.canEdit} onClick={props.onEdit}>
          编辑当前草稿
        </Button>
        <Button
          disabled={!props.canEdit || !props.published}
          onClick={() => props.onPlan(target, false)}
        >
          加入计划
        </Button>
        <Button
          type="primary"
          aria-label="执行"
          disabled={!props.canEdit || !props.canExecute || !props.published}
          onClick={() => props.onPlan(target, true)}
        >
          执行
        </Button>
      </Space>
    </div>
  )
}

function CaseBinding({
  projectId,
  definition,
  workflows,
  environments,
  draft,
}: {
  projectId: string
  definition: TestCaseDefinition
  workflows: Workflow[]
  environments: Environment[]
  draft: boolean
}) {
  const workflow = workflows.find((item) => item.id === definition.workflow_id)
  const environment = environments.find((item) => item.id === definition.environment_id)
  return (
    <>
      <Descriptions
        column={1}
        size="small"
        bordered
        items={[
          { key: 'mode', label: '定义来源', children: draft ? '当前草稿' : '已发布用例的冻结定义' },
          {
            key: 'workflow',
            label: '绑定流程',
            children: (
              <Space wrap>
                {workflow?.name ?? definition.workflow_id}
                <Link to={`${projectPath(projectId, 'workflows')}?focus=${definition.workflow_id}`}>
                  打开流程
                </Link>
              </Space>
            ),
          },
          {
            key: 'version',
            label: '流程版本',
            children: definition.workflow_version
              ? `v${definition.workflow_version}`
              : '发布用例时固定最新已发布版本',
          },
          {
            key: 'environment',
            label: '运行环境',
            children: environment?.name ?? definition.environment_id,
          },
        ]}
      />
      <Typography.Paragraph type="secondary" className="asset-binding-note">
        打开流程用于查看或编辑当前流程；历史执行证据请从“执行与报告”进入冻结回看。
      </Typography.Paragraph>
      <Typography.Title level={5}>运行变量</Typography.Title>
      <OverrideValues values={definition.runtime_variables} />
      <Typography.Title level={5}>运行请求头</Typography.Title>
      <OverrideValues values={definition.runtime_headers} />
    </>
  )
}

function OverrideValues({ values }: { values: Record<string, string> }) {
  return (
    <Table
      size="small"
      rowKey="name"
      pagination={false}
      dataSource={Object.entries(values).map(([name, value]) => ({ name, value }))}
      locale={{ emptyText: '未设置覆盖项' }}
      columns={[
        { title: '名称', dataIndex: 'name' },
        {
          title: '值',
          dataIndex: 'value',
          render: (value: string) => <Typography.Text code>{value}</Typography.Text>,
        },
      ]}
    />
  )
}

function SuiteMembers(props: AssetDetailProps & { items: TestSuiteItem[]; draft: boolean }) {
  return (
    <>
      <Typography.Paragraph type="secondary">
        {props.draft ? '当前套件草稿；发布时固定成员版本。' : '这些用例版本已随套件发布冻结。'}
      </Typography.Paragraph>
      <Table
        rowKey="test_case_id"
        size="small"
        pagination={false}
        dataSource={props.items}
        columns={[
          {
            title: '用例',
            render: (_, item) => (
              <Link
                to={`${projectPath(props.projectId, 'assets')}?type=case&focus=${item.test_case_id}&version=${item.test_case_version ?? 'draft'}`}
              >
                {props.cases.find((asset) => asset.id === item.test_case_id)?.name ??
                  item.test_case_id}
              </Link>
            ),
          },
          {
            title: '固定版本',
            render: (_, item) =>
              item.test_case_version ? `v${item.test_case_version}` : '发布套件时固定',
          },
        ]}
      />
    </>
  )
}

function RelatedPlans(props: Pick<AssetDetailProps, 'projectId' | 'kind' | 'id'>) {
  const plans = useQuery({
    queryKey: ['asset-plans', props.projectId],
    queryFn: () => listAssetPlans(props.projectId),
  })
  const related =
    plans.data?.items.filter((plan) =>
      plan.items.some((item) => item.target_type === props.kind && item.target_id === props.id),
    ) ?? []
  return (
    <>
      {plans.error && <AssetQueryError error={plans.error} onRetry={() => void plans.refetch()} />}
      <Table
        rowKey="id"
        size="small"
        pagination={false}
        loading={plans.isPending}
        dataSource={related}
        locale={{ emptyText: '暂无直接引用该资产的测试计划' }}
        columns={[
          {
            title: '测试计划',
            render: (_, plan) => (
              <Link to={`${projectPath(props.projectId, 'tasks')}?focus=${plan.id}`}>
                {plan.name}
              </Link>
            ),
          },
          {
            title: '固定版本',
            render: (_, plan) =>
              plan.items
                .filter((item) => item.target_type === props.kind && item.target_id === props.id)
                .map((item) => `v${item.target_version}`)
                .join(' / '),
          },
        ]}
      />
    </>
  )
}

function AssetQueryError({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  return (
    <Alert
      type="error"
      showIcon
      title="资产信息读取失败"
      description={apiErrorMessage(error)}
      action={
        <Button size="small" onClick={onRetry}>
          重试
        </Button>
      }
    />
  )
}
