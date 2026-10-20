import { act, renderHook } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { GraphQLRequestDraft } from './protocol-request-draft'
import { useProtocolRequestDraft } from './use-protocol-request-draft'

const initial: GraphQLRequestDraft = {
  mode: 'graphql',
  endpoint: 'https://example.test/graphql',
  operation: 'query { id }',
  operationName: '',
  variables: '{}',
  authorization: '',
  headers: [],
  timeoutSeconds: 30,
}

describe('protocol request session updates', () => {
  it('preserves every field and row across batched callbacks and does not resurrect values after reset', () => {
    const { result } = renderHook(() =>
      useProtocolRequestDraft('project:graphql:schema:v1:hash', initial),
    )
    const change = result.current.patch
    act(() => {
      change({ operationName: 'BatchedOperation' })
      change({ variables: '{"id":"007"}' })
      change((current) => ({
        headers: [...current.headers, { id: 'one', name: 'X-One', value: '1', enabled: true }],
      }))
      change((current) => ({
        headers: [...current.headers, { id: 'two', name: 'X-Two', value: '2', enabled: false }],
      }))
    })
    expect(result.current.draft).toMatchObject({
      operationName: 'BatchedOperation',
      variables: '{"id":"007"}',
    })
    expect(result.current.draft.headers.map((item) => item.id)).toEqual(['one', 'two'])
    act(() => result.current.reset())
    act(() => change({ variables: '{"id":"after-reset"}' }))
    expect(result.current.draft).toEqual({ ...initial, variables: '{"id":"after-reset"}' })
  })
})
