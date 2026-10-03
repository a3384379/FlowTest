import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it, vi } from 'vitest'

import ProjectTestProvider from '../../test/ProjectTestProvider'
import { project } from '../../test/fixtures'
import { server } from '../../test/server'
import TestPlanTargetSelect from './TestPlanTargetSelect'

describe('test plan target catalog', () => {
  it('reaches published cases after the first hundred and returns their actual frozen version', async () => {
    const asset = {
      id: 'last-case',
      project_id: project.id,
      name: '末页发布用例',
      current_version: 3,
    }
    const pages: number[] = []
    const selected = vi.fn()
    server.use(
      http.get('/api/v1/projects', () =>
        HttpResponse.json({ items: [project], total: 1, page: 1, page_size: 100 }),
      ),
      http.get(`/api/v1/projects/${project.id}/test-cases`, ({ request }) => {
        const params = new URL(request.url).searchParams
        expect(params.get('page_size')).toBe('20')
        const page = Number(params.get('page'))
        pages.push(page)
        return HttpResponse.json({
          items:
            page === 7
              ? [
                  asset,
                  { ...asset, id: 'draft', name: '未发布用例', current_version: null },
                  { ...asset, id: 'foreign', name: '其他项目用例', project_id: 'foreign-project' },
                ]
              : [],
          total: 126,
          page,
          page_size: 20,
        })
      }),
    )
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <ProjectTestProvider section="tasks">
          <TestPlanTargetSelect
            type="case"
            label="计划目标用例"
            known={[]}
            onSelection={selected}
          />
        </ProjectTestProvider>
      </QueryClientProvider>,
    )
    await userEvent.click(screen.getByRole('combobox', { name: '计划目标用例' }))
    await screen.findByText('目录共 126 项；本页只显示已发布资源。')
    await userEvent.click(screen.getByTitle('7'))
    await userEvent.click(
      await screen.findByText('末页发布用例 · v3', { selector: '.ant-select-item-option-content' }),
    )
    await waitFor(() => expect(selected).toHaveBeenCalledWith(asset))
    expect(pages).toContain(7)
    expect(screen.queryByText('未发布用例 · vnull')).not.toBeInTheDocument()
    expect(screen.queryByText('其他项目用例 · v3')).not.toBeInTheDocument()
  })
})
