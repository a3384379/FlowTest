import CatalogPagination from '../components/CatalogPagination'
import QueryFailureNotice from '../components/QueryFailureNotice'
import { useProjectCapabilities } from '../features/projects/use-project-capabilities'
import {
  useProtocolLocation,
  type ProtocolMode,
  type SchemaProtocolMode,
} from '../features/protocols/protocol-location'
import {
  useProtocolCatalog,
  useSelectedProtocolAsset,
} from '../features/protocols/use-protocol-catalog'
import {
  ApiOutlined,
  CloudServerOutlined,
  ImportOutlined,
  PlayCircleOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  Descriptions,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Row,
  Segmented,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Typography,
} from 'antd'
import { useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import ProtocolFailurePanel from '../features/protocols/ProtocolFailurePanel'
import ProtocolContractBrowser from '../features/protocols/ProtocolContractBrowser'
import { Link } from 'react-router-dom'
import { WorkflowResourceReturn } from '../flow/WorkflowResourceNavigation'

import { getV3FeatureFlags } from '../features/capabilities/capability-service'
import { listCredentials } from '../features/data-sources/data-source-service'
import { useProjectContext } from '../features/projects/use-project-context'
import EventProtocolWorkspace from '../features/protocols/EventProtocolWorkspace'
import {
  createGraphQLSchema,
  createGrpcDescriptor,
  executeGraphQL,
  executeGrpc,
  importGrpcReflection,
  listGraphQLSchemas,
  listGrpcDescriptors,
  getGraphQLSchema,
  locateGraphQLError,
  getGrpcDescriptor,
  type ProtocolDebugResult,
  type SchemaArtifact,
} from '../features/protocols/protocol-service'
import { apiErrorWithTrace, type Credential } from '../lib/api'
import { DraftContext, useDraftSession } from '../features/drafts/draft-session'
import { useProtocolImportFeedback } from '../features/protocols/use-protocol-import-feedback'
import ProtocolHeadersEditor from '../features/protocols/ProtocolHeadersEditor'
import { useProtocolRequestDraft } from '../features/protocols/use-protocol-request-draft'
import {
  protocolRequestHeaders,
  type GraphQLRequestDraft,
  type GrpcRequestDraft,
} from '../features/protocols/protocol-request-draft'

const { TextArea } = Input

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
  const draftSession = useDraftSession()

  if (!projectId) return <Empty description="请先选择项目" />
  return (
    <DraftContext.Provider value={draftSession}>
      <ProjectProtocolWorkbench key={projectId} projectId={projectId} />
    </DraftContext.Provider>
  )
}

function useProtocolWorkbench(projectId: string) {
  const location = useProtocolLocation()
  const { mode, setMode } = location
  const [importOpen, setImportOpen] = useState(false)
  const schemaMode: SchemaProtocolMode = mode === 'grpc' ? 'grpc' : 'graphql'
  const { canEdit, canExecute, permissions } = useProjectCapabilities()
  const inventory = useProtocolInventory(projectId, schemaMode, location)
  const credentials = useQuery({
    queryKey: ['credentials', projectId],
    queryFn: () => listCredentials(projectId),
  })
  const selection = useSelectedProtocolAsset(
    projectId,
    schemaMode === 'graphql' ? 'graphql-schemas' : 'grpc-descriptors',
    location.id,
    inventory.items,
    (id) =>
      schemaMode === 'graphql' ? getGraphQLSchema(projectId, id) : getGrpcDescriptor(projectId, id),
    location.selectAsset,
    !location.error && (mode === 'graphql' || mode === 'grpc'),
  )
  const selected = selection.selected
  const eventMode = mode === 'kafka' || mode === 'websocket'
  return {
    location,
    mode,
    schemaMode,
    importOpen,
    setImportOpen,
    canEdit,
    canExecute,
    permissions,
    inventory,
    credentials,
    selection,
    selected,
    eventMode,
    setMode,
  }
}

type ProtocolWorkspaceState = ReturnType<typeof useProtocolWorkbench>

function ProjectProtocolWorkbench({ projectId }: { projectId: string }) {
  const state = useProtocolWorkbench(projectId)
  const {
    location,
    mode,
    schemaMode,
    importOpen,
    setImportOpen,
    canEdit,
    permissions,
    inventory,
    credentials,
    selection,
    eventMode,
    setMode,
  } = state

  return (
    <div className="protocol-page">
      <QueryFailureNotice queries={[inventory.flags, credentials, permissions, selection.query]} />
      {location.error && (
        <Alert
          type="error"
          showIcon
          title={location.error}
          action={<Button onClick={location.reset}>重置协议范围</Button>}
        />
      )}
      <ProtocolCatalogControls state={state} />
      <ProtocolHeading
        onImport={eventMode || !canEdit || location.error ? undefined : () => setImportOpen(true)}
      />
      <WorkflowResourceReturn projectId={projectId} />
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
        <ProtocolBody projectId={projectId} state={state} />
      </Card>
      {importOpen && !eventMode && (
        <SchemaImportDialog
          key={`${projectId}:${schemaMode}`}
          open
          editable={canEdit && !location.error}
          mode={schemaMode}
          projectId={projectId}
          onClose={() => setImportOpen(false)}
          credentials={credentials.data ?? []}
        />
      )}
    </div>
  )
}

function ProtocolCatalogControls({ state }: { state: ProtocolWorkspaceState }) {
  const { eventMode, schemaMode, inventory } = state
  if (eventMode || state.location.error) return null
  return (
    <div className="catalog-controls">
      <CatalogPagination
        query={schemaMode === 'graphql' ? inventory.graphql : inventory.grpc}
        label={schemaMode === 'graphql' ? 'GraphQL Schema' : 'gRPC 描述文件'}
      />
    </div>
  )
}

function ProtocolBody({ projectId, state }: { projectId: string; state: ProtocolWorkspaceState }) {
  const { location, mode, canEdit, canExecute, inventory, schemaMode, selected, credentials } =
    state
  if (location.error) return null
  if (mode === 'kafka' || mode === 'websocket')
    return (
      <EventProtocolWorkspace
        key={`${projectId}:${mode}`}
        editable={canEdit}
        executable={canExecute}
        projectId={projectId}
        mode={mode}
        enabled={inventory.eventProtocolsEnabled}
      />
    )
  return (
    <div className="protocol-workspace-grid">
      <div>
        {selected && (
          <Typography.Paragraph>
            {selected.name} · v{selected.version}
          </Typography.Paragraph>
        )}
        <SchemaInventory
          mode={schemaMode}
          items={inventory.items}
          loading={inventory.loading}
          selectedId={assetId(selected)}
          onSelect={(item) => location.selectAsset(item.id)}
        />
      </div>
      <ProtocolEditor
        mode={schemaMode}
        projectId={projectId}
        selected={selected}
        enabled={inventory.enabled && canExecute}
        credentials={credentials.data ?? []}
      />
    </div>
  )
}

function useProtocolInventory(
  projectId: string,
  mode: SchemaProtocolMode,
  location: ReturnType<typeof useProtocolLocation>,
) {
  const flags = useQuery({ queryKey: ['v3-feature-flags'], queryFn: getV3FeatureFlags })
  const schemaMode = location.mode === 'graphql' || location.mode === 'grpc'
  const graphql = useProtocolCatalog(
    'graphql-schemas',
    projectId,
    '',
    mode === 'graphql' && schemaMode ? location.page : 1,
    location.setPage,
    (page) => listGraphQLSchemas(projectId, page, 20),
    !location.error,
  )
  const grpc = useProtocolCatalog(
    'grpc-descriptors',
    projectId,
    '',
    mode === 'grpc' && schemaMode ? location.page : 1,
    location.setPage,
    (page) => listGrpcDescriptors(projectId, page, 20),
    !location.error,
  )
  return {
    flags,
    graphql,
    grpc,
    enabled: flags.data?.multi_protocol === true,
    eventProtocolsEnabled: flags.data?.event_protocols === true,
    items: protocolItems(mode, pageItems(graphql.data), pageItems(grpc.data)),
    graphqlTotal: pageTotal(graphql.data),
    grpcTotal: pageTotal(grpc.data),
    loading: (mode === 'graphql' ? graphql : grpc).isLoading,
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
        <Space align="center" wrap>
          <Typography.Title level={2}>多协议接口工作台</Typography.Title>
          <Tag color="blue">协议资产与调试</Tag>
        </Space>
        <Typography.Paragraph type="secondary">
          统一管理 GraphQL、gRPC、Kafka 与 WebSocket，并将协议资产版本固定到执行 Snapshot。
        </Typography.Paragraph>
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

function ProtocolSummary({
  graphql,
  grpc,
}: {
  graphql: number | undefined
  grpc: number | undefined
}) {
  return (
    <Row gutter={16} className="protocol-summary">
      <Col xs={24} sm={8}>
        <Card>
          <Typography.Text type="secondary">GraphQL Schema</Typography.Text>
          <Typography.Title level={3}>{graphql ?? '—'}</Typography.Title>
        </Card>
      </Col>
      <Col xs={24} sm={8}>
        <Card>
          <Typography.Text type="secondary">gRPC Descriptor</Typography.Text>
          <Typography.Title level={3}>{grpc ?? '—'}</Typography.Title>
        </Card>
      </Col>
      <Col xs={24} sm={8}>
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
        pagination={false}
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
      <>
        <div className="protocol-editor">
          <Empty description="选择 Schema 版本开始调试" />
        </div>
        <SchemaInspector asset={null} />
      </>
    )
  return mode === 'graphql' ? (
    <GraphQLEditor
      key={`${projectId}:${selected.id}:${selected.version}:${selected.content_sha256}`}
      projectId={projectId}
      selected={selected}
      enabled={enabled}
    />
  ) : (
    <GrpcEditor
      key={`${projectId}:${selected.id}:${selected.version}:${selected.content_sha256}`}
      projectId={projectId}
      selected={selected}
      enabled={enabled}
      credentials={credentials}
    />
  )
}

function GraphQLEditor({ projectId, selected, enabled }: EditorProps) {
  const { message } = App.useApp()
  const active = useRef(true)
  const generation = useRef(0)
  useLayoutEffect(() => {
    active.current = true
    return () => {
      active.current = false
    }
  }, [])
  const { draft, patch, reset } = useProtocolRequestDraft<GraphQLRequestDraft>(
    `${projectId}:graphql:${selected.id}:${selected.version}:${selected.content_sha256}`,
    {
      mode: 'graphql',
      endpoint: 'https://api.example.com/graphql',
      operation: 'query User($id: ID!) { user(id: $id) { id name } }',
      operationName: '',
      variables: '{"id":"42"}',
      authorization: '',
      headers: [],
      timeoutSeconds: 30,
    },
  )
  const { endpoint, operation, variables } = draft
  const [requestError, setRequestError] = useState<unknown>(null)
  const [contractFocus, setContractFocus] = useState<string>('root')
  const [activeTab, setActiveTab] = useState('request')
  const [result, setResult] = useState<ProtocolDebugResult | null>(null)
  const mutation = useMutation({
    mutationFn: (input: GraphQLRequestDraft) =>
      executeGraphQL({
        project_id: projectId,
        schema_id: selected.id,
        endpoint: input.endpoint,
        operation: input.operation,
        operation_name: input.operationName || undefined,
        variables: parseObject(input.variables, 'Variables'),
        headers: protocolRequestHeaders('graphql', input.headers, input.authorization),
        timeout_seconds: input.timeoutSeconds,
      }),
    onMutate: () => {
      setRequestError(null)
      setResult(null)
      return ++generation.current
    },
    onSuccess: (value, _input, revision) => {
      if (active.current && revision === generation.current) setResult(value)
    },
    onError: (error, _input, revision) => {
      if (active.current && revision === generation.current) {
        setRequestError(error)
        void message.error(apiErrorWithTrace(error))
      }
    },
  })
  const locate = useMutation({
    mutationFn: (input: {
      path: Array<string | number>
      operation: string
      operation_name?: string
    }) => locateGraphQLError(selected, input),
    onMutate: () => generation.current,
    onSuccess: (node, _path, revision) => {
      if (active.current && revision === generation.current) setContractFocus(node)
    },
    onError: (error, _path, revision) => {
      if (active.current && revision === generation.current)
        void message.error(apiErrorWithTrace(error))
    },
  })
  function changeRequest(change: () => void) {
    generation.current += 1
    setResult(null)
    setRequestError(null)
    setContractFocus('root')
    change()
  }
  return (
    <>
      <div className="protocol-editor">
        <Tabs
          activeKey={activeTab}
          onChange={setActiveTab}
          items={[
            {
              key: 'request',
              label: '请求',
              children: (
                <Space orientation="vertical" className="protocol-form" size="middle">
                  <Input
                    aria-label="GraphQL Endpoint"
                    value={endpoint}
                    onChange={(event) =>
                      changeRequest(() => patch({ endpoint: event.target.value }))
                    }
                    prefix={<CloudServerOutlined />}
                  />
                  <TextArea
                    aria-label="GraphQL Operation"
                    rows={10}
                    value={operation}
                    onChange={(event) =>
                      changeRequest(() => patch({ operation: event.target.value }))
                    }
                  />
                  <TextArea
                    aria-label="GraphQL Variables"
                    rows={5}
                    value={variables}
                    onChange={(event) =>
                      changeRequest(() => patch({ variables: event.target.value }))
                    }
                  />
                  <Input
                    aria-label="GraphQL Operation Name"
                    value={draft.operationName}
                    placeholder="操作名称（可选）"
                    onChange={(event) =>
                      changeRequest(() => patch({ operationName: event.target.value }))
                    }
                  />
                  <label>
                    GraphQL超时（秒）
                    <InputNumber
                      aria-label="GraphQL超时"
                      min={1}
                      max={300}
                      value={draft.timeoutSeconds}
                      onChange={(value) =>
                        changeRequest(() => patch({ timeoutSeconds: value ?? 30 }))
                      }
                    />
                  </label>
                  <ProtocolHeadersEditor
                    mode="graphql"
                    rows={draft.headers}
                    authorization={draft.authorization}
                    onAuthorization={(authorization) =>
                      changeRequest(() => patch({ authorization }))
                    }
                    onChange={(update) =>
                      changeRequest(() =>
                        patch((current) => ({
                          headers: typeof update === 'function' ? update(current.headers) : update,
                        })),
                      )
                    }
                  />
                  <Typography.Text type="secondary">
                    请求草稿只保留在当前会话，按协议与固定版本隔离；不会写入浏览器持久存储。
                  </Typography.Text>
                  <Button onClick={() => changeRequest(reset)}>重置GraphQL请求草稿</Button>
                  <Button
                    type="primary"
                    icon={<PlayCircleOutlined />}
                    disabled={!enabled}
                    loading={mutation.isPending}
                    onClick={() => mutation.mutate(draft)}
                  >
                    执行 GraphQL
                  </Button>
                </Space>
              ),
            },
            {
              key: 'result',
              label: '响应',
              children: (
                <>
                  <ProtocolFailurePanel
                    error={requestError}
                    locating={locate.isPending}
                    onLocate={(path) =>
                      locate.mutate({
                        path,
                        operation: draft.operation,
                        operation_name: draft.operationName || undefined,
                      })
                    }
                  />
                  <ResultPanel result={result} />
                </>
              ),
            },
          ]}
        />
      </div>
      <SchemaInspector asset={selected}>
        <ProtocolContractBrowser
          key={contractFocus}
          initialNode={contractFocus}
          asset={selected}
          onExample={(example) => {
            const { operation, variables } = example
            if (!operation || !variables) return
            changeRequest(() =>
              patch({
                operation,
                variables: JSON.stringify(variables, null, 2),
                operationName: 'FlowTestExample',
              }),
            )
            setActiveTab('request')
          }}
        />
      </SchemaInspector>
    </>
  )
}

function GrpcEditor({ projectId, selected, enabled, credentials = [] }: EditorProps) {
  const { message } = App.useApp()
  const active = useRef(true)
  const generation = useRef(0)
  useLayoutEffect(() => {
    active.current = true
    return () => {
      active.current = false
    }
  }, [])
  const methods = descriptorMethods(selected)
  const mtlsCredentials = credentials.filter((credential) => credential.kind === 'grpc_mtls')
  const { draft, patch, reset } = useProtocolRequestDraft<GrpcRequestDraft>(
    `${projectId}:grpc:${selected.id}:${selected.version}:${selected.content_sha256}`,
    {
      mode: 'grpc',
      endpoint: 'grpc.example.com:443',
      methodKey: methods[0]?.value,
      request: '{"id":"42"}',
      tlsMode: 'tls',
      credentialId: mtlsCredentials.at(0)?.id,
      authorization: '',
      metadata: [],
      timeoutSeconds: 30,
    },
  )
  const { endpoint, methodKey, request, tlsMode, credentialId } = draft
  const credentialAvailable = mtlsCredentials.some((credential) => credential.id === credentialId)
  const [requestError, setRequestError] = useState<unknown>(null)
  const [contractFocus, setContractFocus] = useState<string>('root')
  const [activeTab, setActiveTab] = useState('request')
  const [result, setResult] = useState<ProtocolDebugResult | null>(null)
  const methodOptions = availableGrpcMethods(methods, draft)
  const selectedMethod = methodOptions.find((item) => item.value === methodKey)
  const mutation = useMutation({
    mutationFn: (input: GrpcRequestDraft & { method: typeof selectedMethod }) => {
      if (!input.method) throw new Error('Descriptor 中没有可调用方法')
      return executeGrpc({
        project_id: projectId,
        descriptor_id: selected.id,
        endpoint: input.endpoint,
        service: input.method.service,
        method: input.method.method,
        request: parseObject(input.request, 'Request'),
        metadata: protocolRequestHeaders('grpc', input.metadata, input.authorization),
        call_type: input.method.callType,
        tls_mode: input.tlsMode,
        credential_id: input.tlsMode === 'mtls' ? input.credentialId : undefined,
        timeout_seconds: input.timeoutSeconds,
      })
    },
    onMutate: () => {
      setRequestError(null)
      setResult(null)
      return ++generation.current
    },
    onSuccess: (value, _input, revision) => {
      if (active.current && revision === generation.current) setResult(value)
    },
    onError: (error, _input, revision) => {
      if (active.current && revision === generation.current) {
        setRequestError(error)
        void message.error(apiErrorWithTrace(error))
      }
    },
  })
  function changeRequest(change: () => void) {
    generation.current += 1
    setResult(null)
    setRequestError(null)
    setContractFocus('root')
    change()
  }
  return (
    <>
      <div className="protocol-editor">
        <Tabs
          activeKey={activeTab}
          onChange={setActiveTab}
          items={[
            {
              key: 'request',
              label: '请求',
              children: (
                <Space orientation="vertical" className="protocol-form" size="middle">
                  <Input
                    aria-label="gRPC Endpoint"
                    value={endpoint}
                    onChange={(event) =>
                      changeRequest(() => patch({ endpoint: event.target.value }))
                    }
                    prefix={<CloudServerOutlined />}
                  />
                  <Select
                    aria-label="gRPC Method"
                    value={selectedMethod?.value}
                    options={methodOptions}
                    onChange={(value) =>
                      changeRequest(() => patch({ methodKey: value, methodContract: undefined }))
                    }
                    placeholder="选择 Service / Method"
                  />
                  <Segmented<'plaintext' | 'tls' | 'mtls'>
                    value={tlsMode}
                    options={[
                      { label: 'TLS', value: 'tls' },
                      { label: '明文', value: 'plaintext' },
                      { label: 'mTLS', value: 'mtls' },
                    ]}
                    onChange={(value) => changeRequest(() => patch({ tlsMode: value }))}
                  />
                  {tlsMode === 'mtls' && (
                    <GrpcCredentialSelect
                      credentials={mtlsCredentials}
                      credentialId={credentialId}
                      available={credentialAvailable}
                      onChange={(value) => changeRequest(() => patch({ credentialId: value }))}
                    />
                  )}
                  <TextArea
                    aria-label="gRPC Request"
                    rows={10}
                    value={request}
                    onChange={(event) =>
                      changeRequest(() => patch({ request: event.target.value }))
                    }
                  />
                  <label>
                    gRPC超时（秒）
                    <InputNumber
                      aria-label="gRPC超时"
                      min={1}
                      max={300}
                      value={draft.timeoutSeconds}
                      onChange={(value) =>
                        changeRequest(() => patch({ timeoutSeconds: value ?? 30 }))
                      }
                    />
                  </label>
                  <ProtocolHeadersEditor
                    mode="grpc"
                    rows={draft.metadata}
                    authorization={draft.authorization}
                    onAuthorization={(authorization) =>
                      changeRequest(() => patch({ authorization }))
                    }
                    onChange={(update) =>
                      changeRequest(() =>
                        patch((current) => ({
                          metadata:
                            typeof update === 'function' ? update(current.metadata) : update,
                        })),
                      )
                    }
                  />
                  <Typography.Text type="secondary">
                    请求草稿只保留在当前会话，TLS/mTLS与凭据引用保持独立；不会读取凭据明文。
                  </Typography.Text>
                  <Button onClick={() => changeRequest(reset)}>重置gRPC请求草稿</Button>
                  <Button
                    type="primary"
                    icon={<PlayCircleOutlined />}
                    disabled={
                      !enabled || !selectedMethod || (tlsMode === 'mtls' && !credentialAvailable)
                    }
                    loading={mutation.isPending}
                    onClick={() =>
                      mutation.mutate({
                        ...draft,
                        method: selectedMethod,
                      })
                    }
                  >
                    执行 gRPC
                  </Button>
                </Space>
              ),
            },
            {
              key: 'result',
              label: '响应流',
              children: (
                <>
                  <GrpcRequestFailure
                    error={requestError}
                    method={selectedMethod}
                    onLocate={setContractFocus}
                  />
                  <ResultPanel result={result} />
                </>
              ),
            },
          ]}
        />
      </div>
      <SchemaInspector asset={selected}>
        <ProtocolContractBrowser
          key={contractFocus}
          initialNode={contractFocus}
          asset={selected}
          onExample={(example) => {
            const { service, method, request, call_type } = example
            if (!service || !method || !request || !call_type) return
            changeRequest(() =>
              patch({
                methodKey: `${service}/${method}`,
                methodContract: {
                  service,
                  method,
                  callType: call_type,
                },
                request: JSON.stringify(request, null, 2),
              }),
            )
            setActiveTab('request')
          }}
        />
      </SchemaInspector>
    </>
  )
}

function GrpcRequestFailure({
  error,
  method,
  onLocate,
}: {
  error: unknown
  method: GrpcMethodOption | undefined
  onLocate: (node: string) => void
}) {
  if (!error) return null
  return (
    <>
      <ProtocolFailurePanel error={error} />
      {method && (
        <Button onClick={() => onLocate(`method:${method.service}/${method.method}`)}>
          定位当前方法契约
        </Button>
      )}
    </>
  )
}

function GrpcCredentialSelect({
  credentials,
  credentialId,
  available,
  onChange,
}: {
  credentials: Credential[]
  credentialId: string | undefined
  available: boolean
  onChange: (id: string) => void
}) {
  const options = credentials.map((credential) => ({
    value: credential.id,
    label: credential.name,
    disabled: false,
  }))
  if (credentialId && !available)
    options.push({ value: credentialId, label: '不可用凭据', disabled: true })
  return (
    <>
      <Select
        aria-label="gRPC mTLS Credential"
        value={credentialId}
        options={options}
        onChange={onChange}
        placeholder="选择 mTLS Credential"
      />
      {!available && <Alert type="warning" title="所选mTLS凭据不可用，请重新选择。" />}
    </>
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

function SchemaInspector({
  asset,
  children,
}: {
  asset: SchemaArtifact | null
  children?: ReactNode
}) {
  return (
    <aside className="protocol-inspector">
      <Typography.Title level={4}>契约检查器</Typography.Title>
      {!asset ? (
        <Empty description="选择版本查看固定信息" />
      ) : (
        <>
          <Typography.Paragraph code copyable>
            {asset.content_sha256}
          </Typography.Paragraph>
          <Descriptions column={1} size="small">
            <Descriptions.Item label="协议">{asset.protocol}</Descriptions.Item>
            <Descriptions.Item label="版本">v{asset.version}</Descriptions.Item>
            <Descriptions.Item label="来源">
              {sourceFormatLabel(asset.source_format)}
            </Descriptions.Item>
            <Descriptions.Item label="类型/服务">{summaryCount(asset)}</Descriptions.Item>
          </Descriptions>
          {children}
          <Alert
            showIcon
            type="info"
            title="执行时固定版本"
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
  editable,
}: {
  editable: boolean
  open: boolean
  mode: SchemaProtocolMode
  projectId: string
  onClose: () => void
  credentials: Credential[]
}) {
  const feedback = useProtocolImportFeedback(editable)
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
      if (feedback.allowed()) {
        feedback.success('协议 Schema 已保存为不可变版本')
        onClose()
      }
    },
    onError: feedback.error,
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
      onCancel={onClose}
      onOk={() => form.submit()}
      okButtonProps={{ disabled: !editable || mutation.isPending, loading: mutation.isPending }}
      okText="校验并保存"
      destroyOnHidden
    >
      <Form
        form={form}
        disabled={!editable || mutation.isPending}
        onFinish={(values) => {
          if (feedback.allowed() && !mutation.isPending) mutation.mutate(values)
        }}
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

function pageTotal(page: { total: number } | undefined): number | undefined {
  if (page) return page.total
  return undefined
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

function availableGrpcMethods(
  methods: GrpcMethodOption[],
  draft: GrpcRequestDraft,
): GrpcMethodOption[] {
  const contract = draft.methodContract
  if (!contract || methods.some((item) => item.value === draft.methodKey)) return methods
  const option = {
    ...contract,
    value: `${contract.service}/${contract.method}`,
    label: `${contract.service} / ${contract.method}`,
  }
  return [...methods, option]
}

function descriptorMethods(asset: SchemaArtifact): GrpcMethodOption[] {
  const services = Array.isArray(asset.summary.services) ? asset.summary.services : []
  return services.flatMap((service) => {
    if (!isRecord(service) || typeof service.name !== 'string' || !Array.isArray(service.methods))
      return []
    const serviceName = service.name
    return service.methods.flatMap((method) => {
      if (
        !isRecord(method) ||
        typeof method.name !== 'string' ||
        (method.call_type !== 'unary' && method.call_type !== 'server_streaming')
      )
        return []
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
    ? `${String(asset.summary.type_count ?? '未提供')} 类型`
    : `${String(asset.summary.service_count ?? '未提供')} 服务`
}
