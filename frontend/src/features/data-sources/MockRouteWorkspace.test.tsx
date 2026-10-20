import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App } from 'antd'
import { http, HttpResponse } from 'msw'
import { describe, expect, it, vi } from 'vitest'

import type { MockRoute, MockService } from '../../lib/api'
import { project, user } from '../../test/fixtures'
import { server } from '../../test/server'
import MockRouteWorkspace from './MockRouteWorkspace'

const service: MockService = {
  id: 'mock-maintenance-1',
  project_id: project.id,
  name: '订单 Mock',
  slug: 'mock-maintenance',
  description: '',
  is_enabled: true,
  created_by_id: user.id,
  created_at: '2026-10-21T01:00:00Z',
  updated_at: '2026-10-21T01:00:00Z',
}
const initial: MockRoute = {
  id: 'mock-route-existing',
  mock_service_id: service.id,
  name: '查询订单',
  method: 'GET',
  path_pattern: '/orders/{id}',
  query_conditions: {},
  header_conditions: {},
  response_status: 200,
  response_headers: {},
  response_body: { id: '{{path.id}}' },
  delay_ms: 0,
  scenario: null,
  priority: 10,
  is_enabled: true,
  created_by_id: user.id,
  created_at: service.created_at,
  updated_at: service.updated_at,
}

function renderWorkspace(canEdit = true) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const wrap = (selected: MockService) => (
    <App>
      <QueryClientProvider client={client}>
        <MockRouteWorkspace projectId={project.id} service={selected} canEdit={canEdit} />
      </QueryClientProvider>
    </App>
  )
  const rendered = render(wrap(service))
  return { ...rendered, switchService: (next: MockService) => rendered.rerender(wrap(next)) }
}

function readHandlers(read: () => MockRoute[] = () => [initial]) {
  server.use(
    http.get(`/api/v1/projects/${project.id}/mock-services/:serviceId/routes`, () =>
      HttpResponse.json(read()),
    ),
    http.get(`/api/v1/projects/${project.id}/mock-services/:serviceId/request-logs`, () =>
      HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 }),
    ),
  )
}

describe('MockRouteWorkspace maintenance', () => {
  it('edits the same route ID and toggles only subsequent matching without recreating it', async () => {
    let route = initial
    const updated = vi.fn()
    const created = vi.fn()
    readHandlers(() => [route])
    server.use(
      http.put(
        `/api/v1/projects/${project.id}/mock-services/${service.id}/routes/${initial.id}`,
        async ({ request }) => {
          const body = (await request.json()) as Partial<MockRoute>
          updated(body)
          route = { ...route, ...body }
          return HttpResponse.json(route)
        },
      ),
      http.post(`/api/v1/projects/${project.id}/mock-services/${service.id}/routes`, () => {
        created()
        return HttpResponse.json(initial)
      }),
    )
    renderWorkspace()
    await userEvent.click(await screen.findByRole('button', { name: '编辑 Mock 路由：查询订单' }))
    const name = screen.getByLabelText('名称')
    fireEvent.change(name, { target: { value: '已修改订单规则' } })
    fireEvent.change(screen.getByLabelText('优先级'), { target: { value: '45' } })
    fireEvent.change(screen.getByLabelText('响应模板（JSON）'), {
      target: { value: '{"changed":true}' },
    })
    await userEvent.click(screen.getByRole('button', { name: '保存路由' }))
    await waitFor(() =>
      expect(updated).toHaveBeenCalledWith(
        expect.objectContaining({
          name: '已修改订单规则',
          priority: 45,
          response_body: { changed: true },
          is_enabled: true,
        }),
      ),
    )
    await screen.findByRole('button', { name: '编辑 Mock 路由：已修改订单规则' })
    await userEvent.click(screen.getByRole('switch', { name: '启用规则：已修改订单规则' }))
    await waitFor(() =>
      expect(updated).toHaveBeenLastCalledWith(
        expect.objectContaining({ name: '已修改订单规则', priority: 45, is_enabled: false }),
      ),
    )
    await waitFor(() =>
      expect(screen.getByRole('switch', { name: '启用规则：已修改订单规则' })).not.toBeChecked(),
    )
    expect(created).not.toHaveBeenCalled()
    expect(screen.getByText('启停仅影响后续请求匹配')).toBeInTheDocument()
  })

  it('keeps failed edits and scopes the editor to the selected service', async () => {
    readHandlers()
    server.use(
      http.put(
        `/api/v1/projects/${project.id}/mock-services/${service.id}/routes/${initial.id}`,
        () =>
          HttpResponse.json(
            {
              error: { code: 'UNAVAILABLE', message: '规则保存失败', trace_id: 'mock-save-failed' },
            },
            { status: 503 },
          ),
      ),
    )
    const rendered = renderWorkspace()
    await userEvent.click(await screen.findByRole('button', { name: '编辑 Mock 路由：查询订单' }))
    fireEvent.change(screen.getByLabelText('名称'), { target: { value: '保留未保存规则' } })
    await userEvent.click(screen.getByRole('button', { name: '保存路由' }))
    expect(await screen.findByText(/规则保存失败/)).toBeInTheDocument()
    expect(screen.getByLabelText('名称')).toHaveValue('保留未保存规则')
    rendered.switchService({ ...service, id: 'mock-maintenance-2', name: '另一个服务' })
    await waitFor(() => expect(screen.getByLabelText('名称')).not.toHaveValue('保留未保存规则'))
  })

  it('lets a viewer inspect existing rules while keeping all writes disabled', async () => {
    readHandlers()
    renderWorkspace(false)
    await userEvent.click(await screen.findByRole('button', { name: '查看 Mock 路由：查询订单' }))
    expect(screen.getByLabelText('名称')).toHaveValue('查询订单')
    expect(screen.getByLabelText('名称')).toBeDisabled()
    expect(screen.queryByRole('button', { name: '保存路由' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '删除 Mock 路由' })).not.toBeInTheDocument()
    expect(screen.getByRole('switch', { name: '启用规则：查询订单' })).toBeDisabled()
  })
})
