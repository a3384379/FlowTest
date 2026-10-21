import { Alert, Descriptions, Space, Table, Tabs, Typography } from 'antd'

import ResponseCodeReader from '../api-console/ResponseCodeReader'
import type {
  Capability,
  CapabilityManifest,
  PlatformObject,
  Plugin,
  RunnerPool,
} from './capability-service'

export default function PlatformInspector({
  value,
  runnerEnabled,
}: {
  value: PlatformObject
  runnerEnabled: boolean
}) {
  if (value.kind === 'capability') return <CapabilityInspector capability={value.record} />
  if (value.kind === 'plugin') return <PluginInspector plugin={value.record} />
  return <PoolInspector pool={value.record} runnerEnabled={runnerEnabled} />
}

function CapabilityInspector({ capability }: { capability: Capability }) {
  const manifest = capability.manifest
  return (
    <>
      <Typography.Title level={4}>能力契约检查器</Typography.Title>
      <Typography.Text code>
        {capability.id}@{capability.version}
      </Typography.Text>
      <Tabs
        items={[
          {
            key: 'summary',
            label: '摘要',
            children: <CapabilitySummary capability={capability} />,
          },
          {
            key: 'input',
            label: '输入 Schema',
            children: <SchemaContract title="输入 Schema" value={manifest?.input_schema} />,
          },
          {
            key: 'output',
            label: '输出 Schema',
            children: <SchemaContract title="输出 Schema" value={manifest?.output_schema} />,
          },
          {
            key: 'configuration',
            label: '配置 Schema',
            children: <SchemaContract title="配置 Schema" value={manifest?.configuration_schema} />,
          },
          {
            key: 'policies',
            label: '策略与来源',
            children: <CapabilityPolicies manifest={manifest} capability={capability} />,
          },
        ]}
      />
    </>
  )
}

function CapabilitySummary({ capability }: { capability: Capability }) {
  const manifest = capability.manifest
  return (
    <Descriptions
      column={1}
      size="small"
      items={[
        { label: '名称', children: text(capability.display_name) },
        { label: '说明', children: text(capability.description) },
        { label: 'Schema 哈希（完整）', children: <CopyValue value={capability.schema_hash} /> },
        { label: 'Runner', children: text(capability.runner_type) },
        { label: '网络', children: networkLabel(capability.network_access) },
        { label: '默认超时', children: seconds(manifest?.timeout_policy?.default_seconds) },
        { label: '最大超时', children: seconds(manifest?.timeout_policy?.maximum_seconds) },
        { label: '凭据类型', children: list(manifest?.credential_types) },
        {
          label: 'Snapshot Schema 哈希',
          children: bool(manifest?.snapshot_policy?.include_schema_hash),
        },
        { label: '来源', children: text(capability.source) },
        { label: '插件标识', children: text(capability.plugin_id) },
        { label: '插件 Digest', children: <CopyValue value={capability.plugin_digest} /> },
      ]}
    />
  )
}

function CapabilityPolicies({
  manifest,
  capability,
}: {
  manifest: CapabilityManifest | undefined
  capability: Capability
}) {
  return (
    <Space orientation="vertical" className="full-width">
      <NetworkPolicyDetails value={manifest?.network_policy} />
      <SnapshotPolicyDetails value={manifest?.snapshot_policy} />
      <Descriptions
        column={1}
        size="small"
        items={[
          { label: 'Manifest 插件标识', children: text(manifest?.plugin_id) },
          {
            label: 'Manifest 插件 Digest',
            children: <CopyValue value={manifest?.plugin_digest} />,
          },
        ]}
      />
      {capability.plugin_id && (
        <Typography.Link
          href={`/platform?mode=plugin&search=${encodeURIComponent(capability.plugin_id)}`}
        >
          查找来源插件
        </Typography.Link>
      )}
      <Alert type="info" title="以下为能力声明的策略；实际诊断采集按安装与请求级项目策略执行" />
      <ResponseCodeReader title="完整策略与来源" value={policySource(capability)} />
    </Space>
  )
}

function NetworkPolicyDetails({
  value,
}: {
  value: CapabilityManifest['network_policy'] | undefined
}) {
  return (
    <Descriptions
      column={1}
      size="small"
      items={[
        { label: '网络访问', children: networkLabel(value?.access) },
        { label: '允许协议', children: list(value?.protocols) },
        { label: 'DNS 重新校验', children: bool(value?.dns_revalidation) },
      ]}
    />
  )
}
function SnapshotPolicyDetails({
  value,
}: {
  value: CapabilityManifest['snapshot_policy'] | undefined
}) {
  return (
    <Descriptions
      column={1}
      size="small"
      items={[
        { label: 'Snapshot 包含配置', children: bool(value?.include_configuration) },
        { label: 'Snapshot 固定 Schema 哈希', children: bool(value?.include_schema_hash) },
        { label: 'Snapshot 固定插件 Digest', children: bool(value?.pin_plugin_digest) },
        { label: 'Snapshot 凭据材料策略', children: text(value?.credential_material) },
      ]}
    />
  )
}
function policySource(capability: Capability) {
  const manifest = capability.manifest
  return {
    network_policy: manifest?.network_policy,
    timeout_policy: manifest?.timeout_policy,
    snapshot_policy: manifest?.snapshot_policy,
    redaction_policy: manifest?.redaction_policy,
    credential_types: manifest?.credential_types,
    plugin_id: manifest?.plugin_id,
    plugin_digest: manifest?.plugin_digest,
    source: capability.source,
    schema_hash: capability.schema_hash,
  }
}

function SchemaContract({ title, value }: { title: string; value: unknown }) {
  const properties = schemaProperties(value)
  return (
    <Space orientation="vertical" className="full-width">
      <Typography.Text type="secondary">
        字段结构最多预览所选版本的前 200 个顶层字段；下方可搜索、复制完整原始契约。
      </Typography.Text>
      <Table
        rowKey="name"
        size="small"
        dataSource={properties}
        pagination={false}
        locale={{
          emptyText:
            value === undefined ? 'Schema 未提供' : '未声明顶层 properties，请查看完整 Schema',
        }}
        columns={[
          { title: '字段', dataIndex: 'name' },
          { title: '类型', dataIndex: 'type' },
          {
            title: '必需',
            dataIndex: 'required',
            render: (value: boolean) => (value ? '是' : '否'),
          },
          { title: '说明', dataIndex: 'description' },
        ]}
      />
      <ResponseCodeReader title={title} value={value} />
    </Space>
  )
}

function schemaProperties(
  value: unknown,
): { name: string; type: string; required: boolean; description: string }[] {
  if (!isRecord(value) || !isRecord(value.properties)) return []
  const required = Array.isArray(value.required) ? value.required : []
  return Object.entries(value.properties)
    .slice(0, 200)
    .map(([name, property]) => ({
      name,
      required: required.includes(name),
      type: schemaType(property),
      description: isRecord(property) ? text(property.description) : '未提供',
    }))
}

function schemaType(value: unknown): string {
  if (typeof value === 'boolean') return value ? '允许任意值' : '禁止值'
  if (!isRecord(value)) return '未提供'
  if (value.type !== undefined) return text(value.type)
  return value.$ref ? `引用 ${text(value.$ref)}` : '组合或未声明类型'
}

function PluginInspector({ plugin }: { plugin: Plugin }) {
  return (
    <>
      <Typography.Title level={4}>插件详情</Typography.Title>
      <Descriptions
        column={1}
        items={[
          { label: '名称', children: plugin.display_name },
          { label: '标识', children: plugin.plugin_key },
          { label: '版本', children: plugin.version },
          { label: 'OCI 仓库', children: <CopyValue value={plugin.oci_repository} /> },
          { label: '完整 Digest', children: <CopyValue value={plugin.oci_digest} /> },
          { label: '签名身份（声明）', children: <CopyValue value={plugin.signature_identity} /> },
          { label: '状态', children: plugin.status },
          { label: '创建时间', children: text(plugin.created_at) },
          { label: '更新时间', children: text(plugin.updated_at) },
        ]}
      />
      <Alert type="info" title="插件安装尚未开放；库存身份和状态不代表已完成签名验证或可执行验收" />
    </>
  )
}

function PoolInspector({ pool, runnerEnabled }: { pool: RunnerPool; runnerEnabled: boolean }) {
  return (
    <>
      <Typography.Title level={4}>Runner Pool 详情</Typography.Title>
      <Descriptions
        column={1}
        items={[
          { label: '名称', children: pool.name },
          { label: 'Pool ID', children: <CopyValue value={pool.id} /> },
          { label: '类型', children: pool.runner_type },
          { label: '网络区', children: pool.network_zone },
          { label: '标签', children: list(pool.labels) },
          { label: '并发上限', children: pool.max_concurrency },
          { label: '状态', children: bool(pool.enabled) },
        ]}
      />
      {runnerEnabled ? (
        <Typography.Link href={`/execution-fabric?pool=${encodeURIComponent(pool.id)}`}>
          在执行面查看此 Pool
        </Typography.Link>
      ) : (
        <Alert type="info" title="执行面未启用，当前仅可检查已有库存" />
      )}
      <Table
        rowKey="id"
        size="small"
        dataSource={pool.runners}
        pagination={false}
        locale={{ emptyText: '此 Pool 尚无 Runner' }}
        columns={[
          { title: '成员', dataIndex: 'name' },
          { title: '状态', dataIndex: 'status' },
          { title: '当前负载', dataIndex: 'current_load' },
          { title: '标签', dataIndex: 'labels', render: list },
          { title: '能力', dataIndex: 'capabilities', render: list },
          { title: '心跳', dataIndex: 'last_seen_at', render: text },
        ]}
      />
    </>
  )
}

function CopyValue({ value }: { value: string | null | undefined }) {
  return value ? (
    <Typography.Text copyable={{ text: value }} style={{ overflowWrap: 'anywhere' }}>
      {value}
    </Typography.Text>
  ) : (
    <>未提供</>
  )
}
function seconds(value: number | undefined): string {
  return value === undefined ? '未提供' : `${value} 秒`
}
function bool(value: boolean | undefined): string {
  return value === undefined ? '未提供' : value ? '是' : '否'
}
function list(value: string[] | undefined): string {
  return value === undefined ? '未提供' : value.join('、') || '无'
}
function text(value: unknown): string {
  if (value === undefined || value === null || value === '') return '未提供'
  return typeof value === 'string' ? value : JSON.stringify(value)
}
function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}
function networkLabel(value: string | undefined): string {
  if (value === undefined) return '未提供'
  if (value === 'denied') return '禁止网络'
  if (value === 'project_allowlist') return '项目白名单'
  if (value === 'broker_only') return '仅 Broker'
  return `未知策略：${value}`
}
