import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { WorkflowResourceLink, WorkflowResourceReturn } from './WorkflowResourceNavigation'

describe('workflow prerequisite navigation', () => {
  it('carries the precise workflow route and invalidates only its project resources on return', () => {
    const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } })
    client.setQueryData(['credentials', 'one'], [])
    client.setQueryData(['credentials', 'two'], [])
    client.setQueryData(['reports', 'one'], [])
    const original =
      '/projects/one/workflows?focus=flow&execution=run&node=loop&control_kind=iteration&control_ordinal=2&instance=__nested_request__%3A2&instance_attempt=3'
    const view = render(
      <MemoryRouter initialEntries={[original]}>
        <WorkflowResourceLink
          projectId="one"
          to="/projects/one/data?tab=credentials"
          label="配置数据库凭据"
        />
      </MemoryRouter>,
    )
    const link = screen.getByRole('link', { name: '配置数据库凭据' })
    const target = new URL(link.getAttribute('href')!, window.location.origin)
    expect(target.pathname).toBe('/projects/one/data')
    expect(target.searchParams.get('return_to')).toBe(original)
    view.unmount()
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[target.pathname + target.search]}>
          <WorkflowResourceReturn projectId="one" />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    const back = screen.getByRole('link', { name: '返回流程编排' })
    expect(back).toHaveAttribute('href', original)
    fireEvent.click(back)
    expect(client.getQueryState(['credentials', 'one'])?.isInvalidated).toBe(true)
    expect(client.getQueryState(['credentials', 'two'])?.isInvalidated).toBe(false)
    expect(client.getQueryState(['reports', 'one'])?.isInvalidated).toBe(false)
  })

  it.each([
    'https://example.com/projects/one/workflows',
    '//example.com/projects/one/workflows',
    '/projects/two/workflows?focus=foreign',
    '/projects/one/data',
    '/projects/one/workflows\\../data',
  ])('rejects a return target outside the same workflow context: %s', (target) => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter
          initialEntries={['/projects/one/data?return_to=' + encodeURIComponent(target)]}
        >
          <WorkflowResourceReturn projectId="one" />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    expect(screen.queryByRole('link', { name: '返回流程编排' })).not.toBeInTheDocument()
  })
})
