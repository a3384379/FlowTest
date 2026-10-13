import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App as AntdApp, ConfigProvider, Form, Input } from 'antd'
import { http, HttpResponse } from 'msw'
import { expect, it, vi } from 'vitest'
import { environment, project } from '../../test/fixtures'
import { server } from '../../test/server'
import EnvironmentEndpoints from './EnvironmentEndpoints'

it('edits a module address without overwriting advanced settings or submitting its parent environment form', async () => {
  let baseUrl = 'http://orders.internal:8080'
  const writes: unknown[] = []
  const outerSubmit = vi.fn()
  const endpoint = {
    id: 'endpoint-orders',
    project_id: project.id,
    environment_id: environment.id,
    service_id: 'orders',
    variant: 'blue',
    base_url: baseUrl,
    enabled: true,
    tls_verify: false,
    connect_timeout_ms: 4321,
    headers: { 'X-Module': 'orders' },
    variables: { module: 'orders' },
    secret_refs: ['synthetic_secret'],
  }
  server.use(
    http.get(`/api/v1/projects/${project.id}/services`, () =>
      HttpResponse.json([{ id: 'orders', name: '订单模块', enabled: true }]),
    ),
    http.get(
      `/api/v1/projects/${project.id}/environments/${environment.id}/service-endpoints`,
      () => HttpResponse.json([{ ...endpoint, base_url: baseUrl }]),
    ),
    http.patch(
      `/api/v1/projects/${project.id}/service-endpoints/${endpoint.id}`,
      async ({ request }) => {
        const input = (await request.json()) as { base_url: string }
        writes.push(input)
        baseUrl = input.base_url
        return HttpResponse.json({ ...endpoint, base_url: baseUrl })
      },
    ),
  )
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <ConfigProvider theme={{ token: { motion: false } }}>
        <AntdApp>
          <Form onFinish={outerSubmit} initialValues={{ base_url: environment.base_url }}>
            <Form.Item name="base_url" label="环境默认地址">
              <Input />
            </Form.Item>
            <EnvironmentEndpoints projectId={project.id} environmentId={environment.id} editable />
          </Form>
        </AntdApp>
      </ConfigProvider>
    </QueryClientProvider>,
  )
  const browser = userEvent.setup()
  await browser.click(await screen.findByRole('button', { name: /编辑/ }))
  expect(screen.getByRole('combobox', { name: '地址所属服务' })).toBeDisabled()
  fireEvent.change(screen.getByLabelText('服务地址'), {
    target: { value: 'http://new-orders.internal:9090' },
  })
  await browser.click(screen.getByRole('button', { name: '保存地址' }))
  await waitFor(() =>
    expect(writes).toEqual([
      { variant: 'blue', base_url: 'http://new-orders.internal:9090', enabled: true },
    ]),
  )
  expect(outerSubmit).not.toHaveBeenCalled()
  expect(await screen.findByText('http://new-orders.internal:9090')).toBeVisible()
})
