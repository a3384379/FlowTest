import { describe, expect, it } from 'vitest'
import { mapValue, parseEnvironmentMap } from './environment-map'

describe('environment map validation', () => {
  it('preserves empty values and ignores wholly empty new rows', () => {
    expect(
      parseEnvironmentMap(
        {
          format: 'table',
          rows: [
            { name: 'region', value: '' },
            { name: '', value: '' },
          ],
        },
        'variables',
      ),
    ).toEqual({ region: '' })
    expect(parseEnvironmentMap(mapValue({ region: 'cn' }), 'variables')).toEqual({ region: 'cn' })
  })
  it.each([
    { rows: [{ name: '', value: 'orphan' }] },
    {
      rows: [
        { name: 'duplicate', value: 'a' },
        { name: 'duplicate', value: 'b' },
      ],
    },
    { rows: [{ name: '1invalid', value: 'a' }] },
  ])('rejects invalid or duplicate variable names (%s)', ({ rows }) => {
    expect(() => parseEnvironmentMap({ format: 'table', rows }, 'variables')).toThrow()
  })
  it('rejects case insensitive header duplicates and malformed or non-string JSON', () => {
    expect(() =>
      parseEnvironmentMap(mapValue({ 'X-Test': 'a', 'x-test': 'b' }), 'headers'),
    ).toThrow('不能重复')
    for (const text of ['[1]', 'null', '{"count":1}', '{broken'])
      expect(() => parseEnvironmentMap({ format: 'json', text }, 'variables')).toThrow()
  })
})
