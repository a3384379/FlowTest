import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App as AntdApp } from 'antd'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useAuthStore } from '../auth/auth-store'
import { DraftContext, DraftSession } from '../drafts/draft-session'
import ProjectProvider from '../projects/ProjectProvider'
import { useProjectContext } from '../projects/use-project-context'
import { setOrganizationId } from '../../lib/api'
import { authenticateTestUser } from '../../test/auth'
import { project, user } from '../../test/fixtures'
import { server } from '../../test/server'
import OrganizationScopeProvider from './OrganizationScopeProvider'
import OrganizationSelector from './OrganizationSelector'
import { organizationSelectionKey } from './organization-selection'

const orgA = '00000000-0000-4000-8000-000000000801'
const orgB = '00000000-0000-4000-8000-000000000802'
const organizations = [orgA, orgB].map((id, index) => ({
  id,
  name: `授权组织${index + 1}`,
  slug: `org-${index}`,
  enabled: true,
  role: 'owner',
  description: '',
  member_count: 1,
  created_by_id: user.id,
  created_at: '2026-10-23T00:00:00Z',
  updated_at: '2026-10-23T00:00:00Z',
}))

beforeEach(() => {
  sessionStorage.clear()
  authenticateTestUser(user)
  setOrganizationId(null)
  server.use(
    http.get('/api/v1/organizations', () => HttpResponse.json(organizations)),
    http.get('/api/v1/projects', ({ request }) =>
      HttpResponse.json({
        items: [{ ...project, name: request.headers.get('X-Organization-Id') ?? '账户默认项目' }],
        total: 1,
        page: 1,
        page_size: 20,
      }),
    ),
  )
})

function ProjectProbe() {
  const { projects } = useProjectContext()
  return (
    <>
      <OrganizationSelector />
      <output aria-label="当前组织项目">{projects.data?.items[0]?.name ?? '读取中'}</output>
    </>
  )
}
function renderScope(session = new DraftSession()) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return {
    queryClient,
    ...render(
      <AntdApp>
        <QueryClientProvider client={queryClient}>
          <MemoryRouter>
            <DraftContext.Provider value={session}>
              <OrganizationScopeProvider>
                <ProjectProvider>
                  <ProjectProbe />
                </ProjectProvider>
              </OrganizationScopeProvider>
            </DraftContext.Provider>
          </MemoryRouter>
        </QueryClientProvider>
      </AntdApp>,
    ),
  }
}
async function chooseOrganization(name: string) {
  const browser = userEvent.setup()
  await browser.click(await screen.findByRole('combobox', { name: '全局组织' }))
  await browser.click(
    await screen.findByText(name, { selector: '.ant-select-item-option-content' }),
  )
}

describe('organization scope', () => {
  it('switches actual project requests and clears the previous organization cache', async () => {
    const view = renderScope()
    expect(await screen.findByText('账户默认项目')).toBeVisible()
    view.queryClient.setQueryData(['old-organization-secret'], 'old')
    await chooseOrganization('授权组织2')
    expect(await screen.findByText(orgB)).toBeVisible()
    expect(view.queryClient.getQueryData(['old-organization-secret'])).toBeUndefined()
    expect(sessionStorage.getItem(organizationSelectionKey(user.id))).toBe(orgB)
  })

  it('reauthorizes a saved selection before issuing any project request on reload', async () => {
    sessionStorage.setItem(organizationSelectionKey(user.id), orgA)
    const scopes: Array<string | null> = []
    server.use(
      http.get('/api/v1/projects', ({ request }) => {
        scopes.push(request.headers.get('X-Organization-Id'))
        return HttpResponse.json({
          items: [{ ...project, name: '恢复后的项目' }],
          total: 1,
          page: 1,
          page_size: 20,
        })
      }),
    )
    renderScope()
    expect(await screen.findByText('恢复后的项目')).toBeVisible()
    expect(scopes).toEqual([orgA])
    expect(useAuthStore.getState().organizationId).toBe(orgA)
  })

  it('does not trust a saved organization removed from real membership', async () => {
    sessionStorage.setItem(
      organizationSelectionKey(user.id),
      '00000000-0000-4000-8000-000000000899',
    )
    renderScope()
    expect(await screen.findByText('账户默认项目')).toBeVisible()
    expect(useAuthStore.getState().organizationId).toBeNull()
    expect(screen.getByText(/已保存的组织已不可访问/)).toBeVisible()
  })

  it('does not restore another user selection', async () => {
    sessionStorage.setItem(organizationSelectionKey('different-user'), orgA)
    renderScope()
    expect(await screen.findByText('账户默认项目')).toBeVisible()
    expect(useAuthStore.getState().organizationId).toBeNull()
  })

  it('ignores old organization project responses after switching', async () => {
    let release!: () => void
    let requested = false
    const oldResponse = new Promise<void>((resolve) => {
      release = resolve
    })
    server.use(
      http.get('/api/v1/projects', async ({ request }) => {
        const scope = request.headers.get('X-Organization-Id')
        if (!scope) {
          requested = true
          await oldResponse
        }
        return HttpResponse.json({
          items: [{ ...project, name: scope ? '新组织项目' : '过期项目' }],
          total: 1,
          page: 1,
          page_size: 20,
        })
      }),
    )
    renderScope()
    await waitFor(() => expect(requested).toBe(true))
    await chooseOrganization('授权组织2')
    expect(await screen.findByText('新组织项目')).toBeVisible()
    release()
    await waitFor(() => expect(screen.queryByText('过期项目')).not.toBeInTheDocument())
  })

  it('keeps project data closed while saved organization authorization is unavailable', async () => {
    sessionStorage.setItem(organizationSelectionKey(user.id), orgA)
    const projectsRead = vi.fn()
    server.use(
      http.get('/api/v1/organizations', () =>
        HttpResponse.json(
          {
            error: {
              code: 'TEMPORARILY_UNAVAILABLE',
              message: '组织目录暂不可用',
              trace_id: 'org-unavailable-trace',
            },
          },
          { status: 503 },
        ),
      ),
      http.get('/api/v1/projects', () => {
        projectsRead()
        return HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 })
      }),
    )
    renderScope()
    expect(await screen.findByText(/组织目录暂不可用/)).toBeVisible()
    expect(projectsRead).not.toHaveBeenCalled()
    expect(screen.queryByRole('combobox', { name: '全局组织' })).not.toBeInTheDocument()
    expect(useAuthStore.getState().organizationId).toBeNull()
  })

  it('recovers an inaccessible active organization only through explicit default selection', async () => {
    setOrganizationId(orgA)
    sessionStorage.setItem(organizationSelectionKey(user.id), orgA)
    server.use(
      http.get('/api/v1/organizations', ({ request }) =>
        request.headers.has('X-Organization-Id')
          ? HttpResponse.json(
              {
                error: {
                  code: 'FORBIDDEN',
                  message: '组织访问已撤销',
                  trace_id: 'org-revoked-trace',
                },
              },
              { status: 403 },
            )
          : HttpResponse.json(organizations),
      ),
    )
    renderScope()
    await screen.findByText(/组织访问已撤销/)
    await userEvent.click(screen.getByRole('button', { name: '返回账户默认域' }))
    expect(await screen.findByText('账户默认项目')).toBeVisible()
    expect(useAuthStore.getState().organizationId).toBeNull()
    expect(sessionStorage.getItem(organizationSelectionKey(user.id))).toBe('default')
  })

  it('blocks organization changes while a draft is unsafe', async () => {
    const session = new DraftSession()
    session.markUnsafe('workflow:unsaved', true)
    renderScope(session)
    expect(await screen.findByRole('combobox', { name: '全局组织' })).toBeDisabled()
    fireEvent.mouseDown(screen.getByRole('combobox', { name: '全局组织' }))
    expect(useAuthStore.getState().organizationId).toBeNull()
  })
})
