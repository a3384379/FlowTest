import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App, ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { http, HttpResponse } from 'msw'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { server } from '../../test/server'
import { useReportScope } from './report-scope'
import ReportFilters from './ReportFilters'

const projectId = '00000000-0000-4000-8000-000000000001'
const selectedId = '00000000-0000-4000-8000-000000000021'

function Harness() {
  const state = useReportScope(projectId, true)
  return (
    <>
      <ReportFilters projectId={projectId} state={state} onRefresh={() => {}} />
      <output data-testid="location">{useLocation().search}</output>
    </>
  )
}
function renderFilters() {
  return render(
    <ConfigProvider locale={zhCN} theme={{ token: { motion: false } }}>
      <App>
        <QueryClientProvider
          client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
        >
          <MemoryRouter
            initialEntries={['/?reportFrom=2026-08-01&reportTo=2026-08-09&reportPage=3']}
          >
            <Harness />
          </MemoryRouter>
        </QueryClientProvider>
      </App>
    </ConfigProvider>,
  )
}

describe('report historical resource filters', () => {
  it('paginates and searches the server catalog and resets report pagination only on selection', async () => {
    const requests: URLSearchParams[] = []
    server.use(
      http.get(`/api/v1/projects/${projectId}/reports/filter-options`, ({ request }) => {
        const params = new URL(request.url).searchParams
        requests.push(params)
        const selected =
          params.get('page') === '2' || params.get('search') === '历史' || params.has('selected_id')
        return HttpResponse.json({
          items: selected
            ? [{ id: selectedId, name: '归档历史流程' }]
            : [{ id: projectId, name: '首页流程' }],
          total: params.get('search') ? 1 : 21,
          page: Number(params.get('page')),
          page_size: 20,
        })
      }),
    )
    renderFilters()
    const browser = userEvent.setup()
    await browser.click(screen.getByRole('combobox', { name: '报告流程筛选' }))
    await waitFor(() => expect(screen.getByText('首页流程')).toBeVisible())
    const pagination = screen.getByText('流程共 21 项').closest('ul')!
    await browser.click(within(pagination).getByTitle('下一页'))
    await waitFor(() => expect(screen.getByText('归档历史流程')).toBeVisible())
    expect(requests.at(-1)?.get('page')).toBe('2')
    expect(screen.getByTestId('location').textContent).toContain('reportPage=3')
    fireEvent.change(screen.getByRole('combobox', { name: '报告流程筛选' }), {
      target: { value: '历史' },
    })
    await waitFor(() => expect(requests.at(-1)?.get('search')).toBe('历史'))
    expect(requests.at(-1)?.get('page')).toBe('1')
    await browser.click(screen.getByText('归档历史流程'))
    await waitFor(() =>
      expect(screen.getByTestId('location').textContent).toContain(`reportWorkflow=${selectedId}`),
    )
    expect(screen.getByTestId('location').textContent).not.toContain('reportPage=')
    expect(screen.getByTestId('location').textContent).toContain('reportFrom=2026-08-01')
  })
})
