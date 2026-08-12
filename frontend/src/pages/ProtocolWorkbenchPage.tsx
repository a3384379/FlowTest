import {
  ApiOutlined,
  CloudServerOutlined,
  ImportOutlined,
  PlayCircleOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
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
  Row,
  Segmented,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Typography,
  message,
} from 'antd'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { getV3FeatureFlags } from '../features/capabilities/capability-service'
import { listCredentials } from '../features/data-sources/data-source-service'
import { useProjectContext } from '../features/projects/use-project-context'
import EventProtocolWorkspace, {
  type EventProtocolMode,
} from '../features/protocols/EventProtocolWorkspace'
import {
  createGraphQLSchema,
  createGrpcDescriptor,
  executeGraphQL,
  executeGrpc,
  importGrpcReflection,
  listGraphQLSchemas,
  listGrpcDescriptors,
  type ProtocolDebugResult,
  type SchemaArtifact,
} from '../features/protocols/protocol-service'
import type { Credential } from '../lib/api'

const { TextArea } = Input

type SchemaProtocolMode = 'graphql' | 'grpc'
type ProtocolMode = SchemaProtocolMode | EventProtocolMode
type ImportMode =
  | 'graphql_sdl'
  | 'graphql_introspection'
  | 'proto_source'
  | 'proto_descriptor_set'
  | 'grpc_reflection'

const DEFAULT_SDL = `type Query {
  user(id: ID!): User!
}

type User {
  id: ID!
  name: String!
}`

const DEFAULT_PROTO = `syntax = "proto3";
package flowtest.user.v1;

service UserService {
  rpc GetUser(GetUserRequest) returns (GetUserReply);
}

message GetUserRequest { string id = 1; }
message GetUserReply { string id = 1; string name = 2; }`

export default function ProtocolWorkbenchPage() {
  const { projectId } = useProjectContext()

  if (!projectId) return <Empty description="请先选择项目" />
  return <ProjectProtocolWorkbench projectId={projectId} />
}

function ProjectProtocolWorkbench({ projectId }: { projectId: string }) {
  const [mode, setMode] = useState<ProtocolMode>('graphql')
  const [selection, setSelection] = useState<{ mode: SchemaProtocolMode; id: string } | null>(null)
  const [importOpen, setImportOpen] = useState(false)
  const schemaMode: SchemaProtocolMode = mode === 'grpc' ? 'grpc' : 'graphql'
  const inventory = useProtocolInventory(projectId, schemaMode)
  const credentials = useQuery({
    queryKey: ['credentials', projectId],
    queryFn: () => listCredentials(projectId),
  })
  const selected = useSelectedAsset(inventory.items, selectionId(selection, schemaMode))
  const eventMode = mode === 'kafka' || mode === 'websocket'

  return (
    <div className="protocol-page">
      <ProtocolHeading onImport={eventMode ? undefined : () => setImportOpen(true)} />
      {!eventMode && <ProtocolFeatureAlert enabled={inventory.enabled} />}
      <ProtocolSummary graphql={inventory.graphqlTotal} grpc={inventory.grpcTotal} />
      <Card className="protocol-workspace">
        <Segmented<ProtocolMode>
          value={mode}
          options={[
            { label: 'GraphQL', value: 'graphql' },
            { label: 'gRPC', value: 'grpc' },
            { label: 'Kafka', value: 'kafka' },
            { label: 'WebSocket', value: 'websocket' },
          ]}
          onChange={setMode}
        />
        {eventMode ? (
          <EventProtocolWorkspace
            projectId={projectId}
            mode={mode}
            enabled={inventory.eventProtocolsEnabled}
          />
        ) : (
          <div className="protocol-workspace-grid">
            <SchemaInventory
              mode={schemaMode}
              items={inventory.items}
              loading={inventory.loading}
              selectedId={assetId(selected)}
              onSelect={(item) => setSelection({ mode: schemaMode, id: item.id })}
            />
            <ProtocolEditor
              mode={schemaMode}
              projectId={projectId}
              selected={selected}
              enabled={inventory.enabled}
              credentials={credentials.data ?? []}
            />
            <SchemaInspector asset={selected} />
          </div>
        )}
      </Card>
      <SchemaImportDialog
        open={importOpen}
        mode={schemaMode}
        projectId={projectId}
        onClose={() => setImportOpen(false)}
        credentials={credentials.data ?? []}
      />
    </div>
  )
}

function useProtocolInventory(projectId: string, mode: SchemaProtocolMode) {
  const flags = useQuery({ queryKey: ['v3-feature-flags'], queryFn: getV3FeatureFlags })
  const graphql = useQuery({
    queryKey: ['graphql-schemas', projectId],
    queryFn: () => listGraphQLSchemas(projectId),
  })
  const grpc = useQuery({
    queryKey: ['grpc-descriptors', projectId],
    queryFn: () => listGrpcDescriptors(projectId),
  })
  return {
    enabled: flags.data?.multi_protocol === true,
    eventProtocolsEnabled: flags.data?.event_protocols === true,
    items: protocolItems(mode, pageItems(graphql.data), pageItems(grpc.data)),
    graphqlTotal: pageTotal(graphql.data),
    grpcTotal: pageTotal(grpc.data),
    loading: [graphql.isLoading, grpc.isLoading].some(Boolean),
  }
}

function ProtocolFeatureAlert({ enabled }: { enabled: boolean }) {
  if (enabled) return null
  return (
    <Alert
      showIcon
      type="info"
      className="page-alert"
      title="多协议能力当前关闭"
      description="Schema 可继续管理；启用 Feature Flag 后才能发起 GraphQL 与 gRPC 调试。"
    />
  )
}

function ProtocolHeading({ onImport }: { onImport?: () => void }) {
  return (
    <div className="page-heading">
      <div>
        <Space align="center">
          <Typography.Title level={2}>多协议接口工作台</Typography.Title>
          <Tag color="purple">V3 · S24</Tag>
        </Space>
        <Typography.Text type="secondary">
          统一管理 GraphQL、gRPC、Kafka 与 WebSocket，并将协议资产版本固定到执行 Snapshot。
        </Typography.Text>
      </div>
      <Space>
        <Link to="../apis">
          <Button icon={<ApiOutlined />}>REST 工作台</Button>
        </Link>
        {onImport && (
          <Button type="primary" icon={<ImportOutlined />} onClick={onImport}>
            导入协议 Schema
          </Button>
        )}
      </Space>
    </div>
  )
}

function ProtocolSummary({ graphql, grpc }: { graphql: number; grpc: number }) {
  return (
    <Row gutter={16} className="protocol-summary">
      <Col span={8}>
        <Card>
          <Typography.Text type="secondary">GraphQL Schema</Typography.Text>
          <Typography.Title level={3}>{graphql}</Typography.Title>
        </Card>
      </Col>
      <Col span={8}>
        <Card>
          <Typography.Text type="secondary">gRPC Descriptor</Typography.Text>
          <Typography.Title level={3}>{grpc}</Typography.Title>
        </Card>
      </Col>
      <Col span={8}>
        <Card>
          <Typography.Text type="secondary">协议安全边界</Typography.Text>
          <Typography.Title level={3}>4 MB / 300 秒</Typography.Title>
        </Card>
      </Col>
    </Row>
  )
}

function SchemaInventory({
  mode,
  items,
  loading,
  selectedId,
  onSelect,
}: {
  mode: SchemaProtocolMode
  items: SchemaArtifact[]
  loading: boolean
  selectedId: string | null
  onSelect: (item: SchemaArtifact) => void
}) {
  return (
    <div className="protocol-inventory">
      <Typography.Title level={4}>
        {mode === 'graphql' ? 'Schema 版本' : 'Descriptor 版本'}
      </Typography.Title>
      <Table
        size="small"
        rowKey="id"
        loading={loading}
        dataSource={items}
        pagination={{ pageSize: 8, hideOnSinglePage: true }}
        rowClassName={(item) => (item.id === selectedId ? 'selected-row' : '')}
        onRow={(item) => ({ onClick: () => onSelect(item) })}
        columns={[
          {
            title: '名称',
            render: (_, item) => (
              <Space orientation="vertical" size={0}>
                <Typography.Text strong>{item.name}</Typography.Text>
                <Typography.Text type="secondary">v{item.version}</Typography.Text>
              </Space>
            ),
          },
          { title: '来源', dataIndex: 'source_format', render: sourceFormatLabel },
        ]}
      />
    </div>
  )
}

function ProtocolEditor({
  mode,
  projectId,
  selected,
  enabled,
  credentials,
}: {
  mode: SchemaProtocolMode
  projectId: string
  selected: SchemaArtifact | null
  enabled: boolean
  credentials: Credential[]
}) {
  if (!selected)
    return (
      <div className="protocol-editor">
        <Empty description="选择 Schema 版本开始调试" />
      </div>
    )
  return mode === 'graphql' ? (
    <GraphQLEditor projectId={projectId} selected={selected} enabled={enabled} />
  ) : (
    <GrpcEditor
      projectId={projectId}
      selected={selected}
      enabled={enabled}
      credentials={credentials}
    />
  )
}

function GraphQLEditor({ projectId, selected, enabled }: EditorProps) {
  const [endpoint, setEndpoint] = useState('https://api.example.com/graphql')
  const [operation, setOperation] = useState('query User($id: ID!) { user(id: $id) { id name } }')
  const [variables, setVariables] = useState('{"id":"42"}')
  const [result, setResult] = useState<ProtocolDebugResult | null>(null)
  const mutation = useMutation({
    mutationFn: () =>
      executeGraphQL({
        project_id: projectId,
        schema_id: selected.id,
        endpoint,
        operation,
        variables: parseObject(variables, 'Variables'),
        headers: {},
        timeout_seconds: 30,
      }),
    onSuccess: setResult,
    onError: (error) => void message.error(error.message),
  })
  return (
    <div className="protocol-editor">
      <Tabs
        items={[
          {
            key: 'request',
            label: '请求',
            children: (
              <Space orientation="vertical" className="protocol-form" size="middle">
                <Input
                  aria-label="GraphQL Endpoint"
                  value={endpoint}
                  onChange={(event) => setEndpoint(event.target.value)}
                  prefix={<CloudServerOutlined />}
                />
                <TextArea
                  aria-label="GraphQL Operation"
                  rows={10}
                  value={operation}
                  onChange={(event) => setOperation(event.target.value)}
                />
                <TextArea
                  aria-label="GraphQL Variables"
                  rows={5}
                  value={variables}
                  onChange={(event) => setVariables(event.target.value)}
                />
                <Button
                  type="primary"
                  icon={<PlayCircleOutlined />}
                  disabled={!enabled}
                  loading={mutation.isPending}
                  onClick={() => mutation.mutate()}
                >
                  执行 GraphQL
                </Button>
              </Space>
            ),
          },
          { key: 'result', label: '响应', children: <ResultPanel result={result} /> },
        ]}
      />
    </div>
  )
}

function GrpcEditor({ projectId, selected, enabled, credentials = [] }: EditorProps) {
  const methods = descriptorMethods(selected)
  const [endpoint, setEndpoint] = useState('grpc.example.com:443')
  const [methodKey, setMethodKey] = useState(methods[0]?.value)
  const [request, setRequest] = useState('{"id":"42"}')
  const [tlsMode, setTlsMode] = useState<'plaintext' | 'tls' | 'mtls'>('tls')
  const mtlsCredentials = credentials.filter((credential) => credential.kind === 'grpc_mtls')
  const [credentialId, setCredentialId] = useState<string | undefined>(mtlsCredentials.at(0)?.id)
  const [result, setResult] = useState<ProtocolDebugResult | null>(null)
  const selectedMethod = methods.find((item) => item.value === methodKey) ?? methods[0]
  const mutation = useMutation({
    mutationFn: () => {
      if (!selectedMethod) throw new Error('Descriptor 中没有可调用方法')
      return executeGrpc({
        project_id: projectId,
        descriptor_id: selected.id,
        endpoint,
        service: selectedMethod.service,
        method: selectedMethod.method,
        request: parseObject(request, 'Request'),
        metadata: {},
        call_type: selectedMethod.callType,
        tls_mode: tlsMode,
        credential_id: tlsMode === 'mtls' ? credentialId : undefined,
        timeout_seconds: 30,
      })
    },
    onSuccess: setResult,
    onError: (error) => void message.error(error.message),
  })
  return (
    <div className="protocol-editor">
      <Tabs
        items={[
          {
            key: 'request',
            label: '请求',
            children: (
              <Space orientation="vertical" className="protocol-form" size="middle">
                <Input
                  aria-label="gRPC Endpoint"
                  value={endpoint}
                  onChange={(event) => setEndpoint(event.target.value)}
                  prefix={<CloudServerOutlined />}
                />
                <Select
                  aria-label="gRPC Method"
                  value={selectedMethod?.value}
                  options={methods}
                  onChange={setMethodKey}
                  placeholder="选择 Service / Method"
                />
                <Segmented
                  value={tlsMode}
                  options={[
                    { label: 'TLS', value: 'tls' },
                    { label: '明文', value: 'plaintext' },
                    { label: 'mTLS', value: 'mtls' },
                  ]}
                  onChange={setTlsMode}
                />
                {tlsMode === 'mtls' && (
                  <Select
                    aria-label="gRPC mTLS Credential"
                    value={credentialId}
                    options={mtlsCredentials.map((credential) => ({
                      value: credential.id,
                      label: credential.name,
                    }))}
                    onChange={setCredentialId}
                    placeholder="选择 mTLS Credential"
                  />
                )}
                <TextArea
                  aria-label="gRPC Request"
                  rows={10}
                  value={request}
                  onChange={(event) => setRequest(event.target.value)}
                />
                <Button
                  type="primary"
                  icon={<PlayCircleOutlined />}
                  disabled={!enabled || !selectedMethod || (tlsMode === 'mtls' && !credentialId)}
                  loading={mutation.isPending}
                  onClick={() => mutation.mutate()}
                >
                  执行 gRPC
                </Button>
              </Space>
            ),
          },
          { key: 'result', label: '响应流', children: <ResultPanel result={result} /> },
        ]}
      />
    </div>
  )
}

type EditorProps = {
  projectId: string
  selected: SchemaArtifact
  enabled: boolean
  credentials?: Credential[]
}

function ResultPanel({ result }: { result: ProtocolDebugResult | null }) {
  if (!result) return <Empty description="尚未执行" />
  return (
    <div>
      <Space>
        <Tag color="success">Snapshot v{result.schema_version}</Tag>
        <Tag>{result.duration_ms} ms</Tag>
      </Space>
      <pre className="protocol-result">{JSON.stringify(result.output, null, 2)}</pre>
    </div>
  )
}

function SchemaInspector({ asset }: { asset: SchemaArtifact | null }) {
  return (
    <aside className="protocol-inspector">
      <Typography.Title level={4}>Context Inspector</Typography.Title>
      {!asset ? (
        <Empty description="选择版本查看固定信息" />
      ) : (
        <>
          <Typography.Text code>{asset.content_sha256.slice(0, 16)}…</Typography.Text>
          <Descriptions column={1} size="small">
            <Descriptions.Item label="协议">{asset.protocol}</Descriptions.Item>
            <Descriptions.Item label="版本">v{asset.version}</Descriptions.Item>
            <Descriptions.Item label="来源">
              {sourceFormatLabel(asset.source_format)}
            </Descriptions.Item>
            <Descriptions.Item label="类型/服务">{summaryCount(asset)}</Descriptions.Item>
          </Descriptions>
          <Alert
            showIcon
            type="success"
            title="Snapshot 已固定"
            description="执行记录保存该版本与 SHA-256；后续导入不会改变历史结果。"
          />
        </>
      )}
    </aside>
  )
}

function SchemaImportDialog({
  open,
  mode,
  projectId,
  onClose,
  credentials,
}: {
  open: boolean
  mode: SchemaProtocolMode
  projectId: string
  onClose: () => void
  credentials: Credential[]
}) {
  const queryClient = useQueryClient()
  const [form] = Form.useForm<{
    name: string
    source_format: ImportMode
    content: string
    tls_mode: 'plaintext' | 'tls' | 'mtls'
    credential_id?: string
  }>()
  const selectedFormat = Form.useWatch('source_format', form)
  const selectedTlsMode = Form.useWatch('tls_mode', form)
  const mutation = useMutation({
    mutationFn: async (values: {
      name: string
      source_format: ImportMode
      content: string
      tls_mode: 'plaintext' | 'tls' | 'mtls'
      credential_id?: string
    }) => {
      if (values.source_format === 'graphql_sdl')
        return createGraphQLSchema({
          project_id: projectId,
          name: values.name,
          source_format: values.source_format,
          sdl: values.content,
        })
      if (values.source_format === 'graphql_introspection')
        return createGraphQLSchema({
          project_id: projectId,
          name: values.name,
          source_format: values.source_format,
          introspection: parseObject(values.content, 'Introspection'),
        })
      if (values.source_format === 'proto_source')
        return createGrpcDescriptor({
          project_id: projectId,
          name: values.name,
          source_format: values.source_format,
          entrypoint: 'service.proto',
          files: [{ name: 'service.proto', content: values.content }],
        })
      if (values.source_format === 'grpc_reflection')
        return importGrpcReflection({
          project_id: projectId,
          name: values.name,
          endpoint: values.content.trim(),
          tls_mode: values.tls_mode,
          credential_id: values.tls_mode === 'mtls' ? values.credential_id : undefined,
          timeout_seconds: 30,
        })
      return createGrpcDescriptor({
        project_id: projectId,
        name: values.name,
        source_format: values.source_format,
        descriptor_set_base64: values.content.trim(),
      })
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey:
          mode === 'graphql' ? ['graphql-schemas', projectId] : ['grpc-descriptors', projectId],
      })
      message.success('协议 Schema 已保存为不可变版本')
      onClose()
    },
    onError: (error) => void message.error(error.message),
  })
  const sourceOptions =
    mode === 'graphql'
      ? [
          { label: 'SDL', value: 'graphql_sdl' },
          { label: 'Introspection JSON', value: 'graphql_introspection' },
        ]
      : [
          { label: 'Proto Source', value: 'proto_source' },
          { label: 'Protoset Base64', value: 'proto_descriptor_set' },
          { label: 'Server Reflection（TLS）', value: 'grpc_reflection' },
        ]
  return (
    <Modal
      title="导入协议 Schema"
      open={open}
      confirmLoading={mutation.isPending}
      onCancel={onClose}
      onOk={() => form.validateFields().then((values) => mutation.mutate(values))}
      okText="校验并保存"
      destroyOnHidden
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={{
          source_format: sourceOptions[0].value,
          content: mode === 'graphql' ? DEFAULT_SDL : DEFAULT_PROTO,
          tls_mode: 'tls',
        }}
      >
        <Form.Item label="名称" name="name" rules={[{ required: true }]}>
          <Input />
        </Form.Item>
        <Form.Item label="导入格式" name="source_format">
          <Select
            options={sourceOptions}
            onChange={(value: ImportMode) => {
              if (value === 'grpc_reflection') form.setFieldValue('content', 'grpc.example.com:443')
            }}
          />
        </Form.Item>
        <Form.Item
          label={selectedFormat === 'grpc_reflection' ? 'Reflection Endpoint' : 'Schema 内容'}
          name="content"
          rules={[{ required: true }]}
        >
          <TextArea
            aria-label="Schema 内容"
            rows={selectedFormat === 'grpc_reflection' ? 2 : 16}
            placeholder={selectedFormat === 'grpc_reflection' ? 'grpc.example.com:443' : undefined}
          />
        </Form.Item>
        {selectedFormat === 'grpc_reflection' && (
          <>
            <Form.Item label="传输安全" name="tls_mode" rules={[{ required: true }]}>
              <Segmented
                options={[
                  { label: 'TLS', value: 'tls' },
                  { label: '明文', value: 'plaintext' },
                  { label: 'mTLS', value: 'mtls' },
                ]}
              />
            </Form.Item>
            {selectedTlsMode === 'mtls' && (
              <Form.Item
                label="mTLS Credential"
                name="credential_id"
                rules={[{ required: true, message: '请选择 mTLS Credential' }]}
              >
                <Select
                  options={credentials
                    .filter((credential) => credential.kind === 'grpc_mtls')
                    .map((credential) => ({ value: credential.id, label: credential.name }))}
                />
              </Form.Item>
            )}
          </>
        )}
      </Form>
    </Modal>
  )
}

function useSelectedAsset(items: SchemaArtifact[], selectedId: string | null) {
  return useMemo(
    () => items.find((item) => item.id === selectedId) ?? items[0] ?? null,
    [items, selectedId],
  )
}

function protocolItems(
  mode: SchemaProtocolMode,
  graphql: SchemaArtifact[],
  grpc: SchemaArtifact[],
): SchemaArtifact[] {
  if (mode === 'graphql') return graphql
  return grpc
}

function pageItems(page: { items: SchemaArtifact[] } | undefined): SchemaArtifact[] {
  if (page) return page.items
  return []
}

function pageTotal(page: { total: number } | undefined): number {
  if (page) return page.total
  return 0
}

function selectionId(
  selection: { mode: SchemaProtocolMode; id: string } | null,
  mode: SchemaProtocolMode,
): string | null {
  if (selection?.mode === mode) return selection.id
  return null
}

function assetId(asset: SchemaArtifact | null): string | null {
  if (asset) return asset.id
  return null
}

type GrpcMethodOption = {
  value: string
  label: string
  service: string
  method: string
  callType: 'unary' | 'server_streaming'
}

function descriptorMethods(asset: SchemaArtifact): GrpcMethodOption[] {
  const services = Array.isArray(asset.summary.services) ? asset.summary.services : []
  return services.flatMap((service) => {
    if (!isRecord(service) || typeof service.name !== 'string' || !Array.isArray(service.methods))
      return []
    const serviceName = service.name
    return service.methods.flatMap((method) => {
      if (!isRecord(method) || typeof method.name !== 'string') return []
      const callType: GrpcMethodOption['callType'] =
        method.call_type === 'server_streaming' ? 'server_streaming' : 'unary'
      return [
        {
          value: `${serviceName}/${method.name}`,
          label: `${serviceName} / ${method.name}`,
          service: serviceName,
          method: method.name,
          callType,
        },
      ]
    })
  })
}

function parseObject(value: string, label: string): Record<string, unknown> {
  const parsed: unknown = JSON.parse(value)
  if (!isRecord(parsed)) throw new Error(`${label} 必须是 JSON 对象`)
  return parsed
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}
function sourceFormatLabel(value: string) {
  return (
    {
      graphql_sdl: 'SDL',
      graphql_introspection: 'Introspection',
      proto_source: 'Proto',
      proto_descriptor_set: 'Protoset',
      grpc_reflection: 'Reflection',
    }[value] ?? value
  )
}
function summaryCount(asset: SchemaArtifact) {
  return asset.protocol === 'graphql'
    ? `${String(asset.summary.type_count ?? 0)} 类型`
    : `${String(asset.summary.service_count ?? 0)} 服务`
}
