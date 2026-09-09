import { AxiosError } from 'axios'
import { afterEach, expect, it, vi } from 'vitest'

import { apiClient } from '../../lib/api'
import { exportApis } from './api-service'

afterEach(() => vi.restoreAllMocks())

it.each([
  [
    'har',
    `attachment; filename="fallback.har"; filename*=UTF-8''1.22%E5%8F%91%E7%A5%A8.har`,
    '1.22发票.har',
  ],
  ['curl', '', 'flowtest.curl.txt'],
  ['excel', '', 'flowtest.xlsx'],
  ['bruno', '', 'flowtest.bruno.json'],
  ['har', `attachment; filename="fallback.har"; filename*=UTF-8''%broken`, 'fallback.har'],
] as const)('downloads %s with a usable filename', async (format, disposition, expected) => {
  vi.spyOn(apiClient, 'get').mockResolvedValue({
    data: new Blob(['content']),
    headers: { 'content-disposition': disposition },
  })
  Object.defineProperty(URL, 'createObjectURL', {
    configurable: true,
    value: vi.fn(() => 'blob:export'),
  })
  Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() })
  let filename = ''
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
    this: HTMLAnchorElement,
  ) {
    filename = this.download
  })
  await exportApis('project', format)
  expect(filename).toBe(expected)
})

it('decodes a JSON error Blob and never downloads a failed export', async () => {
  const data = new Blob()
  Object.defineProperty(data, 'text', {
    value: async () =>
      JSON.stringify({
        error: {
          code: 'EXPORT_LIMIT_EXCEEDED',
          message: '接口数量超过导出上限',
          trace_id: 'trace-export',
        },
      }),
  })
  const error = new AxiosError('Request failed')
  Object.assign(error, { response: { data, status: 422 } })
  vi.spyOn(apiClient, 'get').mockRejectedValue(error)
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
  await expect(exportApis('project', 'excel')).rejects.toThrow('EXPORT_LIMIT_EXCEEDED')
  await expect(exportApis('project', 'excel')).rejects.toThrow('trace-export')
  expect(click).not.toHaveBeenCalled()
})
