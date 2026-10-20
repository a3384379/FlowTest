import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import QueryFailureNotice from './QueryFailureNotice'

describe('query failure notice', () => {
  it('preserves the standard message and trace and retries only failed reads', () => {
    const retry = vi.fn(async () => undefined)
    const untouched = vi.fn(async () => undefined)
    render(
      <QueryFailureNotice
        queries={[
          { isError: false, error: null, refetch: untouched },
          {
            isError: true,
            error: {
              isAxiosError: true,
              response: {
                data: {
                  error: {
                    code: 'SCHEMA_ARTIFACT_NOT_FOUND',
                    message: '协议版本不存在',
                    trace_id: 'missing-schema-trace',
                  },
                },
              },
            },
            refetch: retry,
          },
        ]}
      />,
    )
    expect(screen.getByText('协议版本不存在')).toBeInTheDocument()
    expect(screen.getByText('Trace ID: missing-schema-trace')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '重试' }))
    expect(retry).toHaveBeenCalledOnce()
    expect(untouched).not.toHaveBeenCalled()
  })
  it('does not invent trace identifiers for local errors or render a successful query', () => {
    const view = render(
      <QueryFailureNotice
        queries={[
          { isError: true, error: new Error('网络不可用'), refetch: async () => undefined },
        ]}
      />,
    )
    expect(screen.getByText('网络不可用')).toBeInTheDocument()
    expect(screen.queryByText(/Trace ID/)).not.toBeInTheDocument()
    view.rerender(<QueryFailureNotice queries={[]} />)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})
