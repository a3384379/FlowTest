import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App, ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { http, HttpResponse } from 'msw'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { server } from '../../test/server'
import { useAssetCatalogScope } from './asset-catalog-scope'
import AssetCatalogFilters from './AssetCatalogFilters'

const projectId = '00000000-0000-4000-8000-000000000001'
const selectedId = '00000000-0000-4000-8000-000000000021'

function Harness() {
  const state = useAssetCatalogScope()
  return (
    <>
      <AssetCatalogFilters projectId={projectId} state={state} onRefresh={() => {}} />
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
          <MemoryRouter initialEntries={['/?folder=unfiled&focus=case-1&casePage=3&suitePage=2']}>
            <Harness />
          </MemoryRouter>
        </QueryClientProvider>
      </App>
    </ConfigProvider>,
  )
}

describe('asset historical environment filters', () => {
  it('paginates and searches the server catalog and resets asset pagination only on selection', async () => {
    const requests: URLSearchParams[] = []
    server.use(
      http.get(`/api/v1/projects/${projectId}/test-assets/environment-options`, ({ request }) => {
        const params = new URL(request.url).searchParams
        requests.push(params)
        const selected =
          params.get('page') === '2' || params.get('search') === '历史' || params.has('selected_id')
        return HttpResponse.json({
          items: selected
            ? [{ id: selectedId, name: '归档历史环境' }]
            : [{ id: projectId, name: '首页环境' }],
          total: params.get('search') ? 1 : 21,
          page: Number(params.get('page')),
          page_size: 20,
        })
      }),
    )
    renderFilters()
    const browser = userEvent.setup()
    await browser.click(screen.getByRole('combobox', { name: '最近运行环境' }))
    await waitFor(() => expect(screen.getByText('首页环境')).toBeVisible())
    const pagination = screen.getByText('运行环境共 21 项').closest('ul')!
    await browser.click(within(pagination).getByTitle('下一页'))
    await waitFor(() => expect(screen.getByText('归档历史环境')).toBeVisible())
    expect(requests.at(-1)?.get('page')).toBe('2')
    expect(screen.getByTestId('location').textContent).toContain('casePage=3')
    fireEvent.change(screen.getByRole('combobox', { name: '最近运行环境' }), {
      target: { value: '历史' },
    })
    await waitFor(() => expect(requests.at(-1)?.get('search')).toBe('历史'))
    expect(requests.at(-1)?.get('page')).toBe('1')
    await browser.click(screen.getByText('归档历史环境'))
    await waitFor(() =>
      expect(screen.getByTestId('location').textContent).toContain(
        `assetEnvironment=${selectedId}`,
      ),
    )
    expect(screen.getByTestId('location').textContent).not.toContain('casePage=')
    expect(screen.getByTestId('location').textContent).toContain('folder=unfiled')
    expect(screen.getByTestId('location').textContent).toContain('focus=case-1')
    expect(screen.getByTestId('location').textContent).not.toContain('suitePage=')
  })
})
