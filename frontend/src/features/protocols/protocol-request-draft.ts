export type ProtocolHeaderEntry = { id: string; enabled: boolean; name: string; value: string }
export type GraphQLRequestDraft = {
  mode: 'graphql'
  endpoint: string
  operation: string
  operationName: string
  variables: string
  authorization: string
  headers: ProtocolHeaderEntry[]
  timeoutSeconds: number
}
export type GrpcRequestDraft = {
  mode: 'grpc'
  endpoint: string
  methodKey?: string
  request: string
  tlsMode: 'plaintext' | 'tls' | 'mtls'
  credentialId?: string
  authorization: string
  metadata: ProtocolHeaderEntry[]
  timeoutSeconds: number
}
export type KafkaRequestDraft = { mode: 'kafka'; topic: string; payload: string; schemaId?: string }
export type WebSocketRequestDraft = {
  mode: 'websocket'
  payloadKind: 'json' | 'text'
  payload: string
  correlation: string
}
export type ProtocolRequestDraft =
  GraphQLRequestDraft | GrpcRequestDraft | KafkaRequestDraft | WebSocketRequestDraft

export function protocolRequestHeaders(
  mode: 'graphql' | 'grpc',
  rows: readonly ProtocolHeaderEntry[],
  authorization: string,
): Record<string, string> {
  const values: Record<string, string> = {}
  const names = new Set<string>()
  for (const row of rows.filter((item) => item.enabled)) {
    const name = row.name.trim()
    const normalized = name.toLowerCase()
    validateProtocolHeader(mode, name, row.value)
    if (names.has(normalized)) throw new Error('启用项存在重复的Header或Metadata键')
    names.add(normalized)
    values[mode === 'grpc' ? normalized : name] = row.value
  }
  if (authorization) {
    if (names.has('authorization'))
      throw new Error('Authorization请只在认证输入或高级配置中填写一处')
    validateProtocolHeader(mode, 'authorization', authorization)
    values.Authorization = authorization
    if (mode === 'grpc') {
      delete values.Authorization
      values.authorization = authorization
    }
  }
  return values
}
function validateProtocolHeader(mode: 'graphql' | 'grpc', name: string, value: string) {
  if (/\r|\n/.test(value)) throw new Error('Header或Metadata值不能包含换行')
  if (mode === 'grpc') {
    if (!/^[a-z0-9_.-]+$/i.test(name) || name.toLowerCase().endsWith('-bin') || value.length > 8192)
      throw new Error('gRPC Metadata仅支持文本键值，不支持-bin，单值最多8192字符')
    return
  }
  if (
    !/^[!#$%&'*+.^_`|~a-z0-9-]+$/i.test(name) ||
    ['host', 'content-length', 'transfer-encoding', 'connection'].includes(name.toLowerCase())
  )
    throw new Error('GraphQL Header键无效，不能覆盖Host或连接/长度控制头')
}
