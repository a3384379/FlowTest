import { describe, expect, it } from 'vitest'

import { apiErrorMessage } from './api'

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
