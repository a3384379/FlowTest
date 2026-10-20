import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { ConfigProvider } from 'antd'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'

import type { ApiDefinition, RequestService, ServiceEndpoint, WorkflowDefinition } from '../lib/api'
import { apiDefinition, environment, project, workflowDefinition } from '../test/fixtures'
import { server } from '../test/server'
import WorkflowNodeInspector from './WorkflowNodeInspector'
import { addControlBlock, appendRegionApi } from './editor/control-blocks'

const orderService = requestService('service-orders', 'orders', '订单服务', true)
const authService = requestService('service-auth', 'auth', '认证服务', true)
const legacyService = requestService('service-legacy', 'legacy', '旧版服务', false)

describe('WorkflowNodeInspector request target', () => {
  it('edits a pinned API inside a control region with the same service and request inspector', async () => {
    targetHandlers([
      endpoint('endpoint-auth', authService.id, 'default', 'https://auth.example.com', true),
    ])
    const base = addControlBlock(workflowDefinition, 'group')
    const region = appendRegionApi(base.regions![0], apiDefinition.id, 1)!
    const nested = region.nodes.at(-1)!
    const definition = { ...base, regions: [region] }
    const changed = vi.fn()
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <ConfigProvider theme={{ token: { motion: false } }}>
        <QueryClientProvider client={client}>
          <WorkflowNodeInspector
            node={definition.nodes.at(-1)!}
            definition={definition}
            projectId={project.id}
            environmentId={environment.id}
            apis={[apiDefinition]}
            artifacts={[]}
            credentials={[]}
            editable
            onChange={changed}
            onDelete={vi.fn()}
          />
        </QueryClientProvider>
      </ConfigProvider>,
    )
    await userEvent.click(screen.getByRole('button', { name: '打开区域画布' }))
    const canvas = (await screen.findByText('body 区域画布')).closest<HTMLElement>('.ant-modal')!
    fireEvent.click(within(canvas).getByTestId(`rf__node-${nested.id}`))
    const inspector = within(canvas).getByLabelText('区域节点配置')
    fireEvent.change(within(inspector).getByLabelText('名称'), {
      target: { value: '区域订单请求' },
    })
    await userEvent.click(within(inspector).getByRole('radio', { name: '覆盖 Service' }))
    await userEvent.click(within(inspector).getByRole('combobox', { name: '覆盖 Service' }))
    await userEvent.click(await screen.findByText('认证服务 · auth'))
    await waitFor(() =>
      expect(within(inspector).getByText('最终目标：https://auth.example.com')).toBeVisible(),
    )
    expect(changed).not.toHaveBeenCalled()
    await userEvent.click(within(canvas).getByRole('button', { name: '应用节点配置' }))
    const result = changed.mock.lastCall?.[0] as WorkflowDefinition
    expect(result.nodes).toEqual(definition.nodes)
    expect(result.regions![0].nodes.at(-1)).toMatchObject({
      name: '区域订单请求',
      config: { api_definition_id: apiDefinition.id, api_version: 1, service_override: 'auth' },
    })
  })
  it('selects typed services and endpoint variants without memorizing keys', async () => {
    targetHandlers([
      endpoint('endpoint-orders', orderService.id, 'default', 'https://orders.example.com', true),
      endpoint('endpoint-auth', authService.id, 'default', 'https://auth.example.com', true),
    ])
    renderInspector({ ...apiDefinition, service_id: orderService.id })
    const browser = userEvent.setup()

    expect(await screen.findByText('最终目标：https://orders.example.com')).toBeVisible()
    expect(screen.getByText('订单服务 · orders')).toBeVisible()
    await browser.click(screen.getByRole('radio', { name: '覆盖 Service' }))
    await browser.click(screen.getByRole('combobox', { name: '覆盖 Service' }))
    await browser.click(await screen.findByText('认证服务 · auth'))

    expect(await screen.findByText('Override')).toBeVisible()
    expect(await screen.findByText('最终目标：https://auth.example.com')).toBeVisible()
    expect(
      screen.getByRole('combobox', { name: 'Endpoint Variant' }).closest('.ant-select'),
    ).toHaveTextContent('default')
  })

  it('shows disabled and missing target warnings', async () => {
    targetHandlers([
      endpoint('endpoint-legacy', legacyService.id, 'default', 'https://legacy.example.com', false),
    ])
    const definition = withApiConfig(workflowDefinition, {
      service_override: legacyService.service_key,
      endpoint_variant: 'default',
    })
    renderInspector({ ...apiDefinition, service_id: orderService.id }, definition)

    expect(await screen.findByText('Service 旧版服务 已停用')).toBeVisible()
    expect(screen.getByText('Override')).toBeVisible()
  })
})

function renderInspector(api: ApiDefinition, initial = workflowDefinition) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <InspectorHarness api={api} initial={initial} />
    </QueryClientProvider>,
  )
}

function InspectorHarness({ api, initial }: { api: ApiDefinition; initial: WorkflowDefinition }) {
  const [definition, setDefinition] = useState(initial)
  const node = definition.nodes.find((item) => item.id === 'api') ?? null
  return (
    <WorkflowNodeInspector
      projectId={project.id}
      environmentId={environment.id}
      node={node}
      definition={definition}
      apis={[api]}
      artifacts={[]}
      credentials={[]}
      editable
      onChange={setDefinition}
      onDelete={vi.fn()}
    />
  )
}

function targetHandlers(endpoints: ServiceEndpoint[]) {
  server.use(
    http.get(`/api/v1/projects/${project.id}/services`, () =>
      HttpResponse.json([orderService, authService, legacyService]),
    ),
    http.get(
      `/api/v1/projects/${project.id}/environments/${environment.id}/service-endpoints`,
      () => HttpResponse.json(endpoints),
    ),
  )
}

function requestService(
  id: string,
  serviceKey: string,
  name: string,
  enabled: boolean,
): RequestService {
  return {
    id,
    project_id: project.id,
    service_key: serviceKey,
    name,
    description: '',
    owner_team: null,
    service_type: 'https',
    enabled,
    created_by_id: 'user-1',
    created_at: '2026-08-23T00:00:00Z',
    updated_at: '2026-08-23T00:00:00Z',
  }
}

function endpoint(
  id: string,
  serviceId: string,
  variant: string,
  baseUrl: string,
  enabled: boolean,
): ServiceEndpoint {
  return {
    id,
    project_id: project.id,
    environment_id: environment.id,
    service_id: serviceId,
    variant,
    base_url: baseUrl,
    enabled,
    connect_timeout_ms: 5_000,
    read_timeout_ms: 30_000,
    tls_verify: true,
    proxy_ref: null,
    headers: {},
    variables: {},
    secret_refs: [],
    health_check_path: null,
    health_expected_status: null,
    revision: 1,
    created_by_id: 'user-1',
    created_at: '2026-08-23T00:00:00Z',
    updated_at: '2026-08-23T00:00:00Z',
  }
}

function withApiConfig(
  definition: WorkflowDefinition,
  config: Record<string, unknown>,
): WorkflowDefinition {
  return {
    ...definition,
    nodes: definition.nodes.map((node) =>
      node.id === 'api' ? { ...node, config: { ...node.config, ...config } } : node,
    ),
  }
}

it('EDGE09 requires an explicit incoming edge and updates only that edge', async () => {
  const definition: WorkflowDefinition = {
    ...workflowDefinition,
    nodes: [...workflowDefinition.nodes, { ...workflowDefinition.nodes[1], id: 'other' }],
    edges: [
      ...workflowDefinition.edges,
      { id: 'other-api', source: 'other', target: 'api', condition: null, mappings: [] },
    ],
  }
  const update = vi.fn()
  render(
    <WorkflowNodeInspector
      node={definition.nodes[1]}
      definition={definition}
      apis={[apiDefinition]}
      artifacts={[]}
      credentials={[]}
      editable
      onChange={update}
      onDelete={vi.fn()}
    />,
  )
  const browser = userEvent.setup()
  await browser.click(screen.getByRole('tab', { name: '输入 / 输出' }))
  const add = screen.getByRole('button', { name: 'plus 添加' })
  expect(add).toBeDisabled()
  await browser.click(screen.getByRole('combobox', { name: '选择入站连线' }))
  await browser.click(screen.getByText('other → api', { exact: true }))
  await browser.click(add)
  const changed: WorkflowDefinition = update.mock.calls[0][0]
  expect(changed.edges.find((edge) => edge.id === 'other-api')?.mappings).toHaveLength(1)
  expect(changed.edges.find((edge) => edge.id === 'start-api')?.mappings).toEqual([])
})
