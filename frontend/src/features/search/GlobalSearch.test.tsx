import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App as AntdApp, ConfigProvider } from 'antd'
import { http, HttpResponse } from 'msw'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { project } from '../../test/fixtures'
import { server } from '../../test/server'
import GlobalSearch from './GlobalSearch'

describe('GlobalSearch', () => {
  it('debounces a query, labels the project, and navigates to the selected asset', async () => {
    let receivedQuery: string | null = null
    const path = `/projects/${project.id}/workflows?focus=workflow:workflow-id`
    server.use(
      http.get('/api/v1/search', ({ request }) => {
        receivedQuery = new URL(request.url).searchParams.get('q')
        return HttpResponse.json({
          items: [
            {
              resource_type: 'workflow',
              resource_id: 'workflow-id',
              project_id: project.id,
              project_name: project.name,
              title: '结算回归流程',
              description: 'Billing regression',
              section: 'workflows',
              path,
              updated_at: '2026-08-13T01:00:00Z',
            },
          ],
          total: 1,
          page: 1,
          page_size: 20,
        })
      }),
    )
    renderSearch()
    const browser = userEvent.setup()

    await browser.click(screen.getByLabelText('全局搜索'))
    await browser.type(screen.getByLabelText('全局搜索'), '结算')
    expect(await screen.findByText('结算回归流程')).toBeVisible()
    expect(screen.getByText(`工作流 · ${project.name}`)).toBeVisible()
    expect(receivedQuery).toBe('结算')
    await browser.click(screen.getByText('结算回归流程'))

    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent(path))
  })

  it('does not query until at least two characters are entered', async () => {
    let requestCount = 0
    server.use(
      http.get('/api/v1/search', () => {
        requestCount += 1
        return HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 })
      }),
    )
    renderSearch()

    const browser = userEvent.setup()
    await browser.click(screen.getByLabelText('全局搜索'))
    await browser.type(screen.getByLabelText('全局搜索'), 'a')
    await waitFor(() =>
      expect(
        screen
          .getAllByText('至少输入 2 个字符')
          .some((item) => item.closest('.ant-select-dropdown:not(.ant-select-dropdown-hidden)')),
      ).toBe(true),
    )
    await new Promise((resolve) => window.setTimeout(resolve, 300))
    expect(requestCount).toBe(0)
  })
})

function LocationProbe() {
  const location = useLocation()
  return <div data-testid="location">{`${location.pathname}${location.search}`}</div>
}

function renderSearch() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <AntdApp>
        <QueryClientProvider client={queryClient}>
          <MemoryRouter>
            <GlobalSearch />
            <LocationProbe />
          </MemoryRouter>
        </QueryClientProvider>
      </AntdApp>
    </ConfigProvider>,
  )
}
