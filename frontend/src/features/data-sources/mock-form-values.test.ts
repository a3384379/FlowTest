import { describe, expect, it } from 'vitest'

import { mockRouteFields, mockRouteInput, readStringMap } from './mock-form-values'

describe('Mock advanced string maps', () => {
  it.each([
    ['{"mode":"full","mode":"short"}', false],
    [String.raw`{"mode":"full","mo\u0064e":"short"}`, false],
    ['{"X-Team":"first","x-team":"second"}', true],
    [String.raw`{"a\"b":"first","a\u0022b":"second"}`, false],
  ])('rejects duplicate decoded keys in %s', (json, header) => {
    expect(() => readStringMap({ mode: 'json', rows: [], json }, header)).toThrow('键名不能重复')
  })

  it('rejects an invalid value even when a later duplicate would replace it', () => {
    expect(() =>
      readStringMap({ mode: 'json', rows: [], json: '{"mode":4,"mode":"full"}' }),
    ).toThrow('键“mode”的值必须是字符串')
  })

  it('preserves escaped values, punctuation, empty strings and safe own property names', () => {
    const expected = {
      mode: 'text with "name": and \\ plus 😀',
      empty: '',
      constructor: 'literal',
      ['__proto__']: 'own value',
    }
    const fields = mockRouteFields(null)
    fields.query_conditions = { mode: 'json', rows: [], json: JSON.stringify(expected) }
    expect(mockRouteInput(fields).query_conditions).toEqual(expected)
    expect(readStringMap({ mode: 'json', rows: [], json: '{ \n }' })).toEqual({})
  })
})
