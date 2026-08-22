import { describe, expect, it } from 'vitest'

import {
  parseBulkHeaders,
  parseBulkKeyValues,
  parseBulkParameters,
  serializeBulkHeaders,
  serializeBulkKeyValues,
  serializeBulkParameters,
} from './bulk-edit'

describe('API workbench bulk editing', () => {
  it('round-trips ordered and disabled query parameters', () => {
    const parameters = [
      { enabled: true, name: 'source', value: 's14' },
      { enabled: true, name: 'source', value: 'duplicate' },
      { enabled: false, name: 'callback', value: 'https://example.test/result' },
    ]

    const text = serializeBulkParameters(parameters)
    expect(text).toBe('source: s14\nsource: duplicate\n# callback: https://example.test/result')
    expect(parseBulkParameters(text)).toEqual({ values: parameters, errors: [] })
  })

  it('reports parameter errors with exact line numbers', () => {
    const result = parseBulkParameters('valid: yes\nmissing separator\n: missing-name')

    expect(result.errors).toEqual(['第 2 行：请使用“名称: 值”格式', '第 3 行：名称不能为空'])
  })

  it('masks and restores existing sensitive headers', () => {
    const headers = [
      { name: 'Authorization', value: 'Bearer legacy-token' },
      { name: 'X-Region', value: 'cn' },
    ]

    const text = serializeBulkHeaders(headers)
    expect(text).toContain('Authorization: ******')
    expect(text).not.toContain('legacy-token')
    expect(parseBulkHeaders(text, headers)).toEqual({ values: headers, errors: [] })
  })

  it('rejects duplicate or newly exposed sensitive headers', () => {
    const result = parseBulkHeaders(
      [
        'Content-Type: application/json',
        'content-type: text/plain',
        'Authorization: Bearer literal-token',
      ].join('\n'),
      [],
    )

    expect(result.errors).toEqual([
      '第 2 行：Header 名称与第 1 行重复',
      '第 3 行：敏感 Header 请使用 {{secret.NAME}} 引用',
    ])
  })

  it('round-trips unique form fields and ignores comments', () => {
    const fields = [
      { name: 'username', value: 'demo' },
      { name: 'callback', value: 'https://example.test/result' },
    ]

    expect(parseBulkKeyValues(`# form fields\n${serializeBulkKeyValues(fields)}`)).toEqual({
      values: fields,
      errors: [],
    })
    expect(parseBulkKeyValues('name: one\nname: two').errors).toEqual([
      '第 2 行：名称与第 1 行重复',
    ])
  })
})
