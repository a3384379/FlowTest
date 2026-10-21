import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  Button,
  Card,
  Empty,
  Input,
  Pagination,
  Segmented,
  Space,
  Table,
  Typography,
} from 'antd'
import { useSearchParams } from 'react-router-dom'

import QueryFailureNotice from '../components/QueryFailureNotice'
import { useAuthStore } from '../features/auth/auth-store'
import {
  getPlatformObject,
  getV3FeatureFlags,
  listCapabilities,
  listPlugins,
  listRunnerPools,
  type Capability,
  type PlatformSelection,
  type Plugin,
  type RunnerPool,
} from '../features/capabilities/capability-service'
import PlatformInspector from '../features/capabilities/PlatformInspector'

type ViewMode = PlatformSelection['kind']
const modes: { label: string; value: ViewMode }[] = [
  { label: '能力', value: 'capability' },
  { label: '插件', value: 'plugin' },
  { label: 'Runner', value: 'runnerPool' },
]

export default function PlatformCapabilitiesPage() {
  const scope = useAuthStore(
    (state) => `${state.user?.id}:${state.organizationId}:${state.user?.is_system_admin}`,
  )
  return <PlatformWorkspace key={scope} scope={scope} />
}

function PlatformWorkspace({ scope }: { scope: string }) {
  const [params, setParams] = useSearchParams()
  const isAdmin = useAuthStore((state) => Boolean(state.user?.is_system_admin))
  const queryClient = useQueryClient()
  const mode = viewMode(params.get('mode'))
  const selection = readSelection(params, mode)
  const page = pageNumber(params.get('page'))
  const search = params.get('search') ?? ''
  const inventory = usePlatformInventory(scope, mode, page, search, isAdmin)
  const permitted = mode === 'capability' || isAdmin
  const detail = useQuery({
    queryKey: ['platform', scope, 'detail', selection],
    queryFn: () => getPlatformObject(selection!),
    enabled: permitted && selection !== null,
  })
  const updatePage = (next: number) => {
    const nextParams = new URLSearchParams(params)
    nextParams.set('page', String(next))
    setParams(nextParams)
  }
  const select = (value: PlatformSelection) => {
    const next = new URLSearchParams(params)
    next.set('id', value.id)
    if (value.kind === 'capability') next.set('version', value.version)
    setParams(next)
  }
  const onSearch = (value: string) => {
    const next = new URLSearchParams(params)
    next.set('search', value)
    next.delete('page')
    setParams(next)
  }
  return (
    <div className="v3-platform-page">
      <div className="page-heading">
        <div>
          <Typography.Title level={2}>能力与插件中心</Typography.Title>
          <Typography.Text type="secondary">
            按版本核对能力、插件和 Runner 库存及已有安全策略。
          </Typography.Text>
        </div>
        <Space>
          <Button
            onClick={() => void queryClient.invalidateQueries({ queryKey: ['platform', scope] })}
          >
            刷新库存
          </Button>
          <Button disabled title="签名验证与隔离安装尚未开放">
            安装签名插件
          </Button>
        </Space>
      </div>
      <QueryFailureNotice queries={inventory.queries} />
      <InventoryStaleNotice query={inventory.active} />
      <FeatureNotice mode={mode} flags={inventory.flags.data} />
      <InventorySummary page={permitted ? inventory.active.data : undefined} />
      <Card className="v3-platform-workspace">
        <Segmented<ViewMode>
          value={mode}
          options={modes}
          onChange={(value) => setParams({ mode: value })}
        />
        <Input.Search
          key={`${mode}:${search}`}
          aria-label="搜索平台库存"
          defaultValue={search}
          maxLength={200}
          placeholder="搜索标识、名称或版本"
          allowClear
          onSearch={onSearch}
        />
        <div className="v3-platform-content">
          <div className="v3-platform-table">
            <InventoryTable
              mode={mode}
              permitted={permitted}
              inventory={inventory}
              onSelect={select}
            />
            {permitted && (
              <Pagination
                current={page}
                total={inventoryTotal(inventory.active.data)}
                pageSize={20}
                showSizeChanger={false}
                onChange={updatePage}
              />
            )}
          </div>
          <aside
            className="v3-context-inspector"
            aria-label="平台对象检查器"
            style={{ overflowX: 'auto' }}
          >
            {!permitted ? (
              <Empty description="当前角色不能读取此类库存详情" />
            ) : (
              <SelectedInspector
                selection={selection}
                detail={detail}
                runnerEnabled={inventory.flags.data?.runner_fabric === true}
              />
            )}
          </aside>
        </div>
      </Card>
    </div>
  )
}

function usePlatformInventory(
  scope: string,
  mode: ViewMode,
  page: number,
  search: string,
  admin: boolean,
) {
  const flags = useQuery({ queryKey: ['v3-feature-flags'], queryFn: getV3FeatureFlags })
  const capabilities = useQuery({
    queryKey: ['platform', scope, 'capabilities', page, search],
    queryFn: () => listCapabilities(page, search),
    enabled: mode === 'capability',
  })
  const plugins = useQuery({
    queryKey: ['platform', scope, 'plugins', page, search],
    queryFn: () => listPlugins(page, search),
    enabled: admin && mode === 'plugin',
  })
  const pools = useQuery({
    queryKey: ['platform', scope, 'pools', page, search],
    queryFn: () => listRunnerPools(page, search),
    enabled: admin && mode === 'runnerPool',
  })
  const active = mode === 'capability' ? capabilities : mode === 'plugin' ? plugins : pools
  return {
    flags,
    capabilities,
    plugins,
    pools,
    active,
    queries: mode === 'capability' || admin ? [flags, active] : [flags],
  }
}

function InventoryTable({
  mode,
  permitted,
  inventory,
  onSelect,
}: {
  mode: ViewMode
  permitted: boolean
  inventory: ReturnType<typeof usePlatformInventory>
  onSelect: (value: PlatformSelection) => void
}) {
  if (!permitted)
    return (
      <Empty
        description={mode === 'plugin' ? '仅系统管理员可查看插件清单' : '仅系统管理员可查看执行面'}
      />
    )
  if (mode === 'capability')
    return <CapabilityInventory query={inventory.capabilities} onSelect={onSelect} />
  if (mode === 'plugin') return <PluginInventory query={inventory.plugins} onSelect={onSelect} />
  return <PoolInventory query={inventory.pools} onSelect={onSelect} />
}

function CapabilityInventory({
  query,
  onSelect,
}: {
  query: ReturnType<typeof usePlatformInventory>['capabilities']
  onSelect: (value: PlatformSelection) => void
}) {
  return (
    <Table<Capability>
      rowKey={(item) => `${item.id}@${item.version}`}
      loading={query.isPending}
      dataSource={query.data?.items ?? []}
      pagination={false}
      locale={{
        emptyText: query.isError ? '能力目录读取失败，请重试' : '没有匹配的能力',
      }}
      columns={[
        {
          title: '能力',
          render: (_, item) => (
            <Button
              type="link"
              onClick={() => onSelect({ kind: 'capability', id: item.id, version: item.version })}
            >
              {item.display_name}
            </Button>
          ),
        },
        { title: '标识', dataIndex: 'id' },
        { title: '版本', dataIndex: 'version' },
        { title: 'Runner', dataIndex: 'runner_type' },
        { title: '状态', render: (_, item) => (item.enabled ? '启用' : '预览') },
      ]}
    />
  )
}

function PluginInventory({
  query,
  onSelect,
}: {
  query: ReturnType<typeof usePlatformInventory>['plugins']
  onSelect: (value: PlatformSelection) => void
}) {
  return (
    <Table<Plugin>
      rowKey="id"
      loading={query.isPending}
      dataSource={query.data?.items ?? []}
      pagination={false}
      locale={{
        emptyText: query.isError
          ? '插件目录读取失败，请重试'
          : '尚未安装管理员签名插件或没有匹配结果',
      }}
      columns={[
        {
          title: '插件',
          render: (_, item) => (
            <Button type="link" onClick={() => onSelect({ kind: 'plugin', id: item.id })}>
              {item.display_name}
            </Button>
          ),
        },
        { title: '标识', dataIndex: 'plugin_key' },
        { title: '版本', dataIndex: 'version' },
        { title: 'OCI Digest', dataIndex: 'oci_digest', ellipsis: true },
        { title: '状态', dataIndex: 'status' },
      ]}
    />
  )
}

function PoolInventory({
  query,
  onSelect,
}: {
  query: ReturnType<typeof usePlatformInventory>['pools']
  onSelect: (value: PlatformSelection) => void
}) {
  return (
    <Table<RunnerPool>
      rowKey="id"
      loading={query.isPending}
      dataSource={query.data?.items ?? []}
      pagination={false}
      locale={{
        emptyText: query.isError ? 'Runner 目录读取失败，请重试' : '没有匹配的 Runner Pool',
      }}
      columns={[
        {
          title: '池名称',
          render: (_, item) => (
            <Button type="link" onClick={() => onSelect({ kind: 'runnerPool', id: item.id })}>
              {item.name}
            </Button>
          ),
        },
        { title: '类型', dataIndex: 'runner_type' },
        { title: '网络区', dataIndex: 'network_zone' },
        { title: '并发上限', dataIndex: 'max_concurrency' },
        { title: 'Runner', render: (_, item) => `${item.runners.length} 个` },
      ]}
    />
  )
}

function SelectedInspector({
  selection,
  detail,
  runnerEnabled,
}: {
  selection: PlatformSelection | null
  detail: ReturnType<typeof useQuery<Awaited<ReturnType<typeof getPlatformObject>>>>
  runnerEnabled: boolean
}) {
  if (!selection) return <Empty description="选择当前库存对象查看详情" />
  return (
    <>
      <QueryFailureNotice queries={[detail]} />
      {detail.isError && detail.data && (
        <Alert type="warning" title="详情刷新失败，以下为上次成功读取的数据" />
      )}
      {detail.isPending && <Typography.Text>正在读取所选对象</Typography.Text>}
      {detail.data && (
        <PlatformInspector
          key={`${selection.kind}:${selection.id}:${selection.kind === 'capability' ? selection.version : ''}`}
          value={detail.data}
          runnerEnabled={runnerEnabled}
        />
      )}
    </>
  )
}

function FeatureNotice({
  mode,
  flags,
}: {
  mode: ViewMode
  flags: Awaited<ReturnType<typeof getV3FeatureFlags>> | undefined
}) {
  if (!flags) return <Alert type="info" title="功能状态尚未读取，库存不代表当前可执行能力" />
  if (mode === 'capability' && !flags.capability_sdk)
    return (
      <Alert
        showIcon
        type="info"
        title="Capability SDK 当前处于兼容预览模式"
        description="原工作流继续按既有行为运行；能力启用状态以目录实际返回字段为准。"
      />
    )
  if (mode === 'plugin' && !flags.plugin_registry)
    return <Alert type="info" title="插件注册未启用，当前仅展示已有只读库存" />
  if (mode === 'runnerPool' && !flags.runner_fabric)
    return <Alert type="info" title="Runner Fabric 未启用，当前仅展示已有只读库存" />
  return null
}

function viewMode(value: string | null): ViewMode {
  return value === 'plugin' || value === 'runnerPool' ? value : 'capability'
}
function pageNumber(value: string | null): number {
  const page = Number(value)
  return Number.isSafeInteger(page) && page > 0 ? page : 1
}
function readSelection(params: URLSearchParams, mode: ViewMode): PlatformSelection | null {
  const id = params.get('id')
  if (!id) return null
  if (mode !== 'capability') return { kind: mode, id }
  const version = params.get('version')
  return version ? { kind: mode, id, version } : null
}

function InventorySummary({ page }: { page: { total: number; items: unknown[] } | undefined }) {
  return (
    <Typography.Paragraph type="secondary">
      当前目录共 {page?.total ?? '未提供'} 项，已载入 {page?.items.length ?? '未提供'}{' '}
      项。搜索覆盖当前模式全部库存；选中详情独立于目录页。
    </Typography.Paragraph>
  )
}
function inventoryTotal(page: { total: number } | undefined): number {
  return page?.total ?? 0
}

function InventoryStaleNotice({ query }: { query: { isError: boolean; data: unknown } }) {
  if (!query.isError || query.data === undefined) return null
  return <Alert type="warning" title="目录刷新失败，当前列表为上次成功读取的数据" />
}
