import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App } from 'antd'
import { http, HttpResponse } from 'msw'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { apiDefinition, project } from '../../test/fixtures'
import { server } from '../../test/server'
import ProjectAuditPanel from './ProjectAuditPanel'

const record = {
  id: 'audit-51',
  actor_user_id: 'actor-1',
  actor_display_name: '订单组 Owner',
  organization_id: null,
  project_id: project.id,
  action: 'api.updated',
  resource_type: 'api_definition',
  resource_id: apiDefinition.id,
  details: { trace_id: 'audit-trace-51', name: '订单详情接口', changed: ['path'] },
  created_at: '2026-10-21T01:00:00Z',
}

function Location() {
  return <output aria-label="当前链接">{useLocation().search}</output>
}
function renderPanel(search = '', canRead = true) {
  return render(
    <App>
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <MemoryRouter initialEntries={[`/projects/${project.id}/settings${search}`]}>
          <ProjectAuditPanel projectId={project.id} canRead={canRead} />
          <Location />
        </MemoryRouter>
      </QueryClientProvider>
    </App>,
  )
}

describe('ProjectAuditPanel', () => {
  it('loads the 51st record from a durable page/action URL and shows actor and resource details', async () => {
    const read = vi.fn()
    server.use(
      http.get(`/api/v1/projects/${project.id}/audit-logs`, ({ request }) => {
        read(Object.fromEntries(new URL(request.url).searchParams))
        return HttpResponse.json({ items: [record], total: 61, page: 2, page_size: 50 })
      }),
      http.get(`/api/v1/projects/${project.id}/apis/${apiDefinition.id}`, () =>
        HttpResponse.json({ api: apiDefinition }),
      ),
    )
    renderPanel('?auditPage=2&auditAction=api.updated&other=keep')
    expect(await screen.findByText('订单组 Owner')).toBeVisible()
    expect(read).toHaveBeenCalledWith({ page: '2', page_size: '50', action: 'api.updated' })
    expect(screen.getByText('共 61 条')).toBeVisible()
    screen.getByRole('button', { name: '查看详情' }).focus()
    await userEvent.keyboard('{Enter}')
    const drawer = await screen.findByRole('dialog')
    expect(within(drawer).getByText('actor-1')).toBeVisible()
    expect(within(drawer).getByText('audit-trace-51')).toBeVisible()
    expect(within(drawer).getByText(/"changed"/)).toBeVisible()
    expect(await within(drawer).findByRole('link', { name: '定位资源' })).toHaveAttribute(
      'href',
      `/projects/${project.id}/apis?focus=${apiDefinition.id}`,
    )
    await userEvent.click(within(drawer).getByRole('button', { name: 'Close' }))
    await userEvent.click(screen.getByTitle('1'))
    await waitFor(() =>
      expect(read).toHaveBeenLastCalledWith({ page: '1', page_size: '50', action: 'api.updated' }),
    )
    expect(screen.getByLabelText('当前链接')).toHaveTextContent('other=keep')
  })

  it('keeps the failed filter and form input, distinguishes errors from empty results, and retries', async () => {
    let failed = true
    server.use(
      http.get(`/api/v1/projects/${project.id}/audit-logs`, () =>
        failed
          ? HttpResponse.json(
              {
                error: {
                  code: 'UNAVAILABLE',
                  message: '审计读取暂不可用',
                  trace_id: 'audit-failure',
                },
              },
              { status: 503 },
            )
          : HttpResponse.json({ items: [], total: 0, page: 1, page_size: 50 }),
      ),
    )
    renderPanel('?auditAction=workflow.updated&auditPage=2')
    expect(await screen.findByText('审计读取暂不可用')).toBeVisible()
    expect(screen.queryByText('无审计记录')).not.toBeInTheDocument()
    const input = screen.getByLabelText('筛选审计动作')
    await userEvent.clear(input)
    await userEvent.type(input, 'api.updated')
    await userEvent.type(input, '{enter}')
    await waitFor(() => expect(screen.getByLabelText('当前链接')).toHaveTextContent('auditPage=1'))
    expect(screen.getByLabelText('筛选审计动作')).toHaveValue('api.updated')
    failed = false
    await userEvent.click(screen.getByRole('button', { name: '重试' }))
    expect(await screen.findByText('无审计记录')).toBeVisible()
  })

  it('shows legacy missing actor/trace values explicitly and does not invent a resource link', async () => {
    server.use(
      http.get(`/api/v1/projects/${project.id}/audit-logs`, () =>
        HttpResponse.json({
          items: [
            {
              ...record,
              actor_user_id: null,
              actor_display_name: null,
              resource_id: null,
              details: {},
            },
          ],
          total: 1,
          page: 1,
          page_size: 50,
        }),
      ),
    )
    renderPanel()
    await userEvent.click(await screen.findByText('查看详情'))
    const drawer = await screen.findByRole('dialog')
    expect(within(drawer).getAllByText('未提供')).toHaveLength(4)
    expect(within(drawer).queryByRole('link', { name: '定位资源' })).not.toBeInTheDocument()
  })

  it('does not expose a drill-through after the resource authorization read fails', async () => {
    server.use(
      http.get(`/api/v1/projects/${project.id}/audit-logs`, () =>
        HttpResponse.json({ items: [record], total: 1, page: 1, page_size: 50 }),
      ),
      http.get(`/api/v1/projects/${project.id}/apis/${apiDefinition.id}`, () =>
        HttpResponse.json(
          { error: { code: 'FORBIDDEN', message: '无权访问该资源', trace_id: 'resource-denied' } },
          { status: 403 },
        ),
      ),
    )
    renderPanel()
    await userEvent.click(await screen.findByText('查看详情'))
    const drawer = await screen.findByRole('dialog')
    expect(await within(drawer).findByText('无权访问该资源')).toBeVisible()
    expect(within(drawer).queryByRole('link', { name: '定位资源' })).not.toBeInTheDocument()
  })

  it('does not silently fall back to page one for an invalid URL', async () => {
    const read = vi.fn()
    server.use(
      http.get(`/api/v1/projects/${project.id}/audit-logs`, () => {
        read()
        return HttpResponse.json({ items: [], total: 0 })
      }),
    )
    renderPanel('?auditPage=NaN')
    expect(screen.getByText('审计链接中的页码或动作筛选无效，请重新筛选。')).toBeVisible()
    expect(read).not.toHaveBeenCalled()
  })

  it('closes the read-only drawer when navigating to a verified project resource', async () => {
    server.use(
      http.get(`/api/v1/projects/${project.id}/audit-logs`, () =>
        HttpResponse.json({
          items: [{ ...record, resource_type: 'project', resource_id: project.id }],
          total: 1,
          page: 1,
          page_size: 50,
        }),
      ),
    )
    renderPanel('?auditAction=api.updated')
    await userEvent.click(await screen.findByRole('button', { name: '查看详情' }))
    const drawer = await screen.findByRole('dialog')
    await userEvent.click(await within(drawer).findByRole('link', { name: '定位资源' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(screen.getByLabelText('当前链接')).toBeEmptyDOMElement()
  })

  it('does not read or link the resource without the project read capability', async () => {
    const resourceRead = vi.fn()
    server.use(
      http.get(`/api/v1/projects/${project.id}/audit-logs`, () =>
        HttpResponse.json({ items: [record], total: 1, page: 1, page_size: 50 }),
      ),
      http.get(`/api/v1/projects/${project.id}/apis/${apiDefinition.id}`, () => {
        resourceRead()
        return HttpResponse.json({ api: apiDefinition })
      }),
    )
    renderPanel('', false)
    await userEvent.click(await screen.findByRole('button', { name: '查看详情' }))
    expect(await screen.findByRole('dialog')).toBeVisible()
    expect(screen.queryByRole('link', { name: '定位资源' })).not.toBeInTheDocument()
    expect(resourceRead).not.toHaveBeenCalled()
  })
})
