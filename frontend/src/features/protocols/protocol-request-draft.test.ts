import { describe, expect, it } from 'vitest'
import { protocolRequestHeaders, type ProtocolHeaderEntry } from './protocol-request-draft'

const row = (name: string, value: string, enabled = true): ProtocolHeaderEntry => ({
  id: name,
  name,
  value,
  enabled,
})

describe('protocol request header contract', () => {
  it('sends only enabled values and keeps explicit authentication separate from advanced entries', () => {
    expect(
      protocolRequestHeaders(
        'graphql',
        [row(' X-Team ', 'team-a'), row('Host', 'ignored', false)],
        'Bearer synthetic-auth',
      ),
    ).toEqual({ 'X-Team': 'team-a', Authorization: 'Bearer synthetic-auth' })
    expect(
      protocolRequestHeaders(
        'grpc',
        [row('X-TEAM', 'team-a'), row('ignored-bin', 'ignored', false)],
        'Bearer synthetic-auth',
      ),
    ).toEqual({ 'x-team': 'team-a', authorization: 'Bearer synthetic-auth' })
  })
  it('rejects ambiguous authentication and case-insensitive duplicate enabled names before transport', () => {
    expect(() =>
      protocolRequestHeaders('graphql', [row('X-Team', 'a'), row('x-team', 'b')], ''),
    ).toThrow()
    expect(() => protocolRequestHeaders('grpc', [row('Authorization', 'a')], 'Bearer b')).toThrow()
    expect(
      protocolRequestHeaders('grpc', [row('Authorization', 'ignored', false)], 'Bearer b'),
    ).toEqual({ authorization: 'Bearer b' })
  })
  it.each(['Host', 'Content-Length', 'Transfer-Encoding', 'Connection', 'not a token', ''])(
    'rejects unsupported GraphQL header name %s',
    (name) => {
      expect(() => protocolRequestHeaders('graphql', [row(name, 'value')], '')).toThrow()
    },
  )
  it.each(['blob-bin', 'bad:key', '', 'not a key'])(
    'rejects unsupported gRPC metadata name %s',
    (name) => {
      expect(() => protocolRequestHeaders('grpc', [row(name, 'value')], '')).toThrow()
    },
  )
  it('enforces the existing text metadata bound and rejects newline injection without changing values', () => {
    expect(
      protocolRequestHeaders('grpc', [row('x-data', 'a'.repeat(8192))], '')['x-data'],
    ).toHaveLength(8192)
    expect(() => protocolRequestHeaders('grpc', [row('x-data', 'a'.repeat(8193))], '')).toThrow()
    expect(() => protocolRequestHeaders('graphql', [row('x-data', 'a\r\nb')], '')).toThrow()
    expect(() => protocolRequestHeaders('graphql', [], 'a\nb')).toThrow()
    expect(protocolRequestHeaders('graphql', [row('x-data', '  keep spaces  ')], '')).toEqual({
      'x-data': '  keep spaces  ',
    })
  })
})
