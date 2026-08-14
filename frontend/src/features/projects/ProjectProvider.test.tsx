import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { delay, http, HttpResponse } from 'msw'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { project } from '../../test/fixtures'
import { server } from '../../test/server'
import ProjectProvider from './ProjectProvider'
import { useProjectContext } from './use-project-context'

describe('ProjectProvider', () => {
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
      <span data-testid="location">{location.pathname}</span>
      <span data-testid="project-options">
        {context.projects.data?.items.map((item) => item.name).join(',')}
      </span>
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
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <ProjectProvider>
          <ContextProbe />
        </ProjectProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}
