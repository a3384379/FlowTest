import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App, ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import type { ReactNode } from 'react'
import { server } from '../../test/server'
import type { ServiceContractVersion } from '../contracts/contract-hub-service'
import ServiceContractVersions from './ServiceContractVersions'

const projectId = '00000000-0000-4000-8000-000000000001'
const serviceId = '00000000-0000-4000-8000-000000006001'
const otherId = '00000000-0000-4000-8000-000000006002'
function version(index: number): ServiceContractVersion {
  return {
    id: `00000000-0000-4000-8000-${String(6100 + index).padStart(12, '0')}`,
    kind: 'openapi',
    version: index ? String(index) : null,
    source_name: `固定来源${index}`,
    service_role: 'provider',
    status: index ? 'completed' : 'failed',
    created_at: '2026-10-20T00:00:00Z',
  }
}
function renderVersions() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<ServiceContractVersions projectId={projectId} serviceId={serviceId} />, {
    wrapper: ({ children }: { children: ReactNode }) => (
      <ConfigProvider locale={zhCN} theme={{ token: { motion: false } }}>
        <App>
          <MemoryRouter>
            <QueryClientProvider client={client}>{children}</QueryClientProvider>
          </MemoryRouter>
        </App>
      </ConfigProvider>
    ),
  })
}

describe('service fixed contract versions', () => {
  it('paginates the full service scope, labels Pact consumer versions and resets on service change', async () => {
    const reads: Array<{ id: string; page: number }> = []
    const pact: ServiceContractVersion = {
      ...version(20),
      kind: 'pact',
      version: 'web-42',
      source_name: '消费者固定文档',
      status: 'completed',
    }
    server.use(
      http.get(
        `/api/v1/projects/${projectId}/contract-hub/services/:serviceId/versions`,
        ({ request, params }) => {
          const page = Number(new URL(request.url).searchParams.get('page'))
          reads.push({ id: String(params.serviceId), page })
          const items =
            params.serviceId === otherId
              ? [{ ...version(30), version: 'B-1' }]
              : page === 2
                ? [pact]
                : Array.from({ length: 20 }, (_, index) =>
                    index === 1
                      ? { ...version(index), kind: 'pact' as const, version: null }
                      : version(index),
                  )
          return HttpResponse.json({
            items,
            total: params.serviceId === otherId ? 1 : 21,
            page,
            page_size: 20,
          })
        },
      ),
    )
    const view = renderVersions()
    expect(await screen.findByText('未记录提供方版本')).toBeInTheDocument()
    expect(screen.getByText('导入失败')).toBeInTheDocument()
    expect(screen.getByText('未记录消费者版本')).toBeInTheDocument()
    const pager = screen.getByText('契约版本共 21 项').closest('ul')!
    await userEvent.click(within(pager).getByTitle('下一页'))
    expect(await screen.findByText('消费者版本 web-42')).toBeInTheDocument()
    expect(screen.getByText('提供方')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /展开行|Expand row/ }))
    expect(screen.getByText(pact.id)).toBeInTheDocument()
    expect(reads.at(-1)).toEqual({ id: serviceId, page: 2 })
    view.rerender(<ServiceContractVersions projectId={projectId} serviceId={otherId} />)
    expect(await screen.findByText('提供方版本 B-1')).toBeInTheDocument()
    expect(reads.at(-1)).toEqual({ id: otherId, page: 1 })
    expect(screen.queryByText('消费者版本 web-42')).not.toBeInTheDocument()
  })
  it('distinguishes read failure from an empty catalog and retries the real query', async () => {
    let failed = true
    server.use(
      http.get(`/api/v1/projects/${projectId}/contract-hub/services/${serviceId}/versions`, () =>
        failed
          ? HttpResponse.json(
              {
                error: { code: 'READ_FAILED', message: '版本读取失败', trace_id: 'version-trace' },
              },
              { status: 500 },
            )
          : HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 }),
      ),
    )
    renderVersions()
    expect(await screen.findByText('版本读取失败')).toBeInTheDocument()
    expect(screen.queryByText('当前服务未登记契约版本记录')).not.toBeInTheDocument()
    failed = false
    await userEvent.click(screen.getByRole('button', { name: '重试' }))
    await waitFor(() => expect(screen.getByText('当前服务未登记契约版本记录')).toBeInTheDocument())
    expect(screen.getByText('契约版本共 0 项')).toBeInTheDocument()
  })
})
