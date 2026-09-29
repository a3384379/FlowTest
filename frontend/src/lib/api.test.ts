import { describe, expect, it } from 'vitest'

import { apiClient, apiErrorMessage, shouldSkipAutomaticQueryRetry } from './api'

describe('platform request scope', () => {
  it('rejects absolute and protocol-relative URLs before attaching a platform token', async () => {
    await expect(apiClient.get('//external.example/collect')).rejects.toThrow(
      '平台请求不允许使用外部地址',
    )
    await expect(apiClient.get('HTTPS://external.example/collect')).rejects.toThrow(
      '平台请求不允许使用外部地址',
    )
  })

  it('does not automatically retry a rate-limited platform request', () => {
    expect(shouldSkipAutomaticQueryRetry({ isAxiosError: true, response: { status: 429 } })).toBe(
      true,
    )
  })
})

describe('apiErrorMessage', () => {
  it('uses the structured backend message', () => {
    expect(
      apiErrorMessage({
        isAxiosError: true,
        message: 'Request failed',
        response: { data: { error: { message: '项目不存在' } } },
      }),
    ).toBe('项目不存在')
  })

  it('falls back for ordinary and unknown errors', () => {
    expect(apiErrorMessage({ isAxiosError: true, message: 'request timeout' })).toBe(
      'request timeout',
    )
    expect(apiErrorMessage(new Error('network unavailable'))).toBe('network unavailable')
    expect(apiErrorMessage(null)).toBe('请求失败，请稍后重试')
  })
})
