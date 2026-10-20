import { describe, expect, it } from 'vitest'
import { protocolErrorPaths } from './protocol-error-details'

function failure(errors: unknown) {
  return {
    isAxiosError: true,
    response: { data: { error: { details: { output: { body: { errors } } } } } },
  }
}
describe('existing protocol error paths', () => {
  it('accepts bounded real response paths including list offsets', () => {
    expect(protocolErrorPaths(failure([{ path: ['alias', 0, 'id'], message: 'failed' }]))).toEqual([
      ['alias', 0, 'id'],
    ])
    expect(
      protocolErrorPaths(failure(Array.from({ length: 30 }, () => ({ path: ['item'] })))),
    ).toHaveLength(20)
  })
  it.each(
    [
      [],
      [''],
      [null],
      [true],
      ['item', -1],
      ['item', 1.5],
      ['x'.repeat(513)],
      Array.from({ length: 21 }, () => 'item'),
    ].map((path) => ({ path })),
  )('does not turn malformed path $path into a lookup', ({ path }) => {
    expect(protocolErrorPaths(failure([{ path }]))).toEqual([])
  })
  it.each([
    null,
    new Error('request failed'),
    { isAxiosError: true },
    { isAxiosError: true, response: { data: null } },
    failure('invalid'),
  ])('ignores missing diagnostic data', (value) => {
    expect(protocolErrorPaths(value)).toEqual([])
  })
})
