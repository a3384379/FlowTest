import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { executionDetail } from '../../test/fixtures'
import ExecutionResultPanel from './ExecutionResultPanel'

describe('ExecutionResultPanel', () => {
  it('renders the empty state', () => {
    render(<ExecutionResultPanel result={null} history={[]} />)
    expect(screen.getByText('执行接口后查看响应')).toBeVisible()
  })

  it('explains a failed execution and assertion', async () => {
    const failed = {
      execution: {
        ...executionDetail.execution,
        status: 'failed' as const,
        response_status: 500,
        response_body: 'upstream failed',
        error_code: 'UPSTREAM_ERROR',
        error_message: '上游服务返回错误',
      },
      assertions: [
        {
          ...executionDetail.assertions[0],
          passed: false,
          actual: 500,
          message: '状态码期望 200，实际 500',
        },
      ],
    }
    render(<ExecutionResultPanel result={failed} history={[failed.execution]} />)
    const browser = userEvent.setup()

    expect(screen.getByText('上游服务返回错误')).toBeVisible()
    expect(screen.getByText('upstream failed')).toBeVisible()
    await browser.click(screen.getByRole('tab', { name: '断言' }))
    expect(screen.getByText('状态码期望 200，实际 500')).toBeVisible()
    await browser.click(screen.getByRole('tab', { name: '执行历史' }))
    expect(screen.getAllByText('failed').at(-1)).toBeVisible()
  })
})
