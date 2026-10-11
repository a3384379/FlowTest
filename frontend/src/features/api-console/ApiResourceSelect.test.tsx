import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import { apiDefinition, project } from '../../test/fixtures'
import { server } from '../../test/server'
import ApiResourceSelect from './ApiResourceSelect'

function Picker() {
  const [value, setValue] = useState<string>()
  return (
    <ApiResourceSelect
      label="测试接口来源"
      projectId={project.id}
      value={value}
      onChange={setValue}
    />
  )
}

it('reaches later pages, retains the selected resource, and resets pages for a search', async () => {
  const requests: Array<{ page: string | null; search: string | null }> = []
  server.use(
    http.get(`/api/v1/projects/${project.id}/apis`, ({ request }) => {
      const params = new URL(request.url).searchParams
      requests.push({ page: params.get('page'), search: params.get('search') })
      const second = params.get('page') === '2'
      const name = params.get('search') ? '搜索结果接口' : second ? '第二页接口' : '第一页接口'
      return HttpResponse.json({
        items: [{ ...apiDefinition, id: second ? 'second-api' : apiDefinition.id, name }],
        total: 25,
        page: Number(params.get('page')),
        page_size: 20,
      })
    }),
  )
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <Picker />
    </QueryClientProvider>,
  )
  const browser = userEvent.setup()
  await browser.click(screen.getByLabelText('测试接口来源'))
  await screen.findByText(/第一页接口/, { selector: '.ant-select-item-option-content' })
  await browser.click(screen.getByTitle('2'))
  await browser.click(
    await screen.findByText(/第二页接口/, { selector: '.ant-select-item-option-content' }),
  )
  expect(screen.getByText(/第二页接口/, { selector: '.ant-select-content' })).toBeVisible()
  await browser.click(screen.getByLabelText('测试接口来源'))
  await browser.type(screen.getByLabelText('测试接口来源'), '搜索')
  await screen.findByText(/搜索结果接口/, { selector: '.ant-select-item-option-content' })
  await waitFor(() => expect(requests.at(-1)).toEqual({ page: '1', search: '搜索' }))
  expect(screen.getByText(/第二页接口/, { selector: '.ant-select-content' })).toBeVisible()
})

describe('catalog scope', () => {
  it('does not query a disabled picker', async () => {
    let reads = 0
    server.use(
      http.get(`/api/v1/projects/${project.id}/apis`, () => {
        reads += 1
        return HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 })
      }),
    )
    const client = new QueryClient()
    render(
      <QueryClientProvider client={client}>
        <ApiResourceSelect label="只读接口" projectId={project.id} disabled />
      </QueryClientProvider>,
    )
    expect(screen.getByLabelText('只读接口')).toBeDisabled()
    expect(reads).toBe(0)
  })
})
