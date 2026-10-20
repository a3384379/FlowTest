import { apiClient, type Page } from '../../lib/api'

export type SchemaArtifact = {
  id: string
  project_id: string
  protocol: 'graphql' | 'grpc' | 'kafka'
  name: string
  description: string
  version: number
  source_format: string
  content_sha256: string
  summary: Record<string, unknown>
  created_by_id: string
  created_at: string
  updated_at: string
}

export type ProtocolDebugResult = {
  output: Record<string, unknown>
  schema_id: string
  schema_version: number
  schema_hash: string
  duration_ms: number
}

export type EventSource = {
  id: string
  project_id: string
  kind: 'kafka' | 'websocket'
  name: string
  description: string
  version: number
  endpoints: string[]
  schema_registry_url: string | null
  config_sha256: string
  created_by_id: string
  created_at: string
  updated_at: string
}

export type EventDebugResult = {
  output: Record<string, unknown>
  duration_ms: number
}

export async function listGraphQLSchemas(
  projectId: string,
  page = 1,
  pageSize = 100,
): Promise<Page<SchemaArtifact>> {
  return (
    await apiClient.get<Page<SchemaArtifact>>('/graphql/schemas', {
      params: { project_id: projectId, page, page_size: pageSize },
    })
  ).data
}

export async function getGraphQLSchema(projectId: string, id: string): Promise<SchemaArtifact> {
  return (
    await apiClient.get<SchemaArtifact>(`/graphql/schemas/${id}`, {
      params: { project_id: projectId },
    })
  ).data
}
export async function getGrpcDescriptor(projectId: string, id: string): Promise<SchemaArtifact> {
  return (
    await apiClient.get<SchemaArtifact>(`/grpc/descriptors/${id}`, {
      params: { project_id: projectId },
    })
  ).data
}
export async function getEventSource(
  projectId: string,
  id: string,
  kind: EventSource['kind'],
): Promise<EventSource> {
  return (
    await apiClient.get<EventSource>(`/event-sources/${id}`, {
      params: { project_id: projectId, kind },
    })
  ).data
}

export async function createGraphQLSchema(input: {
  project_id: string
  name: string
  description?: string
  source_format: 'graphql_sdl' | 'graphql_introspection'
  sdl?: string
  introspection?: Record<string, unknown>
}): Promise<SchemaArtifact> {
  return (await apiClient.post<SchemaArtifact>('/graphql/schemas', input)).data
}

export async function executeGraphQL(input: {
  project_id: string
  schema_id: string
  endpoint: string
  operation: string
  operation_name?: string
  variables: Record<string, unknown>
  headers: Record<string, string>
  timeout_seconds: number
}): Promise<ProtocolDebugResult> {
  return (await apiClient.post<ProtocolDebugResult>('/graphql/execute', input)).data
}

export async function listGrpcDescriptors(
  projectId: string,
  page = 1,
  pageSize = 100,
): Promise<Page<SchemaArtifact>> {
  return (
    await apiClient.get<Page<SchemaArtifact>>('/grpc/descriptors', {
      params: { project_id: projectId, page, page_size: pageSize },
    })
  ).data
}

export async function createGrpcDescriptor(input: {
  project_id: string
  name: string
  description?: string
  source_format: 'proto_source' | 'proto_descriptor_set'
  entrypoint?: string
  files?: Array<{ name: string; content: string }>
  descriptor_set_base64?: string
}): Promise<SchemaArtifact> {
  return (await apiClient.post<SchemaArtifact>('/grpc/descriptors', input)).data
}

export async function importGrpcReflection(input: {
  project_id: string
  name: string
  description?: string
  endpoint: string
  tls_mode: 'plaintext' | 'tls' | 'mtls'
  credential_id?: string
  timeout_seconds: number
}): Promise<SchemaArtifact> {
  return (await apiClient.post<SchemaArtifact>('/grpc/descriptors/reflection', input)).data
}

export async function executeGrpc(input: {
  project_id: string
  descriptor_id: string
  endpoint: string
  service: string
  method: string
  request: Record<string, unknown>
  metadata: Record<string, string>
  call_type: 'unary' | 'server_streaming'
  tls_mode: 'plaintext' | 'tls' | 'mtls'
  credential_id?: string
  timeout_seconds: number
}): Promise<ProtocolDebugResult> {
  return (await apiClient.post<ProtocolDebugResult>('/grpc/execute', input)).data
}

export async function listEventSources(
  projectId: string,
  kind?: EventSource['kind'],
  page = 1,
  pageSize = 100,
): Promise<Page<EventSource>> {
  return (
    await apiClient.get<Page<EventSource>>('/event-sources', {
      params: { project_id: projectId, kind, page, page_size: pageSize },
    })
  ).data
}

export async function createEventSource(input: {
  project_id: string
  kind: EventSource['kind']
  name: string
  description?: string
  bootstrap_servers?: string[]
  websocket_url?: string
  schema_registry_url?: string
}): Promise<EventSource> {
  return (await apiClient.post<EventSource>('/event-sources', input)).data
}

export async function listEventSchemas(
  projectId: string,
  sourceId: string,
  page = 1,
  pageSize = 100,
): Promise<Page<SchemaArtifact>> {
  return (
    await apiClient.get<Page<SchemaArtifact>>(`/event-sources/${sourceId}/schemas`, {
      params: { project_id: projectId, page, page_size: pageSize },
    })
  ).data
}

export async function getEventSchema(
  projectId: string,
  sourceId: string,
  id: string,
): Promise<SchemaArtifact> {
  return (
    await apiClient.get<SchemaArtifact>(`/event-sources/${sourceId}/schemas/${id}`, {
      params: { project_id: projectId },
    })
  ).data
}

export async function createEventSchema(
  projectId: string,
  sourceId: string,
  input: {
    name: string
    description?: string
    schema_format: 'avro' | 'json_schema' | 'protobuf'
    schema?: string
    entrypoint?: string
    files?: Array<{ name: string; content: string }>
    registry_id?: number
  },
): Promise<SchemaArtifact> {
  return (
    await apiClient.post<SchemaArtifact>(`/event-sources/${sourceId}/schemas`, input, {
      params: { project_id: projectId },
    })
  ).data
}

export async function importEventRegistrySchema(
  projectId: string,
  sourceId: string,
  input: { name: string; subject: string; version?: number | 'latest'; timeout_seconds?: number },
): Promise<SchemaArtifact> {
  return (
    await apiClient.post<SchemaArtifact>(`/event-sources/${sourceId}/schemas/import`, input, {
      params: { project_id: projectId },
    })
  ).data
}

export async function produceKafkaMessage(
  sourceId: string,
  input: {
    project_id: string
    topic: string
    value: unknown
    key?: string
    headers?: Record<string, string>
    correlation_header?: string
    correlation_id?: string
    schema_id?: string
    message_type?: string
    timeout_seconds?: number
  },
): Promise<EventDebugResult> {
  return (await apiClient.post<EventDebugResult>(`/event-sources/${sourceId}/kafka/produce`, input))
    .data
}

export async function consumeKafkaMessages(
  sourceId: string,
  input: {
    project_id: string
    topic: string
    offset: 'earliest' | 'latest'
    maximum_messages: number
    correlation_header?: string
    correlation_id?: string
    schema_id?: string
    message_type?: string
    timeout_seconds?: number
  },
): Promise<EventDebugResult> {
  return (await apiClient.post<EventDebugResult>(`/event-sources/${sourceId}/kafka/consume`, input))
    .data
}

export async function exchangeWebSocketMessage(
  sourceId: string,
  input: {
    project_id: string
    payload_kind: 'json' | 'text'
    message: unknown
    headers?: Record<string, string>
    subprotocols?: string[]
    correlation_expression?: string
    correlation_value?: unknown
    maximum_messages?: number
    timeout_seconds?: number
  },
): Promise<EventDebugResult> {
  return (
    await apiClient.post<EventDebugResult>(`/event-sources/${sourceId}/websocket/exchange`, input)
  ).data
}

export type ProtocolInputExample = {
  operation: string | null
  variables: Record<string, unknown> | null
  service: string | null
  method: string | null
  call_type: 'unary' | 'server_streaming' | null
  request: Record<string, unknown> | null
}
export type ProtocolStructureEntry = {
  key: string
  label: string
  kind: string
  type_label: string
  required: boolean
  description: string
  expandable: boolean
}
export type ProtocolStructureResponse = {
  artifact_id: string
  project_id: string
  protocol: 'graphql' | 'grpc'
  version: number
  content_sha256: string
  view: {
    node: string
    label: string
    entries: ProtocolStructureEntry[]
    total: number
    offset: number
    limit: number
    example: ProtocolInputExample | null
    notice: string | null
    document: string | null
    document_format: 'text' | 'base64' | null
  }
}
export async function inspectProtocolStructure(
  asset: SchemaArtifact,
  node: string,
  page: number,
): Promise<ProtocolStructureResponse> {
  const result = (
    await apiClient.get<ProtocolStructureResponse>(`/protocol-assets/${asset.id}/structure`, {
      params: {
        project_id: asset.project_id,
        protocol: asset.protocol,
        node,
        offset: (page - 1) * 25,
        limit: 25,
      },
    })
  ).data
  if (
    result.artifact_id !== asset.id ||
    result.project_id !== asset.project_id ||
    result.protocol !== asset.protocol ||
    result.version !== asset.version ||
    result.content_sha256 !== asset.content_sha256 ||
    result.view.node !== node
  )
    throw new Error('契约结构身份与所选版本不一致，请刷新后重试。')
  return result
}

export async function locateGraphQLError(
  asset: SchemaArtifact,
  input: { operation: string; operation_name?: string; path: Array<string | number> },
): Promise<string> {
  const result = (
    await apiClient.post<{
      artifact_id: string
      project_id: string
      version: number
      content_sha256: string
      node: string
    }>(`/graphql/schemas/${asset.id}/locate-error`, { project_id: asset.project_id, ...input })
  ).data
  if (
    result.artifact_id !== asset.id ||
    result.project_id !== asset.project_id ||
    result.version !== asset.version ||
    result.content_sha256 !== asset.content_sha256
  )
    throw new Error('错误定位结果与所选契约版本不一致。')
  return result.node
}
