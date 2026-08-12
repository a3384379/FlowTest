import { apiClient, type Page } from '../../lib/api'

export type SchemaArtifact = {
  id: string
  project_id: string
  protocol: 'graphql' | 'grpc'
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
