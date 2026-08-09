import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App as AntdApp } from 'antd'
import { http, HttpResponse } from 'msw'
import { describe, expect, it, vi } from 'vitest'

import { project } from '../test/fixtures'
import { server } from '../test/server'
import ProjectTestProvider from '../test/ProjectTestProvider'
import ProjectsPage from './ProjectsPage'

describe('ProjectsPage', () => {
  it('shows the permission matrix, updates network policy and renders audit trace', async () => {
    const saved = vi.fn()
    const savedRetention = vi.fn()
    server.use(
      http.get('/api/v1/projects', () =>
        HttpResponse.json({ items: [project], total: 1, page: 1, page_size: 100 }),
      ),
      http.get(`/api/v1/projects/${project.id}/permissions`, () =>
        HttpResponse.json({
          effective_role: 'owner',
          capabilities: [
            'read',
            'edit',
            'execute',
            'manage_members',
            'manage_security',
            'view_audit',
          ],
          matrix: {
            owner: ['read', 'edit', 'execute', 'manage_members', 'manage_security', 'view_audit'],
            editor: ['read', 'edit', 'execute'],
            viewer: ['read'],
          },
        }),
      ),
      http.get(`/api/v1/projects/${project.id}/security-policy`, () =>
        HttpResponse.json({
          allowed_hosts: ['api.example.com'],
          allowed_private_cidrs: ['10.20.0.0/16'],
        }),
      ),
      http.put(`/api/v1/projects/${project.id}/security-policy`, async ({ request }) => {
        const body = await request.json()
        saved(body)
        return HttpResponse.json(body)
      }),
      http.get(`/api/v1/projects/${project.id}/retention-policy`, () =>
        HttpResponse.json({ retention_days: 90, maximum_days: 3650 }),
      ),
      http.put(`/api/v1/projects/${project.id}/retention-policy`, async ({ request }) => {
        const body = (await request.json()) as { retention_days: number }
        savedRetention(body)
        return HttpResponse.json({ ...body, maximum_days: 3650 })
      }),
      http.get(`/api/v1/projects/${project.id}/audit-logs`, () =>
        HttpResponse.json({
          items: [
            {
              id: 'audit-1',
              actor_user_id: 'user-1',
              project_id: project.id,
              action: 'project.security_policy_updated',
              resource_type: 'project',
              resource_id: project.id,
              details: { trace_id: 'trace-governance' },
              created_at: '2026-08-09T10:00:00Z',
            },
          ],
          total: 1,
          page: 1,
          page_size: 50,
        }),
      ),
    )
    renderPage()
    const browser = userEvent.setup()

    expect(await screen.findByRole('heading', { name: '项目治理' })).toBeVisible()
    expect(await screen.findByText('当前身份：项目 Owner')).toBeVisible()
    expect(await screen.findByText('project.security_policy_updated')).toBeVisible()
    expect(await screen.findByText('trace-governance')).toBeVisible()

    const hosts = await screen.findByLabelText('允许域名（每行一个）')
    await browser.clear(hosts)
    await browser.type(hosts, 'api.example.com{enter}*.internal.example.com')
    await browser.click(screen.getByRole('button', { name: '保存安全策略' }))
    await waitFor(() =>
      expect(saved).toHaveBeenCalledWith({
        allowed_hosts: ['api.example.com', '*.internal.example.com'],
        allowed_private_cidrs: ['10.20.0.0/16'],
      }),
    )
    const retention = await screen.findByRole('spinbutton', { name: '保留天数' })
    await browser.clear(retention)
    await browser.type(retention, '120')
    await browser.click(screen.getByRole('button', { name: '保存保留策略' }))
    await waitFor(() => expect(savedRetention).toHaveBeenCalledWith({ retention_days: 120 }))
  })
})

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <AntdApp>
      <QueryClientProvider client={queryClient}>
        <ProjectTestProvider section="settings">
          <ProjectsPage />
        </ProjectTestProvider>
      </QueryClientProvider>
    </AntdApp>,
  )
}
