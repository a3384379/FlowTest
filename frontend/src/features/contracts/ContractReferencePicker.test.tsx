import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App as AntdApp } from 'antd'
import { useState } from 'react'
import { expect, it, vi } from 'vitest'
import { HttpResponse, http } from 'msw'

import { server } from '../../test/server'
import ContractReferencePicker from './ContractReferencePicker'

it('searches and pages independently, retains selected names and fails closed when exact reads fail', async () => {
  const reads: Array<{ page: number; size: number; search: string }> = []
  let unavailable = false
  const ready = vi.fn()
  server.use(
    http.get('/api/v1/projects/project-1/contract-hub/services', ({ request }) => {
      const params = new URL(request.url).searchParams
      const page = Number(params.get('page'))
      const search = params.get('search') ?? ''
      reads.push({ page, search, size: Number(params.get('page_size')) })
      const indices = search
        ? [105]
        : Array.from({ length: page === 1 ? 20 : 1 }, (_, index) => (page - 1) * 20 + index + 1)
      return HttpResponse.json({
        items: indices.map((index) => ({ id: `service-${index}`, display_name: `服务${index}` })),
        total: search ? 1 : 21,
        page,
        page_size: 20,
      })
    }),
    http.get('/api/v1/projects/project-1/contract-hub/services/:id', ({ params }) =>
      unavailable
        ? HttpResponse.json(
            {
              error: {
                code: 'UNAVAILABLE',
                message: '所选提供方暂不可用',
                trace_id: 'provider-read-trace',
              },
            },
            { status: 503 },
          )
        : HttpResponse.json({
            id: params.id,
            display_name: `服务${String(params.id).split('-')[1]}`,
          }),
    ),
  )
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  function ControlledPicker() {
    const [value, setValue] = useState<string | undefined>('service-21')
    return (
      <ContractReferencePicker
        projectId="project-1"
        kind="service"
        label="测试提供方"
        value={value}
        onChange={setValue}
        onReadyChange={ready}
      />
    )
  }
  render(
    <QueryClientProvider client={client}>
      <AntdApp>
        <ControlledPicker />
      </AntdApp>
    </QueryClientProvider>,
  )
  const input = screen.getByRole('combobox', { name: '测试提供方' })
  await waitFor(() => expect(input.closest('.ant-select')).toHaveTextContent('服务21'))
  expect(reads).toEqual([])
  const browser = userEvent.setup()
  await browser.click(input)
  await screen.findByText('服务1', { selector: '.ant-select-item-option-content' })
  const pagination = screen.getByLabelText('测试提供方选项分页')
  fireEvent.click(within(pagination).getByTitle('2'))
  await waitFor(() => expect(reads).toContainEqual({ page: 2, size: 20, search: '' }))
  expect(input.closest('.ant-select')).toHaveTextContent('服务21')
  fireEvent.change(input, { target: { value: '服务105' } })
  await screen.findByText('服务105', { selector: '.ant-select-item-option-content' })
  expect(reads).toContainEqual({ page: 1, size: 20, search: '服务105' })
  expect(input.closest('.ant-select')).toHaveTextContent('服务21')
  await browser.click(screen.getByText('服务105', { selector: '.ant-select-item-option-content' }))
  await waitFor(() => expect(ready).toHaveBeenLastCalledWith(true))
  unavailable = true
  await client.invalidateQueries({
    queryKey: ['contract-reference', 'project-1', 'service', 'service-105'],
  })
  expect(await screen.findByText('所选提供方暂不可用')).toBeVisible()
  expect(screen.getByText('Trace ID: provider-read-trace')).toBeVisible()
  expect(ready).toHaveBeenLastCalledWith(false)
  expect(input.closest('.ant-select')).toHaveTextContent('服务105')
  unavailable = false
  await browser.click(screen.getByRole('button', { name: '重试' }))
  await waitFor(() => expect(ready).toHaveBeenLastCalledWith(true))
})
