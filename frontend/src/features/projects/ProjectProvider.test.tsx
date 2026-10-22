import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { delay, http, HttpResponse } from 'msw'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { project } from '../../test/fixtures'
import { server } from '../../test/server'
import ProjectProvider from './ProjectProvider'
import { useProjectContext } from './use-project-context'

describe('ProjectProvider', () => {
  it('retains a known role during an ordinary stale background refresh', async () => {
    const { queryClient } = renderProvider(`/projects/${project.id}/apis`)
    await waitFor(() => expect(screen.getByTestId('current-role')).toHaveTextContent('owner'))
    expect(screen.getByTestId('project-list-freshness')).toHaveTextContent('stale')
    expect(queryClient.getQueryState(['projects'])?.isInvalidated).toBe(false)
    let release!: () => void
    const pending = new Promise<void>((resolve) => {
      release = resolve
    })
    server.use(
      http.get('/api/v1/projects', async () => {
        await pending
        return HttpResponse.json({ items: [project], total: 1, page: 1, page_size: 100 })
      }),
      http.get(`/api/v1/projects/${project.id}`, async () => {
        await pending
        return HttpResponse.json(project)
      }),
    )
    let refresh!: Promise<void[]>
    try {
      act(() => {
        refresh = Promise.all([
          queryClient.refetchQueries({ queryKey: ['projects'], exact: true }),
          queryClient.refetchQueries({ queryKey: ['project', project.id], exact: true }),
        ])
      })
      await waitFor(() => expect(queryClient.isFetching()).toBe(2))
      expect(screen.getByTestId('current-role')).toHaveTextContent('owner')
      expect(queryClient.getQueryState(['projects'])?.isInvalidated).toBe(false)
      await act(async () => {
        release()
        await refresh
      })
      expect(screen.getByTestId('current-role')).toHaveTextContent('owner')
    } finally {
      release()
      await refresh
    }
  })

  it.each(['/organization', '/platform', '/execution-fabric'])(
    'selects a project from %s without constructing a project-scoped global route',
    async (route) => {
      renderProvider(route)
      await screen.findByText('全部项目')
      await userEvent.setup().click(screen.getByRole('button', { name: '选择项目' }))
      expect(screen.getByTestId('location')).toHaveTextContent(`/projects/${project.id}/dashboard`)
      expect(screen.getByTestId('global-path')).toHaveTextContent('/organization')
    },
  )

  it('preserves the business section when selecting a project', async () => {
    renderProvider('/reports')
    await screen.findByText('全部项目')
    await userEvent.setup().click(screen.getByRole('button', { name: '选择项目' }))
    expect(screen.getByTestId('location')).toHaveTextContent(`/projects/${project.id}/reports`)
  })

  it('selects and clears the project through the URL', async () => {
    const browser = userEvent.setup()
    renderProvider('/dashboard')

    await screen.findByText('全部项目')
    await browser.click(screen.getByRole('button', { name: '选择项目' }))
    expect(await screen.findByTestId('current-project')).toHaveTextContent(project.name)
    expect(screen.getByTestId('location')).toHaveTextContent(`/projects/${project.id}/dashboard`)
    expect(screen.getByTestId('reports-path')).toHaveTextContent(`/projects/${project.id}/reports`)

    await browser.click(screen.getByRole('button', { name: '清除项目' }))
    expect(screen.getByTestId('location')).toHaveTextContent('/dashboard')
  })

  it('switches between accessible projects while preserving the business section', async () => {
    const otherProject = { ...project, id: '00000000-0000-4000-8000-000000000088', name: '项目 B' }
    renderProvider(`/projects/${otherProject.id}/reports`, otherProject)
    await waitFor(() => expect(screen.getByTestId('current-project')).toHaveTextContent('项目 B'))
    await userEvent.setup().click(screen.getByRole('button', { name: '选择项目' }))
    expect(screen.getByTestId('location')).toHaveTextContent(`/projects/${project.id}/reports`)
    expect(screen.getByTestId('current-project')).toHaveTextContent(project.name)
  })

  it('redirects an inaccessible project deep link to the global dashboard', async () => {
    renderProvider('/projects/missing/apis')

    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/dashboard'))
  })

  it('resolves an accessible deep-linked project without waiting for the first project page', async () => {
    const deepLinkedProject = {
      ...project,
      id: '00000000-0000-4000-8000-000000000099',
      name: '第 101 个项目',
    }
    renderProvider(`/projects/${deepLinkedProject.id}/services`, deepLinkedProject, 1_500)

    await waitFor(() =>
      expect(screen.getByTestId('current-project')).toHaveTextContent(deepLinkedProject.name),
    )
    expect(screen.getByTestId('location')).toHaveTextContent(
      `/projects/${deepLinkedProject.id}/services`,
    )
    await waitFor(
      () => expect(screen.getByTestId('project-options')).toHaveTextContent(deepLinkedProject.name),
      { timeout: 2_500 },
    )
    expect(screen.getByTestId('reports-path')).toHaveTextContent(
      `/projects/${deepLinkedProject.id}/reports`,
    )
  })
})

function ContextProbe() {
  const context = useProjectContext()
  const location = useLocation()
  return (
    <>
      <span data-testid="current-project">{context.currentProject?.name ?? '全部项目'}</span>
      <span data-testid="current-role">{context.currentProject?.role ?? 'unknown'}</span>
      <span data-testid="project-list-freshness">
        {context.projects.isStale ? 'stale' : 'fresh'}
      </span>
      <span data-testid="location">{location.pathname}</span>
      <span data-testid="project-options">
        {context.projects.data?.items.map((item) => item.name).join(',')}
      </span>
      <span data-testid="global-path">{context.pathFor('organization')}</span>
      <span data-testid="reports-path">{context.pathFor('reports')}</span>
      <button type="button" onClick={() => context.selectProject(project.id)}>
        选择项目
      </button>
      <button type="button" onClick={() => context.selectProject(null)}>
        清除项目
      </button>
    </>
  )
}

function renderProvider(initialEntry: string, deepLinkedProject = project, projectListDelay = 0) {
  server.use(
    http.get('/api/v1/projects', async () => {
      if (projectListDelay) await delay(projectListDelay)
      return HttpResponse.json({ items: [project], total: 1, page: 1, page_size: 100 })
    }),
    http.get('/api/v1/projects/:projectId', ({ params }) => {
      if (params.projectId === deepLinkedProject.id) return HttpResponse.json(deepLinkedProject)
      return HttpResponse.json(
        { error: { code: 'PROJECT_NOT_FOUND', message: '项目不存在', trace_id: 'test-trace' } },
        { status: 404 },
      )
    }),
  )
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const view = render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <ProjectProvider>
          <ContextProbe />
        </ProjectProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return { ...view, queryClient }
}
