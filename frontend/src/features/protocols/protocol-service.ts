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

export async function listGraphQLSchemas(projectId: string): Promise<Page<SchemaArtifact>> {
  return (
    await apiClient.get<Page<SchemaArtifact>>('/graphql/schemas', {
      params: { project_id: projectId, page: 1, page_size: 100 },
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

export async function listGrpcDescriptors(projectId: string): Promise<Page<SchemaArtifact>> {
  return (
    await apiClient.get<Page<SchemaArtifact>>('/grpc/descriptors', {
      params: { project_id: projectId, page: 1, page_size: 100 },
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
): Promise<Page<EventSource>> {
  return (
    await apiClient.get<Page<EventSource>>('/event-sources', {
      params: { project_id: projectId, kind, page: 1, page_size: 100 },
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
): Promise<Page<SchemaArtifact>> {
  return (
    await apiClient.get<Page<SchemaArtifact>>(`/event-sources/${sourceId}/schemas`, {
      params: { project_id: projectId, page: 1, page_size: 100 },
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
