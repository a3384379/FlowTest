import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App as AntdApp, message as staticMessage } from 'antd'
import { HttpResponse, http } from 'msw'
import { describe, expect, it } from 'vitest'
import { useLocation, useNavigate } from 'react-router-dom'

import type { EventSource, SchemaArtifact } from '../features/protocols/protocol-service'
import type { Credential } from '../lib/api'
import { project, user } from '../test/fixtures'
import ProjectTestProvider from '../test/ProjectTestProvider'
import { server } from '../test/server'
import ProtocolWorkbenchPage from './ProtocolWorkbenchPage'

const graphqlSchema: SchemaArtifact = {
  id: '00000000-0000-4000-8000-000000000801',
  project_id: project.id,
  protocol: 'graphql',
  name: '用户 GraphQL',
  description: '',
  version: 2,
  source_format: 'graphql_sdl',
  content_sha256: 'a'.repeat(64),
  summary: { type_count: 6, field_count: 4 },
  created_by_id: user.id,
  created_at: '2026-08-12T00:00:00Z',
  updated_at: '2026-08-12T00:00:00Z',
}

const grpcDescriptor: SchemaArtifact = {
  ...graphqlSchema,
  id: '00000000-0000-4000-8000-000000000802',
  protocol: 'grpc',
  name: '用户 gRPC',
  version: 1,
  source_format: 'proto_source',
  content_sha256: 'b'.repeat(64),
  summary: {
    service_count: 1,
    services: [
      {
        name: 'flowtest.user.v1.UserService',
        methods: [
          { name: 'GetUser', call_type: 'unary' },
          { name: 'WatchUsers', call_type: 'server_streaming' },
        ],
      },
    ],
  },
}

const kafkaSource: EventSource = {
  id: '00000000-0000-4000-8000-000000000805',
  project_id: project.id,
  kind: 'kafka',
  name: '订单 Kafka',
  description: '',
  version: 1,
  endpoints: ['redpanda:9092'],
  schema_registry_url: 'http://redpanda:8081',
  config_sha256: 'c'.repeat(64),
  created_by_id: user.id,
  created_at: '2026-08-12T00:00:00Z',
  updated_at: '2026-08-12T00:00:00Z',
}

const websocketSource: EventSource = {
  ...kafkaSource,
  id: '00000000-0000-4000-8000-000000000806',
  kind: 'websocket',
  name: '订单 WebSocket',
  endpoints: ['ws://mock-target:8080/ws/echo'],
  schema_registry_url: null,
  config_sha256: 'd'.repeat(64),
}

describe('ProtocolWorkbenchPage', () => {
  it('restores an off-page immutable schema from the link without changing selection on pagination', async () => {
    installHandlers()
    const selected = {
      ...graphqlSchema,
      id: '00000000-0000-4000-8000-000000000812',
      name: '页外固定GraphQL',
      version: 3,
    }
    const pages: string[] = []
    server.use(
      http.get('/api/v1/graphql/schemas', ({ request }) => {
        const page = new URL(request.url).searchParams.get('page') ?? '1'
        pages.push(page)
        return HttpResponse.json({
          items: [graphqlSchema],
          total: 60,
          page: Number(page),
          page_size: 20,
        })
      }),
      http.get(`/api/v1/graphql/schemas/${selected.id}`, () => HttpResponse.json(selected)),
    )
    renderPage(`?mode=graphql&graphqlSchema=${selected.id}&graphqlPage=2`)
    expect(await screen.findByText('页外固定GraphQL · v3')).toBeVisible()
    const pager = screen.getByText('GraphQL Schema共 60 项').closest('ul')!
    await userEvent.click(within(pager).getByTitle('Next Page'))
    await waitFor(() => expect(pages.at(-1)).toBe('3'))
    expect(screen.getByText('页外固定GraphQL · v3')).toBeVisible()
    expect(screen.getByTestId('protocol-location')).toHaveTextContent(
      `graphqlSchema=${selected.id}`,
    )
    expect(screen.getByTestId('protocol-location')).toHaveTextContent('graphqlPage=3')
    await userEvent.click(screen.getByRole('button', { name: '协议测试后退' }))
    await waitFor(() =>
      expect(screen.getByTestId('protocol-location')).toHaveTextContent('graphqlPage=2'),
    )
    expect(screen.getByText('页外固定GraphQL · v3')).toBeVisible()
  })

  it('keeps unavailable or invalid protocol links explicit instead of falling back to the first asset', async () => {
    installHandlers()
    const absent = '00000000-0000-4000-8000-000000000899'
    server.use(
      http.get(`/api/v1/graphql/schemas/${absent}`, () =>
        HttpResponse.json(
          {
            error: {
              code: 'SCHEMA_ARTIFACT_NOT_FOUND',
              message: '协议版本不存在',
              details: null,
              trace_id: 'missing-schema-trace',
            },
          },
          { status: 404 },
        ),
      ),
    )
    renderPage(`?mode=graphql&graphqlSchema=${absent}`)
    expect(await screen.findByText(/协议版本不存在/)).toBeVisible()
    expect(screen.getByText(/missing-schema-trace/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /执行 GraphQL/ })).not.toBeInTheDocument()
  })

  it('restores the exact event source using its own mode and link parameters', async () => {
    installHandlers()
    const selected = {
      ...websocketSource,
      id: '00000000-0000-4000-8000-000000000813',
      name: '页外固定WebSocket',
      version: 7,
    }
    server.use(http.get(`/api/v1/event-sources/${selected.id}`, () => HttpResponse.json(selected)))
    renderPage(
      `?mode=websocket&websocketSource=${selected.id}&websocketPage=2&graphqlSchema=${graphqlSchema.id}`,
    )
    expect(await screen.findByText('页外固定WebSocket · v7')).toBeVisible()
    expect(screen.queryByLabelText('GraphQL Operation')).not.toBeInTheDocument()
    expect(screen.getByLabelText('WebSocket Message')).toBeInTheDocument()
  })

  it('restores a Kafka message schema outside its catalog page and keeps it fixed while paging', async () => {
    installHandlers()
    const schema = {
      ...graphqlSchema,
      id: '00000000-0000-4000-8000-000000000829',
      protocol: 'kafka',
      name: '页外订单消息',
      version: 9,
    }
    const payloads: Array<{ schema_id: string }> = []
    server.use(
      http.get('/api/v1/event-sources/:sourceId/schemas', () =>
        HttpResponse.json({ items: [], total: 60, page: 2, page_size: 20 }),
      ),
      http.get(`/api/v1/event-sources/${kafkaSource.id}/schemas/${schema.id}`, () =>
        HttpResponse.json(schema),
      ),
      http.post('/api/v1/event-sources/:sourceId/kafka/produce', async ({ request }) => {
        payloads.push((await request.json()) as (typeof payloads)[number])
        return HttpResponse.json({ output: { operation: 'produce' }, duration_ms: 1 })
      }),
    )
    renderPage(
      `?mode=kafka&kafkaSource=${kafkaSource.id}&kafkaSchema=${schema.id}&kafkaSchemaPage=2`,
    )
    await screen.findByText('页外订单消息 · v9')
    const pager = screen.getByText('项目消息 Schema共 60 项').closest('ul')!
    await userEvent.click(within(pager).getByTitle('Next Page'))
    await waitFor(() =>
      expect(screen.getByTestId('protocol-location')).toHaveTextContent('kafkaSchemaPage=3'),
    )
    expect(screen.getByText('页外订单消息 · v9')).toBeVisible()
    await userEvent.click(screen.getByRole('button', { name: /Produce/ }))
    await waitFor(() =>
      expect(payloads).toEqual([expect.objectContaining({ schema_id: schema.id })]),
    )
  })

  it('restores request drafts separately for each protocol and fixed asset version', async () => {
    installHandlers()
    renderPage()
    await screen.findByLabelText('GraphQL Variables')
    fireEvent.change(screen.getByLabelText('GraphQL Variables'), {
      target: { value: '{"id":"007"}' },
    })
    await userEvent.click(screen.getByText('gRPC', { selector: '.ant-segmented-item-label' }))
    await screen.findByLabelText('gRPC Request')
    fireEvent.change(screen.getByLabelText('gRPC Request'), {
      target: { value: '{"message":"grpc-only"}' },
    })
    await userEvent.click(screen.getByText('GraphQL', { selector: '.ant-segmented-item-label' }))
    expect(await screen.findByLabelText('GraphQL Variables')).toHaveValue('{"id":"007"}')
    await userEvent.click(screen.getByText('gRPC', { selector: '.ant-segmented-item-label' }))
    expect(await screen.findByLabelText('gRPC Request')).toHaveValue('{"message":"grpc-only"}')
  })

  it('sends the frozen enabled GraphQL headers and invalidates evidence when a header is edited', async () => {
    installHandlers()
    let release: () => void = () => {}
    let received: () => void = () => {}
    const started = new Promise<void>((resolve) => {
      received = resolve
    })
    const pending = new Promise<void>((resolve) => {
      release = resolve
    })
    const payloads: Array<{
      headers: Record<string, string>
      timeout_seconds: number
      operation_name?: string
      schema_id: string
    }> = []
    server.use(
      http.post('/api/v1/graphql/execute', async ({ request }) => {
        payloads.push((await request.json()) as (typeof payloads)[number])
        received()
        await pending
        return HttpResponse.json({
          output: { body: { data: 'stale-header-response' } },
          schema_id: graphqlSchema.id,
          schema_version: 2,
          schema_hash: graphqlSchema.content_sha256,
          duration_ms: 1,
        })
      }),
    )
    const view = renderPage()
    const browser = userEvent.setup()
    await screen.findByLabelText('GraphQL Authorization')
    fireEvent.change(screen.getByLabelText('GraphQL Authorization'), {
      target: { value: 'Bearer synthetic-graphql' },
    })
    fireEvent.change(screen.getByLabelText('GraphQL Operation Name'), { target: { value: 'User' } })
    fireEvent.change(screen.getByLabelText('GraphQL超时'), { target: { value: '17' } })
    await browser.click(screen.getByRole('button', { name: /GraphQL Header高级键值/ }))
    await browser.click(screen.getByRole('button', { name: '添加GraphQL Header' }))
    fireEvent.change(screen.getByLabelText('GraphQL Header键1'), { target: { value: 'X-Team' } })
    fireEvent.change(screen.getByLabelText('GraphQL Header值1'), {
      target: { value: 'before-review' },
    })
    await browser.click(screen.getByRole('button', { name: '添加GraphQL Header' }))
    fireEvent.change(await screen.findByLabelText('GraphQL Header键2'), {
      target: { value: 'X-Ignored' },
    })
    fireEvent.change(screen.getByLabelText('GraphQL Header值2'), {
      target: { value: 'disabled-value' },
    })
    await browser.click(screen.getByRole('switch', { name: '启用GraphQL Header2' }))
    await browser.click(screen.getByRole('button', { name: /执行 GraphQL/ }))
    await waitFor(() => expect(payloads).toHaveLength(1))
    await started
    expect(payloads).toEqual([
      expect.objectContaining({
        headers: { 'X-Team': 'before-review', Authorization: 'Bearer synthetic-graphql' },
        operation_name: 'User',
        timeout_seconds: 17,
        schema_id: graphqlSchema.id,
      }),
    ])
    fireEvent.change(screen.getByLabelText('GraphQL Header值1'), {
      target: { value: 'after-review' },
    })
    await act(async () => {
      release()
      await waitFor(() => expect(view.queryClient.isMutating()).toBe(0))
    })
    await browser.click(screen.getByText('响应', { exact: true }))
    expect(screen.getByText('尚未执行')).toBeInTheDocument()
    expect(screen.queryByText(/stale-header-response/)).not.toBeInTheDocument()
    const persisted = [localStorage, sessionStorage]
      .flatMap((storage) => Object.keys(storage).map((key) => storage.getItem(key)))
      .join(' ')
    expect(persisted).not.toContain('synthetic-graphql')
  })

  it('keeps GraphQL authentication out of gRPC and sends only enabled normalized metadata', async () => {
    installHandlers()
    const payloads: Array<{
      metadata: Record<string, string>
      timeout_seconds: number
      descriptor_id: string
      tls_mode: string
    }> = []
    server.use(
      http.post('/api/v1/grpc/execute', async ({ request }) => {
        payloads.push((await request.json()) as (typeof payloads)[number])
        return HttpResponse.json({
          output: { messages: [] },
          schema_id: grpcDescriptor.id,
          schema_version: 1,
          schema_hash: grpcDescriptor.content_sha256,
          duration_ms: 1,
        })
      }),
    )
    renderPage()
    const browser = userEvent.setup()
    await screen.findByLabelText('GraphQL Authorization')
    fireEvent.change(screen.getByLabelText('GraphQL Authorization'), {
      target: { value: 'Bearer synthetic-graphql-only' },
    })
    await browser.click(screen.getByText('gRPC', { selector: '.ant-segmented-item-label' }))
    expect(await screen.findByLabelText('gRPC Authorization')).toHaveValue('')
    fireEvent.change(screen.getByLabelText('gRPC Authorization'), {
      target: { value: 'Bearer synthetic-grpc-only' },
    })
    fireEvent.change(screen.getByLabelText('gRPC超时'), { target: { value: '23' } })
    await browser.click(screen.getByRole('button', { name: /gRPC Metadata高级键值/ }))
    await browser.click(screen.getByRole('button', { name: '添加gRPC Metadata' }))
    fireEvent.change(screen.getByLabelText('gRPC Metadata键1'), { target: { value: 'X-TEAM' } })
    fireEvent.change(screen.getByLabelText('gRPC Metadata值1'), { target: { value: 'grpc-team' } })
    await browser.click(screen.getByRole('button', { name: '添加gRPC Metadata' }))
    fireEvent.change(await screen.findByLabelText('gRPC Metadata键2'), {
      target: { value: 'X-TEAM' },
    })
    fireEvent.change(screen.getByLabelText('gRPC Metadata值2'), {
      target: { value: 'disabled-duplicate' },
    })
    await browser.click(screen.getByRole('switch', { name: '启用gRPC Metadata2' }))
    await browser.click(screen.getByRole('button', { name: /执行 gRPC/ }))
    await waitFor(() => expect(payloads).toHaveLength(1))
    expect(payloads[0]).toMatchObject({
      metadata: { 'x-team': 'grpc-team', authorization: 'Bearer synthetic-grpc-only' },
      timeout_seconds: 23,
      descriptor_id: grpcDescriptor.id,
      tls_mode: 'tls',
    })
  })

  it.each(['success', 'error'] as const)(
    'does not apply an old Kafka source %s after selecting a different source',
    async (outcome) => {
      installHandlers()
      const other = {
        ...kafkaSource,
        id: '00000000-0000-4000-8000-000000000814',
        name: '第二Kafka源',
        version: 2,
        config_sha256: 'e'.repeat(64),
      }
      let release: () => void = () => {}
      const pending = new Promise<void>((resolve) => {
        release = resolve
      })
      let received = false
      server.use(
        http.get('/api/v1/event-sources', () =>
          HttpResponse.json({ items: [kafkaSource, other], total: 2, page: 1, page_size: 20 }),
        ),
        http.post(`/api/v1/event-sources/${kafkaSource.id}/kafka/produce`, async () => {
          received = true
          await pending
          if (outcome === 'error')
            return HttpResponse.json(
              {
                error: {
                  code: 'OLD_SOURCE_FAILED',
                  message: 'previous-source-failure',
                  details: null,
                  trace_id: 'old-source-trace',
                },
              },
              { status: 503 },
            )
          return HttpResponse.json({ output: { result: 'old-source-evidence' }, duration_ms: 1 })
        }),
      )
      const view = renderPage('?mode=kafka')
      const browser = userEvent.setup()
      await browser.click(await screen.findByRole('button', { name: /Produce/ }))
      await waitFor(() => expect(received).toBe(true))
      await browser.click(screen.getByText('第二Kafka源', { exact: true }))
      await screen.findByText('第二Kafka源 · v2')
      await act(async () => {
        release()
        await waitFor(() => expect(view.queryClient.isMutating()).toBe(0))
      })
      await browser.click(screen.getByText('Exchange', { exact: true }))
      expect(screen.getByText('尚未执行')).toBeInTheDocument()
      expect(
        screen.queryByText(
          /old-source-evidence|previous-source-failure|Request failed with status code 503/,
        ),
      ).not.toBeInTheDocument()
    },
  )

  it('keeps the newer Kafka consume result when an older produce request finishes last', async () => {
    installHandlers()
    let release: () => void = () => {}
    const pending = new Promise<void>((resolve) => {
      release = resolve
    })
    let received = false
    server.use(
      http.post(`/api/v1/event-sources/${kafkaSource.id}/kafka/produce`, async () => {
        received = true
        await pending
        return HttpResponse.json({ output: { result: 'older-produce' }, duration_ms: 1 })
      }),
      http.post(`/api/v1/event-sources/${kafkaSource.id}/kafka/consume`, () =>
        HttpResponse.json({ output: { result: 'newest-consume' }, duration_ms: 1 }),
      ),
    )
    const view = renderPage('?mode=kafka')
    const browser = userEvent.setup()
    await browser.click(await screen.findByRole('button', { name: /Produce/ }))
    await waitFor(() => expect(received).toBe(true))
    await browser.click(screen.getByRole('button', { name: /Consume/ }))
    await browser.click(screen.getByText('Exchange', { exact: true }))
    await screen.findByText(/newest-consume/)
    await act(async () => {
      release()
      await waitFor(() => expect(view.queryClient.isMutating()).toBe(0))
    })
    expect(screen.getByText(/newest-consume/)).toBeInTheDocument()
    expect(screen.queryByText(/older-produce/)).not.toBeInTheDocument()
  })

  it('does not mount a global notification when an import finishes after workspace unmount', async () => {
    installHandlers()
    let release!: () => void
    let received!: () => void
    const pending = new Promise<void>((resolve) => {
      release = resolve
    })
    const started = new Promise<void>((resolve) => {
      received = resolve
    })
    server.use(
      http.post('/api/v1/graphql/schemas', async () => {
        received()
        await pending
        return HttpResponse.json(graphqlSchema)
      }),
    )
    const view = renderPage()
    await screen.findByText('用户 GraphQL')
    await userEvent.click(screen.getByRole('button', { name: /导入协议 Schema/ }))
    await userEvent.type(screen.getByLabelText('名称'), '卸载中的导入')
    await userEvent.click(screen.getByRole('button', { name: '校验并保存' }))
    await started
    view.unmount()
    try {
      await act(async () => {
        release()
        await waitFor(() => expect(view.queryClient.isMutating()).toBe(0))
      })
      expect(document.querySelector('.ant-message')).toBeNull()
    } finally {
      await act(async () => {
        staticMessage.destroy()
      })
      view.queryClient.clear()
    }
  })

  it('invalidates completed and pending evidence when the same schema request is edited', async () => {
    installHandlers()
    renderPage()
    await screen.findByText('用户 GraphQL')
    await userEvent.click(screen.getByRole('button', { name: /执行 GraphQL/ }))
    await userEvent.click(screen.getByText('响应', { exact: true }))
    expect(await screen.findByText(/Alice/)).toBeVisible()
    await userEvent.click(screen.getByText('请求', { exact: true }))
    let release!: () => void
    let received!: () => void
    const started = new Promise<void>((resolve) => {
      received = resolve
    })
    const pending = new Promise<void>((resolve) => {
      release = resolve
    })
    server.use(
      http.post('/api/v1/graphql/execute', async () => {
        received()
        await pending
        return HttpResponse.json({
          output: { body: { data: 'outdated-operation' } },
          schema_id: graphqlSchema.id,
          schema_version: 2,
          schema_hash: graphqlSchema.content_sha256,
          duration_ms: 1,
        })
      }),
    )
    await userEvent.click(screen.getByRole('button', { name: /执行 GraphQL/ }))
    await started
    fireEvent.change(screen.getByLabelText('GraphQL Operation'), {
      target: { value: 'query NewOperation { id }' },
    })
    release()
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /执行 GraphQL/ })).not.toHaveClass(
        'ant-btn-loading',
      ),
    )
    await userEvent.click(screen.getByText('响应', { exact: true }))
    expect(screen.getByText('尚未执行')).toBeVisible()
    expect(screen.queryByText(/Alice|outdated-operation/)).not.toBeInTheDocument()
  })

  it('isolates a late debug response from another schema and starts with an empty result', async () => {
    installHandlers()
    let release!: () => void
    const pending = new Promise<void>((resolve) => {
      release = resolve
    })
    const second = {
      ...graphqlSchema,
      id: '00000000-0000-4000-8000-000000000811',
      name: '订单 GraphQL',
      version: 3,
    }
    server.use(
      http.get('/api/v1/graphql/schemas', () =>
        HttpResponse.json({ items: [graphqlSchema, second], total: 2, page: 1, page_size: 20 }),
      ),
      http.post('/api/v1/graphql/execute', async () => {
        await pending
        return HttpResponse.json({
          output: { body: { data: 'late-first-schema-result' } },
          schema_id: graphqlSchema.id,
          schema_version: 2,
          schema_hash: graphqlSchema.content_sha256,
          duration_ms: 1,
        })
      }),
    )
    renderPage()
    await screen.findByText('用户 GraphQL')
    fireEvent.change(screen.getByLabelText('GraphQL Endpoint'), {
      target: { value: 'https://first.example/graphql' },
    })
    await userEvent.click(screen.getByRole('button', { name: /执行 GraphQL/ }))
    await userEvent.click(screen.getByText('订单 GraphQL'))
    expect(screen.getByLabelText('GraphQL Endpoint')).toHaveValue('https://api.example.com/graphql')
    release()
    await userEvent.click(screen.getByText('响应'))
    expect(screen.getByText('尚未执行')).toBeVisible()
    expect(screen.queryByText(/late-first-schema-result/)).not.toBeInTheDocument()
  })

  it('executes GraphQL and gRPC against pinned schema versions', async () => {
    installHandlers()
    renderPage()
    const browser = userEvent.setup()

    expect(await screen.findByText('用户 GraphQL')).toBeVisible()
    expect(screen.getByText(graphqlSchema.content_sha256)).toBeVisible()
    await browser.click(screen.getByRole('button', { name: /执行 GraphQL/ }))
    await browser.click(screen.getByText('响应'))
    expect(await screen.findByText(/Alice/)).toBeVisible()
    expect(screen.getByText('Snapshot v2')).toBeVisible()

    await browser.click(screen.getByText('gRPC'))
    expect(await screen.findByText('用户 gRPC')).toBeVisible()
    expect(screen.getByText('flowtest.user.v1.UserService / GetUser')).toBeVisible()
    await browser.click(screen.getByRole('button', { name: /执行 gRPC/ }))
    await browser.click(screen.getByText('响应流'))
    expect(await screen.findByText(/grpc-user/)).toBeVisible()
  })

  it('produces and consumes Kafka messages and runs a bounded WebSocket exchange', async () => {
    installHandlers()
    renderPage()
    const browser = userEvent.setup()

    await screen.findByText('用户 GraphQL')
    await browser.click(screen.getByText('Kafka', { exact: true }))
    expect(await screen.findByText('订单 Kafka')).toBeVisible()
    await browser.click(screen.getByRole('button', { name: /Produce/ }))
    await browser.click(screen.getByText('Exchange'))
    expect(await screen.findByText(/partition/)).toBeVisible()

    await browser.click(screen.getByText('消息'))
    await browser.click(screen.getByRole('button', { name: /Consume/ }))
    await browser.click(screen.getByText('Exchange'))
    expect(await screen.findByText(/message_count/)).toBeVisible()

    await browser.click(screen.getByText('WebSocket', { exact: true }))
    expect(await screen.findByText('订单 WebSocket')).toBeVisible()
    await browser.click(screen.getByRole('button', { name: /Connect → Send/ }))
    await browser.click(screen.getByText('Exchange'))
    expect(await screen.findByText(/"operation": "exchange"/)).toBeVisible()
  })

  it('creates a versioned event source without embedding credentials', async () => {
    let created: Record<string, unknown> | null = null
    installHandlers()
    server.use(
      http.post('/api/v1/event-sources', async ({ request }) => {
        created = (await request.json()) as Record<string, unknown>
        return HttpResponse.json(kafkaSource, { status: 201 })
      }),
    )
    renderPage()
    const browser = userEvent.setup()

    await screen.findByText('用户 GraphQL')
    await browser.click(screen.getByText('Kafka', { exact: true }))
    await browser.click(screen.getByRole('button', { name: /新建事件源/ }))
    await browser.type(screen.getByLabelText('名称'), '订单集群')
    await browser.type(screen.getByLabelText('Bootstrap Servers'), 'redpanda:9092')
    await browser.click(screen.getByRole('button', { name: /保存事件源/ }))

    await waitFor(() => expect(created).toMatchObject({ kind: 'kafka' }))
    expect(created).not.toHaveProperty('password')
  })

  it('creates a WebSocket source and keeps protocol-specific fields separate', async () => {
    let created: Record<string, unknown> | null = null
    installHandlers()
    server.use(
      http.post('/api/v1/event-sources', async ({ request }) => {
        created = (await request.json()) as Record<string, unknown>
        return HttpResponse.json(websocketSource, { status: 201 })
      }),
    )
    renderPage()
    const browser = userEvent.setup()

    await screen.findByText('用户 GraphQL')
    await browser.click(screen.getByText('WebSocket', { exact: true }))
    await browser.click(screen.getByRole('button', { name: /新建事件源/ }))
    await browser.type(screen.getByLabelText('名称'), '订单 Echo')
    await browser.type(screen.getByLabelText('WebSocket URL'), 'ws://mock-target:8080/ws/echo')
    await browser.click(screen.getByRole('button', { name: /保存事件源/ }))

    await waitFor(() => expect(created).toMatchObject({ kind: 'websocket' }))
    expect(created).not.toHaveProperty('bootstrap_servers')
    expect(created).not.toHaveProperty('schema_registry_url')
  })

  it('imports Registry and manual Kafka schemas as immutable versions', async () => {
    const imports: string[] = []
    const catalog = [
      { ...graphqlSchema, id: '00000000-0000-4000-8000-000000000821', protocol: 'kafka' as const },
    ]
    installHandlers()
    server.use(
      http.get('/api/v1/event-sources/:sourceId/schemas', () =>
        HttpResponse.json({ items: catalog, total: catalog.length, page: 1, page_size: 20 }),
      ),
      http.post('/api/v1/event-sources/:sourceId/schemas/import', async ({ request }) => {
        const payload = (await request.json()) as Record<string, unknown>
        imports.push(String(payload.subject))
        catalog.push({
          ...graphqlSchema,
          id: '00000000-0000-4000-8000-000000000822',
          name: 'Registry 订单',
          protocol: 'kafka',
        })
        return HttpResponse.json(
          {
            ...graphqlSchema,
            id: '00000000-0000-4000-8000-000000000822',
            protocol: 'kafka',
            source_format: 'json_schema',
          },
          { status: 201 },
        )
      }),
      http.post('/api/v1/event-sources/:sourceId/schemas', async ({ request }) => {
        const payload = (await request.json()) as Record<string, unknown>
        imports.push(String(payload.schema_format))
        return HttpResponse.json(
          {
            ...graphqlSchema,
            id: '00000000-0000-4000-8000-000000000823',
            protocol: 'kafka',
            source_format: 'avro',
          },
          { status: 201 },
        )
      }),
    )
    renderPage()
    const browser = userEvent.setup()

    await screen.findByText('用户 GraphQL')
    await browser.click(screen.getByText('Kafka', { exact: true }))
    await browser.click(screen.getByRole('button', { name: /导入消息 Schema/ }))
    await browser.type(screen.getByLabelText('名称'), 'Registry 订单')
    await browser.type(screen.getByLabelText('Subject'), 'flowtest.orders-value')
    await browser.click(screen.getByRole('button', { name: '校验并保存' }))
    await waitFor(() => expect(imports).toEqual(['flowtest.orders-value']))
    await browser.click(screen.getByRole('combobox', { name: 'Kafka Schema' }))
    await browser.click(
      await screen.findByText(/Registry 订单/, { selector: '.ant-select-item-option-content' }),
    )

    await browser.click(screen.getByRole('button', { name: /导入消息 Schema/ }))
    await browser.click(screen.getByLabelText('来源'))
    await browser.click(screen.getByText('Avro Schema'))
    await browser.type(screen.getByLabelText('名称'), 'Avro 订单')
    fireEvent.change(screen.getByLabelText('Schema 内容'), {
      target: { value: '{"type":"record","name":"Order","fields":[]}' },
    })
    await browser.click(screen.getByRole('button', { name: '校验并保存' }))
    await waitFor(() => expect(imports).toEqual(['flowtest.orders-value', 'avro']))
  })

  it('supports text WebSocket exchange without a correlation expression', async () => {
    let exchanged: Record<string, unknown> | null = null
    installHandlers()
    server.use(
      http.post('/api/v1/event-sources/:sourceId/websocket/exchange', async ({ request }) => {
        exchanged = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({
          output: { operation: 'exchange', message_count: 1, messages: ['plain-message'] },
          duration_ms: 4,
        })
      }),
    )
    renderPage()
    const browser = userEvent.setup()

    await screen.findByText('用户 GraphQL')
    await browser.click(screen.getByText('WebSocket', { exact: true }))
    await browser.click(screen.getByText('Text', { selector: '.ant-segmented-item-label' }))
    fireEvent.change(screen.getByLabelText('WebSocket Message'), {
      target: { value: 'plain-message' },
    })
    await browser.clear(screen.getByLabelText('Correlation Expression'))
    await browser.click(screen.getByRole('button', { name: /Connect → Send/ }))

    await waitFor(() => expect(exchanged).toMatchObject({ payload_kind: 'text' }))
    expect(exchanged).not.toHaveProperty('correlation_expression')
    expect(exchanged).not.toHaveProperty('correlation_value')
  })

  it('rejects an invalid Kafka JSON message before transport', async () => {
    let produced = false
    installHandlers()
    server.use(
      http.post('/api/v1/event-sources/:sourceId/kafka/produce', () => {
        produced = true
        return HttpResponse.json({})
      }),
    )
    renderPage()
    const browser = userEvent.setup()

    await screen.findByText('用户 GraphQL')
    await browser.click(screen.getByText('Kafka', { exact: true }))
    fireEvent.change(screen.getByLabelText('Kafka Message'), { target: { value: '{bad' } })
    await browser.click(screen.getByRole('button', { name: /Produce/ }))

    await waitFor(() => expect(produced).toBe(false))
  })

  it('imports a validated immutable schema version', async () => {
    let created = false
    installHandlers()
    server.use(
      http.post('/api/v1/graphql/schemas', async ({ request }) => {
        const payload = (await request.json()) as Record<string, unknown>
        expect(payload.source_format).toBe('graphql_sdl')
        expect(String(payload.sdl)).toContain('type Query')
        created = true
        return HttpResponse.json(
          { ...graphqlSchema, id: 'graphql-new', name: payload.name },
          { status: 201 },
        )
      }),
    )
    renderPage()
    const browser = userEvent.setup()

    await screen.findByText('用户 GraphQL')
    await browser.click(screen.getByRole('button', { name: /导入协议 Schema/ }))
    await browser.type(screen.getByLabelText('名称'), '订单 GraphQL')
    await browser.click(screen.getByRole('button', { name: '校验并保存' }))

    await waitFor(() => expect(created).toBe(true))
  })

  it('imports GraphQL introspection JSON as a validated object', async () => {
    let introspection: unknown
    installHandlers()
    server.use(
      http.post('/api/v1/graphql/schemas', async ({ request }) => {
        const payload = (await request.json()) as Record<string, unknown>
        introspection = payload.introspection
        return HttpResponse.json({ ...graphqlSchema, source_format: payload.source_format })
      }),
    )
    renderPage()
    const browser = userEvent.setup()

    await screen.findByText('用户 GraphQL')
    await browser.click(screen.getByRole('button', { name: /导入协议 Schema/ }))
    await browser.type(screen.getByLabelText('名称'), '用户 Introspection')
    await browser.click(screen.getByLabelText('导入格式'))
    await browser.click(screen.getByText('Introspection JSON'))
    fireEvent.change(screen.getByLabelText('Schema 内容'), {
      target: { value: JSON.stringify({ __schema: { queryType: { name: 'Query' } } }) },
    })
    await browser.click(screen.getByRole('button', { name: '校验并保存' }))

    await waitFor(() =>
      expect(introspection).toEqual({ __schema: { queryType: { name: 'Query' } } }),
    )
  })

  it('imports Proto source and Protoset through the gRPC workbench', async () => {
    const formats: unknown[] = []
    installHandlers()
    server.use(
      http.post('/api/v1/grpc/descriptors', async ({ request }) => {
        const payload = (await request.json()) as Record<string, unknown>
        formats.push(payload.source_format)
        return HttpResponse.json({ ...grpcDescriptor, source_format: payload.source_format })
      }),
    )
    renderPage()
    const browser = userEvent.setup()

    await screen.findByText('用户 GraphQL')
    await browser.click(screen.getByText('gRPC', { exact: true }))
    await browser.click(screen.getByRole('button', { name: /导入协议 Schema/ }))
    await browser.type(screen.getByLabelText('名称'), '用户 Proto')
    await browser.click(screen.getByRole('button', { name: '校验并保存' }))
    await waitFor(() => expect(formats).toEqual(['proto_source']))

    await browser.click(screen.getByRole('button', { name: /导入协议 Schema/ }))
    await browser.type(screen.getByLabelText('名称'), '用户 Protoset')
    await browser.click(screen.getByLabelText('导入格式'))
    await browser.click(screen.getByText('Protoset Base64'))
    await browser.clear(screen.getByLabelText('Schema 内容'))
    await browser.type(screen.getByLabelText('Schema 内容'), 'ZGVzY3JpcHRvcg==')
    await browser.click(screen.getByRole('button', { name: '校验并保存' }))

    await waitFor(() => expect(formats).toEqual(['proto_source', 'proto_descriptor_set']))
  })

  it('rejects non-object GraphQL variables before sending a request', async () => {
    let executed = false
    installHandlers()
    server.use(
      http.post('/api/v1/graphql/execute', () => {
        executed = true
        return HttpResponse.json({})
      }),
    )
    renderPage()
    const browser = userEvent.setup()

    await screen.findByText('用户 GraphQL')
    fireEvent.change(screen.getByLabelText('GraphQL Variables'), { target: { value: '[]' } })
    await browser.click(screen.getByRole('button', { name: /执行 GraphQL/ }))

    expect(await screen.findByText('Variables 必须是 JSON 对象')).toBeInTheDocument()
    expect(executed).toBe(false)
  })

  it('fills real contract examples without executing and supports gRPC methods when a legacy summary is absent', async () => {
    installHandlers()
    const payloads: Array<{ service: string; method: string; request: object }> = []
    server.use(
      http.get('/api/v1/grpc/descriptors', () =>
        HttpResponse.json({
          items: [{ ...grpcDescriptor, summary: {} }],
          total: 1,
          page: 1,
          page_size: 20,
        }),
      ),
      http.get('/api/v1/protocol-assets/:id/structure', ({ request }) => {
        const node = new URL(request.url).searchParams.get('node') ?? 'root'
        const entries =
          node === 'root'
            ? [
                {
                  key: 'service:audit.Orders',
                  label: 'audit.Orders',
                  kind: 'service',
                  type_label: '',
                  required: false,
                  description: '',
                  expandable: true,
                },
              ]
            : node === 'service:audit.Orders'
              ? [
                  {
                    key: 'method:audit.Orders/Get',
                    label: 'Get',
                    kind: 'method',
                    type_label: 'unary',
                    required: false,
                    description: '',
                    expandable: true,
                  },
                ]
              : []
        return HttpResponse.json({
          artifact_id: grpcDescriptor.id,
          project_id: project.id,
          protocol: 'grpc',
          version: 1,
          content_sha256: grpcDescriptor.content_sha256,
          view: {
            node,
            label: '真实方法',
            entries,
            total: entries.length,
            offset: 0,
            limit: 25,
            notice: '样例只保证契约结构',
            document: null,
            document_format: null,
            example:
              node === 'method:audit.Orders/Get'
                ? {
                    operation: null,
                    variables: null,
                    service: 'audit.Orders',
                    method: 'Get',
                    call_type: 'unary',
                    request: { orderId: 'from-contract' },
                  }
                : null,
          },
        })
      }),
      http.post('/api/v1/grpc/execute', async ({ request }) => {
        payloads.push((await request.json()) as (typeof payloads)[number])
        return HttpResponse.json({
          output: {},
          schema_id: grpcDescriptor.id,
          schema_version: 1,
          schema_hash: grpcDescriptor.content_sha256,
          duration_ms: 1,
        })
      }),
    )
    renderPage('?mode=grpc')
    expect(await screen.findByRole('button', { name: /执行 gRPC/ })).toBeDisabled()
    await userEvent.click(await screen.findByRole('button', { name: '查看契约audit.Orders' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Get', exact: true }))
    await userEvent.click(await screen.findByRole('button', { name: '将样例填入请求草稿' }))
    expect(screen.getByLabelText('gRPC Request')).toHaveValue(
      JSON.stringify({ orderId: 'from-contract' }, null, 2),
    )
    expect(payloads).toHaveLength(0)
    expect(screen.getByRole('button', { name: /执行 gRPC/ })).toBeEnabled()
    await userEvent.click(screen.getByRole('button', { name: /执行 gRPC/ }))
    await waitFor(() =>
      expect(payloads).toEqual([
        expect.objectContaining({
          service: 'audit.Orders',
          method: 'Get',
          request: { orderId: 'from-contract' },
        }),
      ]),
    )
  })

  it('keeps GraphQL failure evidence scoped and explicitly locates aliases in the frozen contract', async () => {
    installHandlers()
    const lookups: unknown[] = []
    server.use(
      http.post('/api/v1/graphql/execute', () =>
        HttpResponse.json(
          {
            error: {
              code: 'GRAPHQL_ERRORS',
              message: '响应包含字段错误',
              trace_id: 'graphql-field-trace',
              details: {
                output: {
                  body: { errors: [{ path: ['alias', 0, 'id'], message: 'field failed' }] },
                },
              },
            },
          },
          { status: 502 },
        ),
      ),
      http.post('/api/v1/graphql/schemas/:id/locate-error', async ({ request }) => {
        lookups.push(await request.json())
        return HttpResponse.json({
          artifact_id: graphqlSchema.id,
          project_id: project.id,
          version: 2,
          content_sha256: graphqlSchema.content_sha256,
          node: 'field:Query.user',
        })
      }),
      http.get('/api/v1/protocol-assets/:id/structure', ({ request }) => {
        const node = new URL(request.url).searchParams.get('node')
        return HttpResponse.json({
          artifact_id: graphqlSchema.id,
          project_id: project.id,
          protocol: 'graphql',
          version: 2,
          content_sha256: graphqlSchema.content_sha256,
          view: {
            node,
            label: node === 'root' ? '结构首页内容' : 'Query.user真实契约字段',
            entries: [],
            total: 0,
            offset: 0,
            limit: 25,
            example: null,
            notice: null,
            document: null,
            document_format: null,
          },
        })
      }),
    )
    renderPage()
    fireEvent.change(await screen.findByLabelText('GraphQL Operation'), {
      target: { value: 'query User { alias: user(id:"42") { id } }' },
    })
    await userEvent.click(screen.getByRole('button', { name: /执行 GraphQL/ }))
    await userEvent.click(screen.getByText('响应', { exact: true }))
    await screen.findByRole('button', { name: '定位错误对应契约' })
    expect(
      screen.getByText(/Trace ID: graphql-field-trace/, { selector: '.ant-alert-description' }),
    ).toBeInTheDocument()
    expect(lookups).toHaveLength(0)
    await userEvent.click(screen.getByRole('button', { name: '定位错误对应契约' }))
    expect(await screen.findByText('Query.user真实契约字段')).toBeInTheDocument()
    expect(lookups).toEqual([
      expect.objectContaining({
        project_id: project.id,
        operation: 'query User { alias: user(id:"42") { id } }',
        path: ['alias', 0, 'id'],
      }),
    ])
    await userEvent.click(screen.getByText('请求', { exact: true }))
    fireEvent.change(screen.getByLabelText('GraphQL Variables'), {
      target: { value: '{"id":"edited"}' },
    })
    await userEvent.click(screen.getByText('响应', { exact: true }))
    expect(screen.queryByRole('button', { name: '定位错误对应契约' })).not.toBeInTheDocument()
  })

  it('keeps a newly opened import draft when a cancelled import completes late', async () => {
    installHandlers()
    let release: () => void = () => {}
    const pending = new Promise<void>((resolve) => {
      release = resolve
    })
    let received = false
    server.use(
      http.post('/api/v1/graphql/schemas', async () => {
        received = true
        await pending
        return HttpResponse.json(graphqlSchema, { status: 201 })
      }),
    )
    const view = renderPage()
    await screen.findByLabelText('GraphQL Operation')
    await userEvent.click(screen.getByRole('button', { name: /导入协议 Schema/ }))
    fireEvent.change(screen.getByLabelText('名称'), { target: { value: '第一次导入' } })
    await userEvent.click(screen.getByRole('button', { name: '校验并保存' }))
    await waitFor(() => expect(received).toBe(true))
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    await userEvent.click(screen.getByRole('button', { name: /导入协议 Schema/ }))
    await screen.findByRole('dialog')
    expect(await screen.findByLabelText('名称')).toHaveValue('')
    fireEvent.change(screen.getByLabelText('名称'), { target: { value: '新的导入草稿' } })
    release()
    await waitFor(() => expect(view.queryClient.isMutating()).toBe(0))
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByLabelText('名称')).toHaveValue('新的导入草稿')
    expect(screen.queryByText('协议 Schema 已保存为不可变版本')).not.toBeInTheDocument()
  })

  it('blocks mTLS execution when the referenced credential disappears after refresh', async () => {
    installHandlers(true, [grpcCredential])
    const view = renderPage('?mode=grpc')
    await screen.findByLabelText('gRPC Request')
    await userEvent.click(screen.getByText('mTLS', { selector: '.ant-segmented-item-label' }))
    expect(screen.getByRole('button', { name: /执行 gRPC/ })).toBeEnabled()
    server.use(http.get('/api/v1/credentials', () => HttpResponse.json([])))
    await act(async () => {
      await view.queryClient.invalidateQueries({ queryKey: ['credentials', project.id] })
    })
    await waitFor(() => expect(screen.getByRole('button', { name: /执行 gRPC/ })).toBeDisabled())
    expect(screen.getByText('所选mTLS凭据不可用，请重新选择。')).toBeVisible()
    expect(
      screen.getByLabelText('gRPC mTLS Credential').closest('.ant-select-content'),
    ).toHaveTextContent('不可用凭据')
  })

  it('imports gRPC Reflection and exposes mTLS credentials without values', async () => {
    let reflected = false
    installHandlers(true, [grpcCredential])
    server.use(
      http.post('/api/v1/grpc/descriptors/reflection', async ({ request }) => {
        const payload = (await request.json()) as Record<string, unknown>
        expect(payload.endpoint).toBe('grpc-target:50051')
        expect(payload.tls_mode).toBe('mtls')
        expect(payload.credential_id).toBe(grpcCredential.id)
        reflected = true
        return HttpResponse.json(
          { ...grpcDescriptor, source_format: 'grpc_reflection' },
          { status: 201 },
        )
      }),
    )
    renderPage()
    const browser = userEvent.setup()

    await screen.findByText('用户 GraphQL')
    await browser.click(screen.getByText('gRPC', { exact: true }))
    await browser.click(screen.getByRole('button', { name: /导入协议 Schema/ }))
    await browser.type(screen.getByLabelText('名称'), 'Reflection 用户服务')
    await browser.click(screen.getByLabelText('导入格式'))
    await browser.click(screen.getByText('Server Reflection（TLS）'))
    await browser.clear(screen.getByLabelText('Schema 内容'))
    await browser.type(screen.getByLabelText('Schema 内容'), 'grpc-target:50051')
    const importDialog = within(screen.getByRole('dialog'))
    await browser.click(
      importDialog.getByText('mTLS', {
        selector: '.ant-segmented-item-label',
      }),
    )
    await browser.click(screen.getByLabelText('mTLS Credential'))
    await browser.click(
      screen.getByText(grpcCredential.name, { selector: '.ant-select-item-option-content' }),
    )
    await browser.click(screen.getByRole('button', { name: '校验并保存' }))
    await waitFor(() => expect(reflected).toBe(true))

    const grpcEditor = screen
      .getByLabelText('gRPC Endpoint')
      .closest<HTMLElement>('.protocol-editor')
    if (!grpcEditor) throw new Error('gRPC editor was not rendered')
    await browser.click(
      within(grpcEditor).getByText('mTLS', { selector: '.ant-segmented-item-label' }),
    )
    const credentialSelect = screen.getByLabelText('gRPC mTLS Credential')
    expect(credentialSelect).toBeVisible()
    expect(credentialSelect.closest('.ant-select-content')).toHaveTextContent(grpcCredential.name)
    expect(document.body.textContent).not.toContain('private-key')
  })

  it('keeps protocol execution disabled when its feature flag is off', async () => {
    installHandlers(false)
    renderPage()

    expect(await screen.findByText('多协议能力当前关闭')).toBeVisible()
    await screen.findByText('用户 GraphQL')
    expect(screen.getByRole('button', { name: /执行 GraphQL/ })).toBeDisabled()
  })

  it('renders a safe empty state when a project has no protocol assets', async () => {
    installHandlers()
    server.use(
      http.get('/api/v1/graphql/schemas', () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 100 }),
      ),
      http.get('/api/v1/grpc/descriptors', () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 100 }),
      ),
    )
    renderPage()

    expect(await screen.findByText('选择 Schema 版本开始调试')).toBeVisible()
    expect(screen.getByText('选择版本查看固定信息')).toBeVisible()
    expect(screen.queryByRole('button', { name: /执行 GraphQL/ })).not.toBeInTheDocument()
  })

  it('ignores malformed descriptor summary entries without hiding valid methods', async () => {
    const resilientDescriptor: SchemaArtifact = {
      ...grpcDescriptor,
      summary: {
        services: [
          null,
          { name: 7, methods: [] },
          { name: 'MissingMethods' },
          {
            name: 'flowtest.safe.UserService',
            methods: [null, { name: 8 }, { name: 'WatchUsers', call_type: 'server_streaming' }],
          },
        ],
      },
    }
    installHandlers()
    server.use(
      http.get('/api/v1/grpc/descriptors', () =>
        HttpResponse.json({
          items: [resilientDescriptor],
          total: 1,
          page: 1,
          page_size: 100,
        }),
      ),
    )
    renderPage()
    const browser = userEvent.setup()

    await screen.findByText('用户 GraphQL')
    await browser.click(screen.getByText('gRPC', { exact: true }))

    expect(await screen.findByText('flowtest.safe.UserService / WatchUsers')).toBeVisible()
    expect(screen.getByRole('button', { name: /执行 gRPC/ })).toBeEnabled()
  })

  it('blocks an mTLS debug request until a credential is selected', async () => {
    installHandlers(true, [])
    renderPage()
    const browser = userEvent.setup()

    await screen.findByText('用户 GraphQL')
    await browser.click(screen.getByText('gRPC', { exact: true }))
    const grpcEditor = screen
      .getByLabelText('gRPC Endpoint')
      .closest<HTMLElement>('.protocol-editor')
    if (!grpcEditor) throw new Error('gRPC editor was not rendered')
    await browser.click(
      within(grpcEditor).getByText('mTLS', { selector: '.ant-segmented-item-label' }),
    )

    expect(screen.getByLabelText('gRPC mTLS Credential')).toBeVisible()
    expect(screen.getByRole('button', { name: /执行 gRPC/ })).toBeDisabled()
  })

  it('falls back safely for custom schema metadata and multiple inventory rows', async () => {
    const customSchema: SchemaArtifact = {
      ...graphqlSchema,
      id: '00000000-0000-4000-8000-000000000804',
      name: '自定义 GraphQL',
      source_format: 'custom_schema',
      summary: {},
    }
    installHandlers()
    server.use(
      http.get('/api/v1/graphql/schemas', () =>
        HttpResponse.json({
          items: [customSchema, graphqlSchema],
          total: 2,
          page: 1,
          page_size: 100,
        }),
      ),
    )
    renderPage()

    expect(await screen.findByText('自定义 GraphQL')).toBeVisible()
    expect(screen.getAllByText('custom_schema').length).toBeGreaterThan(0)
    expect(screen.getByText('未提供 类型')).toBeVisible()
  })
})

function installHandlers(enabled = true, credentials: Credential[] = []) {
  server.use(
    http.get('/api/v1/projects', () =>
      HttpResponse.json({ items: [project], total: 1, page: 1, page_size: 100 }),
    ),
    http.get('/api/v1/v3/features', () =>
      HttpResponse.json({
        capability_sdk: true,
        plugin_registry: false,
        runner_fabric: false,
        multi_protocol: enabled,
        event_protocols: enabled,
        performance_lab: false,
        environment_lab: false,
      }),
    ),
    http.get('/api/v1/graphql/schemas', () =>
      HttpResponse.json({ items: [graphqlSchema], total: 1, page: 1, page_size: 100 }),
    ),
    http.get('/api/v1/grpc/descriptors', () =>
      HttpResponse.json({ items: [grpcDescriptor], total: 1, page: 1, page_size: 100 }),
    ),
    http.get('/api/v1/event-sources', ({ request }) => {
      const kind = new URL(request.url).searchParams.get('kind')
      const items = kind === 'websocket' ? [websocketSource] : [kafkaSource]
      return HttpResponse.json({ items, total: 1, page: 1, page_size: 100 })
    }),
    http.get('/api/v1/event-sources/:sourceId/schemas', () =>
      HttpResponse.json({
        items: [
          { ...graphqlSchema, id: '00000000-0000-4000-8000-000000000821', protocol: 'kafka' },
        ],
        total: 1,
        page: 1,
        page_size: 100,
      }),
    ),
    http.get('/api/v1/protocol-assets/:id/structure', ({ params, request }) => {
      const node = new URL(request.url).searchParams.get('node') ?? 'root'
      const asset = params.id === grpcDescriptor.id ? grpcDescriptor : graphqlSchema
      return HttpResponse.json({
        artifact_id: params.id,
        project_id: project.id,
        protocol: asset.protocol,
        version: asset.version,
        content_sha256: asset.content_sha256,
        view: {
          node,
          label: '测试契约结构',
          entries: [],
          total: 0,
          offset: 0,
          limit: 25,
          example: null,
          notice: null,
          document: null,
          document_format: null,
        },
      })
    }),
    http.get('/api/v1/credentials', () => HttpResponse.json(credentials)),
    http.post('/api/v1/graphql/execute', () =>
      HttpResponse.json({
        output: { body: { data: { user: { id: '42', name: 'Alice' } } } },
        schema_id: graphqlSchema.id,
        schema_version: 2,
        schema_hash: graphqlSchema.content_sha256,
        duration_ms: 18,
      }),
    ),
    http.post('/api/v1/grpc/execute', () =>
      HttpResponse.json({
        output: { messages: [{ id: '42', name: 'grpc-user' }], message_count: 1 },
        schema_id: grpcDescriptor.id,
        schema_version: 1,
        schema_hash: grpcDescriptor.content_sha256,
        duration_ms: 12,
      }),
    ),
    http.post('/api/v1/event-sources/:sourceId/kafka/produce', () =>
      HttpResponse.json({
        output: { operation: 'produce', topic: 'flowtest.orders', partition: 0, offset: 1 },
        duration_ms: 8,
      }),
    ),
    http.post('/api/v1/event-sources/:sourceId/kafka/consume', () =>
      HttpResponse.json({
        output: { operation: 'consume', message_count: 1, messages: [{ id: 'order-42' }] },
        duration_ms: 12,
      }),
    ),
    http.post('/api/v1/event-sources/:sourceId/websocket/exchange', () =>
      HttpResponse.json({
        output: { operation: 'exchange', message_count: 1, messages: [{ id: 'order-42' }] },
        duration_ms: 10,
      }),
    ),
  )
}

const grpcCredential: Credential = {
  id: '00000000-0000-4000-8000-000000000803',
  project_id: project.id,
  name: '用户服务 mTLS',
  kind: 'grpc_mtls',
  host: 'grpc.example.com',
  port: 443,
  database_name: '',
  username: '',
  secret_provider: 'local',
  tls_enabled: true,
  created_by_id: user.id,
  created_at: '2026-08-12T00:00:00Z',
  updated_at: '2026-08-12T00:00:00Z',
}

function RouteProbe() {
  const location = useLocation()
  const navigate = useNavigate()
  return (
    <>
      <output data-testid="protocol-location">{location.search}</output>
      <button onClick={() => navigate(-1)}>协议测试后退</button>
    </>
  )
}

function renderPage(search = '') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const view = render(
    <AntdApp>
      <QueryClientProvider client={queryClient}>
        <ProjectTestProvider
          section="protocols"
          initialEntry={`/projects/${project.id}/protocols${search}`}
        >
          <RouteProbe />
          <ProtocolWorkbenchPage />
        </ProjectTestProvider>
      </QueryClientProvider>
    </AntdApp>,
  )
  return { ...view, queryClient }
}
