import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App, ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { http, HttpResponse } from 'msw'
import { useState } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { server } from '../../test/server'
import { project } from '../../test/fixtures'
import TargetResolutionPreview from './TargetResolutionPreview'
import type { TargetPreviewChange, TargetPreviewInput } from './service-target-service'

const endpointId = '00000000-0000-4000-8000-000000004002'
const apiId = '00000000-0000-4000-8000-000000004003'
const context = { id: apiId, name: '预览订单接口' }
const candidate: TargetPreviewChange = {
  kind: 'endpoint',
  endpoint_id: endpointId,
  base_url: 'https://first.example.test',
}
function response(url: string) {
  const resolution = {
    status: 'resolved',
    url,
    service_key: 'orders',
    endpoint_variant: 'default',
    endpoint_revision: 2,
    api_version: 1,
    error: null,
  }
  return {
    before: { ...resolution, url: 'https://before.example.test/health' },
    after: resolution,
    persisted: false,
    network_checked: false,
  }
}
function Harness({ change }: { change: TargetPreviewChange }) {
  const [ready, setReady] = useState(false)
  return (
    <>
      <TargetResolutionPreview
        projectId={project.id}
        environmentId="environment-one"
        initialApi={context}
        change={change}
        onReady={setReady}
      />
      <output data-testid="preview-ready">{String(ready)}</output>
    </>
  )
}
function show(change: TargetPreviewChange) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const tree = (value: TargetPreviewChange) => (
    <ConfigProvider locale={zhCN} theme={{ token: { motion: false } }}>
      <App>
        <QueryClientProvider client={client}>
          <MemoryRouter>
            <Harness change={value} />
          </MemoryRouter>
        </QueryClientProvider>
      </App>
    </ConfigProvider>
  )
  const view = render(tree(change))
  return { ...view, change: (value: TargetPreviewChange) => view.rerender(tree(value)) }
}

describe('read-only request target candidate resolution', () => {
  it('keeps a late response for the previous candidate out of the current review', async () => {
    let release: () => void = () => {}
    let completed = false
    const pending = new Promise<void>((resolve) => {
      release = resolve
    })
    const requests: TargetPreviewInput[] = []
    server.use(
      http.get(`/api/v1/projects/${project.id}/apis`, () =>
        HttpResponse.json({ items: [context], total: 1, page: 1, page_size: 20 }),
      ),
      http.post(`/api/v1/projects/${project.id}/request-targets/preview`, async ({ request }) => {
        const input = (await request.json()) as TargetPreviewInput
        requests.push(input)
        if (
          input.change.kind === 'endpoint' &&
          input.change.base_url === 'https://first.example.test'
        ) {
          await pending
          completed = true
          return HttpResponse.json(response('https://stale-result.example.test/health'))
        }
        return HttpResponse.json(response('https://current-result.example.test/health'))
      }),
    )
    const view = show(candidate)
    await waitFor(() => expect(requests).toHaveLength(1))
    expect(screen.getByTestId('preview-ready')).toHaveTextContent('false')
    view.change({ ...candidate, base_url: 'https://second.example.test' })
    await screen.findByText('https://current-result.example.test/health')
    await waitFor(() => expect(screen.getByTestId('preview-ready')).toHaveTextContent('true'))
    release()
    await waitFor(() => expect(completed).toBe(true))
    expect(screen.queryByText('https://stale-result.example.test/health')).not.toBeInTheDocument()
    expect(requests[1]).toMatchObject({
      environment_id: 'environment-one',
      api_id: apiId,
      change: { base_url: 'https://second.example.test' },
    })
  })

  it('pages and searches preview interfaces and binds explicit version and variant context', async () => {
    const catalog: URLSearchParams[] = []
    const inputs: TargetPreviewInput[] = []
    server.use(
      http.get(`/api/v1/projects/${project.id}/apis`, ({ request }) => {
        const params = new URL(request.url).searchParams
        catalog.push(params)
        return HttpResponse.json({
          items: [params.get('page') === '2' ? { id: 'later-api', name: '后页接口' } : context],
          total: 21,
          page: Number(params.get('page')),
          page_size: 20,
        })
      }),
      http.post(`/api/v1/projects/${project.id}/request-targets/preview`, async ({ request }) => {
        inputs.push((await request.json()) as TargetPreviewInput)
        return HttpResponse.json(response('https://current.example.test/health'))
      }),
    )
    show(candidate)
    const browser = userEvent.setup()
    await screen.findByText('预览接口共 21 项')
    const pagination = screen.getByText('预览接口共 21 项').closest('ul')!
    await browser.click(within(pagination).getByTitle('下一页'))
    await waitFor(() => expect(catalog.at(-1)?.get('page')).toBe('2'))
    await browser.click(screen.getByRole('combobox', { name: '预览接口' }))
    await browser.click(await screen.findByText('后页接口'))
    await waitFor(() => expect(inputs.at(-1)?.api_id).toBe('later-api'))
    fireEvent.change(screen.getByRole('spinbutton', { name: '预览固定接口版本' }), {
      target: { value: '2' },
    })
    fireEvent.change(screen.getByRole('textbox', { name: '预览节点服务覆盖' }), {
      target: { value: 'billing' },
    })
    fireEvent.change(screen.getByRole('textbox', { name: '预览节点地址变体' }), {
      target: { value: 'canary' },
    })
    await waitFor(() =>
      expect(inputs.at(-1)).toMatchObject({
        api_id: 'later-api',
        api_version: 2,
        service_override: 'billing',
        endpoint_variant: 'canary',
      }),
    )
    await browser.click(screen.getByRole('combobox', { name: '预览接口' }))
    fireEvent.change(screen.getByRole('combobox', { name: '预览接口' }), {
      target: { value: '订单' },
    })
    await waitFor(() => expect(catalog.at(-1)?.get('search')).toBe('订单'))
    expect(catalog.at(-1)?.get('page')).toBe('1')
  })
})
