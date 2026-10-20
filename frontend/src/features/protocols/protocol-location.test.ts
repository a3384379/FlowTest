import { describe, expect, it } from 'vitest'
import { parseProtocolLocation } from './protocol-location'

describe('protocol URL scope', () => {
  it.each(['0', '-1', '1.5', '1e2', '', '100001', 'Infinity', ' 2'])(
    'rejects invalid page %j without silently selecting another scope',
    (page) => {
      expect(
        parseProtocolLocation(new URLSearchParams({ mode: 'kafka', kafkaPage: page })).error,
      ).toBe('链接中的协议目录页码无效。')
    },
  )
  it.each(['unknown', '', 'GraphQL'])('rejects invalid mode %j', (mode) => {
    expect(parseProtocolLocation(new URLSearchParams({ mode })).error).toBe(
      '链接中的协议模式无效，请重置协议范围。',
    )
  })
  it('keeps mode-specific asset and page parameters separate', () => {
    const id = '00000000-0000-4000-8000-000000000801'
    expect(
      parseProtocolLocation(
        new URLSearchParams({
          mode: 'grpc',
          graphqlSchema: 'invalid',
          grpcDescriptor: id,
          grpcPage: '2',
        }),
      ),
    ).toEqual({ mode: 'grpc', id, page: 2, schemaId: null, schemaPage: 1, error: null })
  })
  it('rejects invalid identity without falling back', () => {
    expect(parseProtocolLocation(new URLSearchParams({ graphqlSchema: 'absent' })).error).toContain(
      '资产ID无效',
    )
  })
})
