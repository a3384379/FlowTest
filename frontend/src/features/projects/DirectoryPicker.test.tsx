import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App } from 'antd'
import { useState } from 'react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it, vi } from 'vitest'

import { project } from '../../test/fixtures'
import { server } from '../../test/server'
import DirectoryPicker from './DirectoryPicker'

const selected = {
  id: '00000000-0000-4000-8000-000000000106',
  display_name: '分页末尾成员',
  email: 'last@example.com',
  is_active: true,
}
const endpoint = `/api/v1/projects/${project.id}/member-candidates/search`
function ControlledPicker() {
  const [value, setValue] = useState<string>()
  return (
    <>
      <DirectoryPicker
        source={{ kind: 'project-user', projectId: project.id }}
        label="候选用户"
        value={value}
        onChange={setValue}
      />
      <output aria-label="选中身份">{value}</output>
    </>
  )
}
function renderPicker() {
  return render(
    <App>
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <ControlledPicker />
      </QueryClientProvider>
    </App>,
  )
}

describe('DirectoryPicker', () => {
  it('reaches the sixth directory page and retains the selected identity while searching another page', async () => {
    const searched = vi.fn()
    server.use(
      http.post(endpoint, async ({ request }) => {
        const input = (await request.json()) as { page: number; query: string }
        searched(input)
        return HttpResponse.json({
          items: input.page === 6 ? [selected] : [],
          total: 106,
          page: input.page,
          page_size: 20,
        })
      }),
    )
    renderPicker()
    await userEvent.click(screen.getByRole('combobox', { name: '候选用户' }))
    await screen.findByText('共 106 条')
    await userEvent.click(screen.getByTitle('6'))
    await userEvent.click(await screen.findByText('分页末尾成员 (last@example.com)'))
    expect(screen.getByLabelText('选中身份')).toHaveTextContent(selected.id)
    expect(searched).toHaveBeenCalledWith({ query: '', page: 6, page_size: 20 })
    await userEvent.type(screen.getByRole('combobox', { name: '候选用户' }), '另一个人')
    await waitFor(() =>
      expect(searched).toHaveBeenCalledWith({ query: '另一个人', page: 1, page_size: 20 }),
    )
    expect(screen.getByLabelText('选中身份')).toHaveTextContent(selected.id)
    expect(screen.getAllByText('分页末尾成员 (last@example.com)').length).toBeGreaterThan(0)
  })

  it('keeps the search text during failure and retries the same query without presenting it as empty', async () => {
    let failed = true
    const searched = vi.fn()
    server.use(
      http.post(endpoint, async ({ request }) => {
        searched(await request.json())
        return failed
          ? HttpResponse.json(
              {
                error: {
                  code: 'UNAVAILABLE',
                  message: '身份目录暂不可用',
                  trace_id: 'directory-retry',
                },
              },
              { status: 503 },
            )
          : HttpResponse.json({ items: [selected], total: 1, page: 1, page_size: 20 })
      }),
    )
    renderPicker()
    const input = screen.getByRole('combobox', { name: '候选用户' })
    await userEvent.type(input, 'last@example.com')
    expect(await screen.findByText('身份目录暂不可用')).toBeInTheDocument()
    expect(input).toHaveValue('last@example.com')
    expect(screen.queryByText('没有匹配的可授权对象')).not.toBeInTheDocument()
    failed = false
    await userEvent.click(screen.getByRole('button', { name: '重试' }))
    await screen.findByText('分页末尾成员 (last@example.com)')
    expect(searched).toHaveBeenLastCalledWith({ query: 'last@example.com', page: 1, page_size: 20 })
  })

  it('does not replace current results when a previous search completes late', async () => {
    let release: (() => void) | undefined
    server.use(
      http.post(endpoint, async ({ request }) => {
        const { query } = (await request.json()) as { query: string }
        if (query === 'old')
          await new Promise<void>((resolve) => {
            release = resolve
          })
        return HttpResponse.json({
          items: query
            ? [{ ...selected, display_name: query === 'old' ? '旧搜索结果' : '新搜索结果' }]
            : [],
          total: query ? 1 : 0,
          page: 1,
          page_size: 20,
        })
      }),
    )
    renderPicker()
    const input = screen.getByRole('combobox', { name: '候选用户' })
    await userEvent.type(input, 'old')
    await waitFor(() => expect(release).toBeDefined())
    await userEvent.clear(input)
    await userEvent.type(input, 'new')
    await screen.findByText('新搜索结果 (last@example.com)')
    await act(async () => release?.())
    expect(screen.queryByText('旧搜索结果 (last@example.com)')).not.toBeInTheDocument()
    expect(screen.getByText('新搜索结果 (last@example.com)')).toBeInTheDocument()
  })
})
