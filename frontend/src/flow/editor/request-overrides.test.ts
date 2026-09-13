import { describe, expect, it } from 'vitest'
import { applyOwnedRequestSections, extraRequestPolicies } from './request-overrides'
import { jsonEqual } from './editor-types'
describe('request section ownership', () => {
  it('keeps absent, empty, null, and explicit override semantics separate', () => {
    const original = {
      query_parameters: [{ name: 'old', value: '1', enabled: true }],
      headers: { Authorization: 'managed' },
      body: { kind: 'json', value: { old: true } },
      auth_disabled: true,
      suppressed_cookies: ['sid'],
    }
    const next = applyOwnedRequestSections(original, {
      params: { mode: 'custom', value: [] },
      headers: { mode: 'custom', value: {} },
      body: { mode: 'custom', value: { kind: 'json', value: null } },
    })
    expect(next).toMatchObject({
      query_parameters: [],
      headers: {},
      body: { kind: 'json', value: null },
      auth_disabled: true,
    })
    expect(original.body.value).toEqual({ old: true })
    const inherited = applyOwnedRequestSections(next, {
      params: { mode: 'inherit' },
      headers: { mode: 'inherit' },
      body: { mode: 'inherit' },
    })
    expect(inherited).toEqual({ auth_disabled: true, suppressed_cookies: ['sid'] })
    expect(extraRequestPolicies(inherited)).toEqual(['auth_disabled', 'suppressed_cookies'])
    expect(extraRequestPolicies(null)).toEqual([])
    expect(
      applyOwnedRequestSections(undefined, {
        params: { mode: 'inherit' },
        headers: { mode: 'inherit' },
        body: { mode: 'inherit' },
      }),
    ).toEqual({})
  })
  it('compares parent echoes semantically without confusing arrays, nulls, or removed keys', () => {
    expect(jsonEqual({ a: 1, b: undefined }, { a: 1 })).toBe(true)
    expect(jsonEqual([1, 2], { '0': 1, '1': 2 })).toBe(false)
    expect(jsonEqual(null, {})).toBe(false)
    expect(jsonEqual({ a: 1 }, { b: 1 })).toBe(false)
    expect(jsonEqual({ a: 1, b: 2 }, { b: 2, a: 1 })).toBe(true)
  })
})
