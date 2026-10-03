import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { expect, it, vi } from 'vitest'

import { project, workflow } from '../test/fixtures'
import { server } from '../test/server'
import WorkflowResourceSelect from './WorkflowResourceSelect'

it('selects a published workflow outside the initial catalog while preserving its actual version', async () => {
  const pages: number[] = []
  const target = { ...workflow, id: 'last-workflow', name: '目标子流程', current_version: 3 }
  const onChange = vi.fn()
  let writes = 0
  server.use(
    http.get(`/api/v1/projects/${project.id}/workflows`, ({ request }) => {
      const page = Number(new URL(request.url).searchParams.get('page'))
      pages.push(page)
      return HttpResponse.json({
        items:
          page === 7
            ? [
                target,
                { ...workflow, id: 'draft', name: '未发布', current_version: null },
                { ...target, id: 'foreign', project_id: 'another-project', name: '其他项目' },
              ]
            : [],
        total: 126,
        page,
        page_size: 20,
      })
    }),
    http.post('*', () => {
      writes += 1
      return HttpResponse.json({})
    }),
  )
  render(
    <WorkflowResourceSelect
      projectId={project.id}
      workflows={[]}
      disabled={false}
      label="选择子流程"
      onChange={onChange}
    />,
  )
  const browser = userEvent.setup()
  await browser.click(screen.getByRole('combobox', { name: '选择子流程' }))
  await screen.findByText(/目录共 126 项/)
  await browser.click(screen.getByTitle('7'))
  await browser.click(await screen.findByText('目标子流程 · v3'))
  expect(onChange).toHaveBeenCalledWith(target)
  expect(pages).toEqual([1, 7])
  expect(screen.queryByText('未发布')).not.toBeInTheDocument()
  expect(screen.queryByText('其他项目')).not.toBeInTheDocument()
  expect(writes).toBe(0)
})

it('loads the selected off-page workflow by exact ID without changing configuration', async () => {
  const onChange = vi.fn()
  const selected = {
    ...workflow,
    id: 'selected-workflow',
    name: '已绑定子流程',
    current_version: 8,
  }
  server.use(
    http.get(`/api/v1/projects/${project.id}/workflows/${selected.id}`, () =>
      HttpResponse.json(selected),
    ),
  )
  render(
    <WorkflowResourceSelect
      projectId={project.id}
      value={selected.id}
      workflows={[]}
      disabled
      label="选择子流程"
      onChange={onChange}
    />,
  )
  expect(await screen.findByText('已绑定子流程 · v8')).toBeVisible()
  expect(screen.getByRole('combobox', { name: '选择子流程' })).toBeDisabled()
  expect(onChange).not.toHaveBeenCalled()
})

it('shows a retryable directory failure instead of inventing empty resources', async () => {
  let reads = 0
  server.use(
    http.get(`/api/v1/projects/${project.id}/workflows`, () => {
      reads += 1
      return HttpResponse.json(
        { error: { code: 'FAILED', message: '目录读取失败', trace_id: 'test' } },
        { status: 503 },
      )
    }),
  )
  render(
    <WorkflowResourceSelect
      projectId={project.id}
      workflows={[]}
      disabled={false}
      label="选择子流程"
      onChange={vi.fn()}
    />,
  )
  const browser = userEvent.setup()
  await browser.click(screen.getByRole('combobox', { name: '选择子流程' }))
  await screen.findByText('目录读取失败')
  await browser.click(screen.getByRole('button', { name: /重\s*试/ }))
  await waitFor(() => expect(reads).toBe(2))
})
