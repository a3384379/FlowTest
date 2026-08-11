import {
  ApiOutlined,
  CloudServerOutlined,
  LockOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Empty,
  Row,
  Segmented,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
} from 'antd'
import { useMemo, useState } from 'react'

import {
  getV3FeatureFlags,
  listCapabilities,
  listPlugins,
  listRunnerPools,
  type Capability,
  type Plugin,
  type RunnerPool,
} from '../features/capabilities/capability-service'
import { useAuthStore } from '../features/auth/auth-store'

type ViewMode = '能力' | '插件' | 'Runner'

export default function PlatformCapabilitiesPage() {
  const isSystemAdmin = useSystemAdminStatus()
  const [mode, setMode] = useState<ViewMode>('能力')
  const [selectedKey, setSelectedKey] = useState<string | null>(null)
  const inventory = usePlatformInventory(isSystemAdmin)
  const selected = useSelectedCapability(inventory.capabilities, selectedKey)

  return (
    <div className="v3-platform-page">
      <PlatformPageHeading />
      <FeatureBoundaryAlert flags={inventory.flags} />
      <CapabilityStatistics
        capabilities={inventory.capabilities}
        pluginCount={inventory.pluginCount}
        runnerCount={inventory.runnerCount}
      />
      <PlatformWorkspace
        mode={mode}
        onModeChange={setMode}
        isSystemAdmin={isSystemAdmin}
        capabilities={inventory.capabilities}
        capabilitiesLoading={inventory.capabilitiesLoading}
        plugins={inventory.plugins}
        pluginsLoading={inventory.pluginsLoading}
        runnerPools={inventory.runnerPools}
        runnerPoolsLoading={inventory.runnerPoolsLoading}
        selected={selected}
        onSelect={(item) => setSelectedKey(capabilityKey(item))}
      />
    </div>
  )
}

function useSystemAdminStatus(): boolean {
  return useAuthStore((state) => Boolean(state.user?.is_system_admin))
}

function usePlatformInventory(isSystemAdmin: boolean) {
  const flags = useQuery({ queryKey: ['v3-feature-flags'], queryFn: getV3FeatureFlags })
  const capabilities = useQuery({ queryKey: ['capabilities'], queryFn: listCapabilities })
  const plugins = useQuery({
    queryKey: ['plugins'],
    queryFn: listPlugins,
    enabled: isSystemAdmin,
  })
  const runnerPools = useQuery({
    queryKey: ['runner-pools'],
    queryFn: listRunnerPools,
    enabled: isSystemAdmin,
  })
  const capabilityItems = pageItems(capabilities.data)
  const pluginItems = pageItems(plugins.data)
  const poolItems = pageItems(runnerPools.data)
  return {
    flags: flags.data,
    capabilities: capabilityItems,
    capabilitiesLoading: capabilities.isLoading,
    plugins: pluginItems,
    pluginCount: pluginItems.length,
    pluginsLoading: plugins.isLoading,
    runnerPools: poolItems,
    runnerCount: poolItems.flatMap((pool) => pool.runners).length,
    runnerPoolsLoading: runnerPools.isLoading,
  }
}

function pageItems<T>(page: { items: T[] } | undefined): T[] {
  return page ? page.items : []
}

function PlatformPageHeading() {
  return (
    <div className="page-heading">
      <div>
        <Space align="center">
          <Typography.Title level={2}>能力与插件中心</Typography.Title>
          <Tag color="purple">V3 · S22</Tag>
        </Space>
        <Typography.Text type="secondary">
          以版本化 Capability 扩展执行能力，同时固定 Snapshot、Schema 哈希和 Runner 安全边界。
        </Typography.Text>
      </div>
      <Button disabled title="签名验证与隔离安装将在后续迭代开放">
        安装签名插件
      </Button>
    </div>
  )
}

function PlatformWorkspace({
  mode,
  onModeChange,
  selected,
  onSelect,
  ...inventory
}: {
  mode: ViewMode
  onModeChange: (mode: ViewMode) => void
  selected: Capability | null
  onSelect: (item: Capability) => void
  isSystemAdmin: boolean
  capabilities: Capability[]
  capabilitiesLoading: boolean
  plugins: Plugin[]
  pluginsLoading: boolean
  runnerPools: RunnerPool[]
  runnerPoolsLoading: boolean
}) {
  return (
    <Card className="v3-platform-workspace">
      <Segmented<ViewMode>
        value={mode}
        options={['能力', '插件', 'Runner']}
        onChange={onModeChange}
      />
      <div className="v3-platform-content">
        <div className="v3-platform-table">
          <InventoryTable mode={mode} selected={selected} onSelect={onSelect} {...inventory} />
        </div>
        <CapabilityInspector capability={selected} />
      </div>
    </Card>
  )
}

function InventoryTable({
  mode,
  isSystemAdmin,
  capabilities,
  capabilitiesLoading,
  plugins,
  pluginsLoading,
  runnerPools,
  runnerPoolsLoading,
  selected,
  onSelect,
}: {
  mode: ViewMode
  isSystemAdmin: boolean
  capabilities: Capability[]
  capabilitiesLoading: boolean
  plugins: Plugin[]
  pluginsLoading: boolean
  runnerPools: RunnerPool[]
  runnerPoolsLoading: boolean
  selected: Capability | null
  onSelect: (item: Capability) => void
}) {
  if (mode === '能力') {
    return (
      <CapabilityTable
        loading={capabilitiesLoading}
        items={capabilities}
        selected={selected}
        onSelect={onSelect}
      />
    )
  }
  if (!isSystemAdmin) {
    const message = mode === '插件' ? '仅系统管理员可查看插件清单' : '仅系统管理员可查看执行面'
    return <Empty description={message} />
  }
  if (mode === '插件') return <PluginTable items={plugins} loading={pluginsLoading} />
  return <RunnerPoolTable items={runnerPools} loading={runnerPoolsLoading} />
}

function PluginTable({ items, loading }: { items: Plugin[]; loading: boolean }) {
  return (
    <Table
      rowKey="id"
      loading={loading}
      dataSource={items}
      locale={{ emptyText: '尚未安装管理员签名插件' }}
      columns={[
        { title: '插件', dataIndex: 'display_name' },
        { title: '标识', dataIndex: 'plugin_key' },
        { title: '版本', dataIndex: 'version' },
        { title: 'OCI Digest', dataIndex: 'oci_digest', ellipsis: true },
        { title: '状态', dataIndex: 'status' },
      ]}
    />
  )
}

function RunnerPoolTable({ items, loading }: { items: RunnerPool[]; loading: boolean }) {
  return (
    <Table
      rowKey="id"
      loading={loading}
      dataSource={items}
      locale={{ emptyText: 'Runner Fabric 尚未启用' }}
      columns={[
        { title: '池名称', dataIndex: 'name' },
        { title: 'Runner 类型', dataIndex: 'runner_type' },
        { title: '网络区', dataIndex: 'network_zone' },
        { title: '并发', dataIndex: 'max_concurrency' },
        { title: 'Runner', render: (_, pool) => `${pool.runners.length} 个` },
      ]}
    />
  )
}

function FeatureBoundaryAlert({
  flags,
}: {
  flags?: Awaited<ReturnType<typeof getV3FeatureFlags>>
}) {
  if (flags?.capability_sdk) return null
  return (
    <Alert
      showIcon
      type="info"
      className="page-alert"
      title="Capability SDK 当前处于兼容预览模式"
      description="V2 Workflow 继续按原行为运行；只有启用 Feature Flag 后才能发布显式 Capability 节点。"
    />
  )
}

function CapabilityStatistics({
  capabilities,
  pluginCount,
  runnerCount,
}: {
  capabilities: Capability[]
  pluginCount: number
  runnerCount: number
}) {
  const enabled = capabilities.filter((item) => item.enabled).length
  const runnerTypes = new Set(capabilities.map((item) => item.runner_type)).size
  return (
    <Row gutter={16} className="v3-capability-statistics">
      <Col span={6}>
        <Card>
          <Statistic title="内置能力" value={capabilities.length} prefix={<ApiOutlined />} />
        </Card>
      </Col>
      <Col span={6}>
        <Card>
          <Statistic title="已启用" value={enabled} prefix={<SafetyCertificateOutlined />} />
        </Card>
      </Col>
      <Col span={6}>
        <Card>
          <Statistic title="签名插件" value={pluginCount} prefix={<LockOutlined />} />
        </Card>
      </Col>
      <Col span={6}>
        <Card>
          <Statistic
            title="Runner 类型 / 在线"
            value={`${runnerTypes} / ${runnerCount}`}
            prefix={<CloudServerOutlined />}
          />
        </Card>
      </Col>
    </Row>
  )
}

function CapabilityTable({
  items,
  loading,
  selected,
  onSelect,
}: {
  items: Capability[]
  loading: boolean
  selected: Capability | null
  onSelect: (item: Capability) => void
}) {
  return (
    <Table
      rowKey={capabilityKey}
      loading={loading}
      dataSource={items}
      pagination={{ pageSize: 12, hideOnSinglePage: true }}
      rowClassName={(item) =>
        capabilityKey(item) === capabilityKey(selected) ? 'selected-row' : ''
      }
      onRow={(item) => ({ onClick: () => onSelect(item) })}
      columns={[
        {
          title: '能力',
          render: (_, item) => (
            <Space orientation="vertical" size={0}>
              <Typography.Text strong>{item.id}</Typography.Text>
              <Typography.Text type="secondary">{item.display_name}</Typography.Text>
            </Space>
          ),
        },
        {
          title: '类型',
          dataIndex: 'source',
          render: (value) => (value === 'builtin' ? '内置' : '插件'),
        },
        { title: '版本', dataIndex: 'version' },
        { title: 'Runner', dataIndex: 'runner_type' },
        { title: '网络策略', dataIndex: 'network_access', render: networkLabel },
        {
          title: '状态',
          dataIndex: 'enabled',
          render: (value) => (
            <Tag color={value ? 'success' : 'default'}>{value ? '启用' : '预览'}</Tag>
          ),
        },
      ]}
    />
  )
}

function CapabilityInspector({ capability }: { capability: Capability | null }) {
  if (!capability)
    return (
      <aside className="v3-context-inspector">
        <Empty description="选择能力查看契约" />
      </aside>
    )
  const manifest = capability.manifest
  return (
    <aside className="v3-context-inspector">
      <Typography.Title level={4}>Context Inspector</Typography.Title>
      <Typography.Text code>
        {capability.id}@{capability.version}
      </Typography.Text>
      <Descriptions column={1} size="small" className="v3-capability-details">
        <Descriptions.Item label="Schema 哈希">
          {capability.schema_hash.slice(0, 16)}…
        </Descriptions.Item>
        <Descriptions.Item label="Runner">{capability.runner_type}</Descriptions.Item>
        <Descriptions.Item label="网络">
          {networkLabel(capability.network_access)}
        </Descriptions.Item>
        <Descriptions.Item label="默认超时">
          {manifest.timeout_policy.default_seconds} 秒
        </Descriptions.Item>
        <Descriptions.Item label="Credential">
          {manifest.credential_types.join('、') || '无'}
        </Descriptions.Item>
        <Descriptions.Item label="Snapshot">
          {manifest.snapshot_policy.include_schema_hash ? '固定 Schema 哈希' : '不固定'}
        </Descriptions.Item>
      </Descriptions>
      <Alert
        showIcon
        type="success"
        title="安全边界"
        description="Credential 仅保存加密材料；插件不会获得 Secret 明文，历史 Snapshot 始终固定版本与 Digest。"
      />
    </aside>
  )
}

function useSelectedCapability(items: Capability[], selectedKey: string | null) {
  return useMemo(
    () => items.find((item) => capabilityKey(item) === selectedKey) ?? items[0] ?? null,
    [items, selectedKey],
  )
}

function capabilityKey(item: Capability | null): string {
  return item ? `${item.id}@${item.version}` : ''
}

function networkLabel(value: string): string {
  return (
    {
      denied: '禁止网络',
      project_allowlist: '项目白名单',
      broker_only: '仅 Broker',
    }[value] ?? value
  )
}
