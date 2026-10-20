import { useSearchParams } from 'react-router-dom'

export type SchemaProtocolMode = 'graphql' | 'grpc'
export type ProtocolMode = SchemaProtocolMode | 'kafka' | 'websocket'
const assetParams = {
  graphql: 'graphqlSchema',
  grpc: 'grpcDescriptor',
  kafka: 'kafkaSource',
  websocket: 'websocketSource',
} as const
const pageParams = {
  graphql: 'graphqlPage',
  grpc: 'grpcPage',
  kafka: 'kafkaPage',
  websocket: 'websocketPage',
} as const
const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

export function parseProtocolLocation(params: URLSearchParams) {
  const requested = params.get('mode') ?? 'graphql'
  const validMode = isProtocolMode(requested)
  const mode = validMode ? requested : 'graphql'
  const id = params.get(assetParams[mode])
  const page = Number(params.get(pageParams[mode]) ?? 1)
  const error = protocolScopeError(validMode, id, page)

  return { mode, id, page: error ? 1 : page, error }
}

function protocolScopeError(validMode: boolean, id: string | null, page: number): string | null {
  if (!validMode) return '链接中的协议模式无效，请重置协议范围。'
  if (id !== null && !uuidPattern.test(id)) return '链接中的协议资产ID无效，不会自动选择其他版本。'
  if (!Number.isSafeInteger(page) || page < 1 || page > 100000) return '链接中的协议目录页码无效。'
  return null
}

function isProtocolMode(mode: string): mode is ProtocolMode {
  return mode === 'graphql' || mode === 'grpc' || mode === 'kafka' || mode === 'websocket'
}

export function useProtocolLocation() {
  const [params, setParams] = useSearchParams()
  const location = parseProtocolLocation(params)
  const { mode } = location
  function selectAsset(id: string, replace = false) {
    const next = new URLSearchParams(params)
    next.set(assetParams[mode], id)
    if (mode === 'kafka') next.delete('kafkaSchemaPage')
    setParams(next, { replace })
  }
  return {
    ...location,
    selectAsset,
    setMode: (value: ProtocolMode) => {
      const next = new URLSearchParams(params)
      next.set('mode', value)
      setParams(next)
    },
    setPage: (page: number) => {
      const next = new URLSearchParams(params)
      next.set(pageParams[mode], String(page))
      setParams(next)
    },
    reset: () => {
      const next = new URLSearchParams(params)
      Object.values(assetParams).forEach((key) => next.delete(key))
      Object.values(pageParams).forEach((key) => next.delete(key))
      next.delete('kafkaSchemaPage')
      next.set('mode', 'graphql')
      setParams(next, { replace: true })
    },
  }
}
