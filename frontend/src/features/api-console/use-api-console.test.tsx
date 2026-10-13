import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import { App as AntdApp } from 'antd'
import { http, HttpResponse } from 'msw'
import { expect, it } from 'vitest'
import type { ReactNode } from 'react'
import { useApiConsole } from '../../features/api-console/use-api-console'
import ProjectTestProvider from '../../test/ProjectTestProvider'
import { authenticateTestUser } from '../../test/auth'
import { apiDefinition, environment, project, user } from '../../test/fixtures'
import { server } from '../../test/server'

function harness(section: 'ai' | 'apis' | 'performance') {
  server.use(
    http.get('/api/v1/projects', () =>
      HttpResponse.json({ items: [project], total: 1, page: 1, page_size: 100 }),
    ),
  )
  authenticateTestUser(user)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  function wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>
        <AntdApp>
          <ProjectTestProvider section={section}>{children}</ProjectTestProvider>
        </AntdApp>
      </QueryClientProvider>
    )
  }
  return { client, wrapper }
}

it.each([
  { override: undefined, historicalService: 'old-service', expectedVariant: undefined },
  { override: 'new', historicalService: 'old-service', expectedVariant: 'blue' },
  { override: undefined, historicalService: 'new-service', expectedVariant: 'blue' },
  { override: undefined, historicalService: null, expectedVariant: undefined },
])(
  'scopes a variant to the effective service across version changes ($override, $historicalService)',
  async ({ override, historicalService, expectedVariant }) => {
    const previews: unknown[] = []
    server.use(
      http.get(`/api/v1/projects/${project.id}/apis`, () =>
        HttpResponse.json({ items: [apiDefinition], total: 1, page: 1, page_size: 50 }),
      ),
      http.get(`/api/v1/projects/${project.id}/environments`, () =>
        HttpResponse.json([environment]),
      ),
      http.get(`/api/v1/projects/${project.id}/apis/${apiDefinition.id}/versions`, () =>
        HttpResponse.json([{ version: 2 }, { version: 1 }]),
      ),
      http.get(`/api/v1/projects/${project.id}/apis/${apiDefinition.id}`, ({ request }) => {
        const version = Number(new URL(request.url).searchParams.get('version') ?? '2')
        return HttpResponse.json({
          definition: { ...apiDefinition, current_version: 2 },
          version: {
            id: `api-v${version}`,
            api_definition_id: apiDefinition.id,
            version,
            service_id: version === 2 ? 'new-service' : historicalService,
            method: 'GET',
            path: '/users/me',
            headers: {},
            variables: {},
            query_parameters: [],
            assertions: [],
          },
        })
      }),
      http.get(`/api/v1/projects/${project.id}/services`, () =>
        HttpResponse.json([
          { id: 'new-service', service_key: 'new', enabled: true },
          { id: 'old-service', service_key: 'old', enabled: true },
        ]),
      ),
      http.get(
        `/api/v1/projects/${project.id}/environments/${environment.id}/service-endpoints`,
        () =>
          HttpResponse.json([
            { id: 'new-blue', service_id: 'new-service', variant: 'blue', enabled: true },
            { id: 'old-default', service_id: 'old-service', variant: 'default', enabled: true },
          ]),
      ),
      http.post(
        `/api/v1/projects/${project.id}/apis/${apiDefinition.id}/preview`,
        async ({ request }) => {
          previews.push(await request.json())
          return HttpResponse.json({ url: 'http://synthetic-target/users/me' })
        },
      ),
      http.get(`/api/v1/projects/${project.id}/executions`, () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 }),
      ),
      http.get(`/api/v1/projects/${project.id}/files`, () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 100 }),
      ),
    )
    const { wrapper } = harness('apis')
    const { result } = renderHook(() => useApiConsole(), { wrapper })
    await waitFor(() => expect(result.current.apiDetail.data?.version.version).toBe(2))
    act(() => result.current.setEnvironmentSelection(environment.id))
    await waitFor(() => expect(result.current.environmentId).toBe(environment.id))
    if (override) act(() => result.current.setServiceOverride(override))
    act(() => result.current.setEndpointVariant('blue'))
    await waitFor(() => expect(result.current.targetPreview.data).toBeDefined())
    act(() => result.current.setSelectedVersion(1))
    await waitFor(() =>
      expect(result.current.apiDetail.data?.version.service_id).toBe(historicalService),
    )
    expect(result.current.executionOptions.endpointVariant).toBe(expectedVariant)
    expect(result.current.executionOptions.version).toBe(1)
  },
)

it.each([false, true])(
  'refreshes the address after environment editing, including an in-flight preview (%s)',
  async (delayFirstPreview) => {
    let baseUrl = 'http://old-synthetic-target'
    let previewReads = 0
    let releasePreview!: () => void
    const firstPreview = new Promise<void>((resolve) => {
      releasePreview = resolve
    })
    server.use(
      http.get(`/api/v1/projects/${project.id}/apis`, () =>
        HttpResponse.json({ items: [apiDefinition], total: 1, page: 1, page_size: 50 }),
      ),
      http.get(`/api/v1/projects/${project.id}/environments`, () =>
        HttpResponse.json([{ ...environment, base_url: baseUrl }]),
      ),
      http.patch(
        `/api/v1/projects/${project.id}/environments/${environment.id}`,
        async ({ request }) => {
          const input = (await request.json()) as { base_url: string }
          baseUrl = input.base_url
          return HttpResponse.json({ ...environment, base_url: baseUrl })
        },
      ),
      http.get(`/api/v1/projects/${project.id}/apis/${apiDefinition.id}/versions`, () =>
        HttpResponse.json([{ version: 1 }]),
      ),
      http.get(`/api/v1/projects/${project.id}/apis/${apiDefinition.id}`, () =>
        HttpResponse.json({
          definition: apiDefinition,
          version: {
            id: 'api-v1',
            api_definition_id: apiDefinition.id,
            version: 1,
            method: 'GET',
            path: '/users/me',
            headers: {},
            variables: {},
            query_parameters: [],
            assertions: [],
          },
        }),
      ),
      http.get(`/api/v1/projects/${project.id}/services`, () => HttpResponse.json([])),
      http.get(
        `/api/v1/projects/${project.id}/environments/${environment.id}/service-endpoints`,
        () => HttpResponse.json([]),
      ),
      http.post(`/api/v1/projects/${project.id}/apis/${apiDefinition.id}/preview`, async () => {
        const url = `${baseUrl}/users/me`
        previewReads += 1
        if (previewReads === 1 && delayFirstPreview) await firstPreview
        return HttpResponse.json({ url })
      }),
      http.get(`/api/v1/projects/${project.id}/executions`, () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 }),
      ),
      http.get(`/api/v1/projects/${project.id}/files`, () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 100 }),
      ),
    )
    const { wrapper } = harness('apis')
    const { result } = renderHook(() => useApiConsole(), { wrapper })
    await waitFor(() => expect(result.current.apiDetail.data?.version.version).toBe(1))
    act(() => result.current.setEnvironmentSelection(environment.id))
    await waitFor(() => expect(previewReads).toBeGreaterThan(0))
    if (!delayFirstPreview)
      await waitFor(() =>
        expect(result.current.targetPreview.data?.url).toBe('http://old-synthetic-target/users/me'),
      )
    await act(async () =>
      result.current.editEnvironment(environment.id, { base_url: 'http://new-synthetic-target' }),
    )
    await waitFor(() =>
      expect(result.current.environments.data?.[0].base_url).toBe('http://new-synthetic-target'),
    )
    await waitFor(() =>
      expect(result.current.targetPreview.data?.url).toBe('http://new-synthetic-target/users/me'),
    )
    await act(async () => releasePreview())
    expect(result.current.targetPreview.data?.url).toBe('http://new-synthetic-target/users/me')
  },
)

it('keeps management creation separate and leaves a deleted sending environment invalid', async () => {
  localStorage.clear()
  let catalog = [environment]
  const added = { ...environment, id: 'new-env', name: '新环境' }
  server.use(
    http.get(`/api/v1/projects/${project.id}/apis`, () =>
      HttpResponse.json({ items: [], total: 0, page: 1, page_size: 50 }),
    ),
    http.get(`/api/v1/projects/${project.id}/environments`, () => HttpResponse.json(catalog)),
    http.post(`/api/v1/projects/${project.id}/environments`, () => {
      catalog = [...catalog, added]
      return HttpResponse.json(added, { status: 201 })
    }),
    http.delete(`/api/v1/projects/${project.id}/environments/${environment.id}`, () => {
      catalog = [added]
      return new HttpResponse(null, { status: 204 })
    }),
    http.get(`/api/v1/projects/${project.id}/services`, () => HttpResponse.json([])),
    http.get(
      `/api/v1/projects/${project.id}/environments/${environment.id}/service-endpoints`,
      () => HttpResponse.json([]),
    ),
    http.get(`/api/v1/projects/${project.id}/files`, () =>
      HttpResponse.json({ items: [], total: 0, page: 1, page_size: 100 }),
    ),
  )
  const { wrapper } = harness('apis')
  const { result } = renderHook(() => useApiConsole(), { wrapper })
  await waitFor(() => expect(result.current.environmentId).toBe(environment.id))
  await act(async () => {
    await result.current.addEnvironment(
      { name: added.name, base_url: added.base_url, variables: {}, headers: {} },
      false,
    )
  })
  expect(result.current.environmentId).toBe(environment.id)
  await act(async () => {
    await result.current.archiveEnvironment(environment.id)
  })
  expect(result.current.environmentId).toBeNull()
  expect(result.current.environmentSelectionInvalid).toBe(true)
  expect(result.current.environmentPlaceholder).toBe('原环境已失效，请重新选择')
  localStorage.clear()
})

it('does not auto-select the first environment created inside management', async () => {
  localStorage.clear()
  let created = false
  server.use(
    http.get(`/api/v1/projects/${project.id}/apis`, () =>
      HttpResponse.json({ items: [], total: 0, page: 1, page_size: 50 }),
    ),
    http.get(`/api/v1/projects/${project.id}/environments`, () =>
      HttpResponse.json(created ? [environment] : []),
    ),
    http.post(`/api/v1/projects/${project.id}/environments`, () => {
      created = true
      return HttpResponse.json(environment, { status: 201 })
    }),
    http.get(`/api/v1/projects/${project.id}/services`, () => HttpResponse.json([])),
    http.get(`/api/v1/projects/${project.id}/files`, () =>
      HttpResponse.json({ items: [], total: 0, page: 1, page_size: 100 }),
    ),
  )
  const { wrapper } = harness('apis')
  const { result } = renderHook(() => useApiConsole(), { wrapper })
  await waitFor(() => expect(result.current.environments.data).toEqual([]))
  await act(async () => {
    await result.current.addEnvironment(
      { name: environment.name, base_url: environment.base_url, variables: {}, headers: {} },
      false,
    )
  })
  expect(result.current.environments.data).toEqual([environment])
  expect(result.current.environmentId).toBeNull()
  expect(localStorage.getItem(`flowtest:environment:v1:${user.id}:${project.id}`)).toBe('')
  localStorage.clear()
})

it('upserts a created environment already discovered by a background refresh', async () => {
  localStorage.clear()
  let phase: 'empty' | 'committed' | 'failed' = 'empty'
  let release!: () => void
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  server.use(
    http.get(`/api/v1/projects/${project.id}/apis`, () =>
      HttpResponse.json({ items: [], total: 0, page: 1, page_size: 50 }),
    ),
    http.get(`/api/v1/projects/${project.id}/environments`, () =>
      phase === 'failed'
        ? HttpResponse.json(
            {
              error: {
                code: 'UNAVAILABLE',
                message: '刷新失败',
                trace_id: 'duplicate-environment',
              },
            },
            { status: 503 },
          )
        : HttpResponse.json(phase === 'committed' ? [environment] : []),
    ),
    http.post(`/api/v1/projects/${project.id}/environments`, async () => {
      phase = 'committed'
      await gate
      return HttpResponse.json(environment, { status: 201 })
    }),
    http.get(`/api/v1/projects/${project.id}/services`, () => HttpResponse.json([])),
    http.get(`/api/v1/projects/${project.id}/files`, () =>
      HttpResponse.json({ items: [], total: 0, page: 1, page_size: 100 }),
    ),
  )
  const { client, wrapper } = harness('apis')
  const { result } = renderHook(() => useApiConsole(), { wrapper })
  await waitFor(() => expect(result.current.environments.data).toEqual([]))
  let operation!: Promise<typeof environment>
  act(() => {
    operation = result.current.addEnvironment(
      { name: environment.name, base_url: environment.base_url, variables: {}, headers: {} },
      false,
    )
  })
  await waitFor(() => expect(phase).toBe('committed'))
  await act(async () => {
    await client.invalidateQueries({ queryKey: ['environments', project.id] })
  })
  await waitFor(() => expect(result.current.environments.data).toEqual([environment]))
  phase = 'failed'
  await act(async () => {
    release()
    await operation
  })
  expect(result.current.environments.data).toEqual([environment])
  expect(result.current.environmentId).toBeNull()
  localStorage.clear()
})
