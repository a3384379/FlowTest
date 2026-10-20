import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { describe, expect, it, vi } from 'vitest'
import { server } from '../../test/server'
import ProtocolContractBrowser from './ProtocolContractBrowser'
import type { ProtocolStructureResponse, SchemaArtifact } from './protocol-service'

const asset: SchemaArtifact = {
  id: '00000000-0000-4000-8000-000000000801',
  project_id: '00000000-0000-4000-8000-000000000101',
  protocol: 'graphql',
  name: '真实结构',
  version: 3,
  content_sha256: 'a'.repeat(64),
  source_format: 'graphql_sdl',
  summary: {},
  description: '',
  created_by_id: 'user',
  created_at: '',
  updated_at: '',
}
function response(
  node: string,
  view: Partial<ProtocolStructureResponse['view']> = {},
): ProtocolStructureResponse {
  return {
    artifact_id: asset.id,
    project_id: asset.project_id,
    protocol: 'graphql',
    version: 3,
    content_sha256: asset.content_sha256,
    view: {
      node,
      label: node,
      entries: [],
      total: 0,
      offset: 0,
      limit: 25,
      example: null,
      notice: null,
      document: null,
      document_format: null,
      ...view,
    },
  }
}
function renderBrowser() {
  const onExample = vi.fn()
  const view = render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <ProtocolContractBrowser asset={asset} onExample={onExample} />
    </QueryClientProvider>,
  )
  return { ...view, onExample }
}

describe('ProtocolContractBrowser', () => {
  it('loads real paths lazily, pages children and only applies a sample after an explicit click', async () => {
    const requests: string[] = []
    const example = {
      operation: 'query FlowTestExample { orders { __typename } }',
      variables: {},
      request: null,
      service: null,
      method: null,
      call_type: null,
    }
    server.use(
      http.get('/api/v1/protocol-assets/:id/structure', ({ request }) => {
        const params = new URL(request.url).searchParams
        const node = params.get('node') ?? 'root'
        requests.push(`${node}:${params.get('offset')}`)
        if (node === 'root')
          return HttpResponse.json(
            response(node, {
              entries: [
                {
                  key: 'operation:query',
                  label: 'query · ReadRoot',
                  kind: 'operation',
                  type_label: 'ReadRoot',
                  required: false,
                  description: '自定义查询根',
                  expandable: true,
                },
              ],
            }),
          )
        if (node === 'operation:query')
          return HttpResponse.json(
            response(node, {
              total: 60,
              entries: [
                {
                  key: 'field:ReadRoot.orders',
                  label: 'orders',
                  kind: 'field',
                  type_label: '[Order!]!',
                  required: false,
                  description: '',
                  expandable: true,
                },
              ],
            }),
          )
        if (node === 'source')
          return HttpResponse.json(
            response(node, {
              document: 'schema { query: ReadRoot }',
              document_format: 'text',
              notice: '源文档超过64 KiB,当前仅显示前缀。',
            }),
          )
        return HttpResponse.json(
          response(node, {
            example,
            entries: [
              {
                key: 'type:Filter',
                label: 'filter',
                kind: 'input',
                type_label: 'Filter!',
                required: true,
                description: '订单筛选',
                expandable: true,
              },
            ],
          }),
        )
      }),
    )
    const view = renderBrowser()
    expect(await screen.findByText('query · ReadRoot')).toBeInTheDocument()
    expect(requests).toEqual(['root:0'])
    await userEvent.click(screen.getByRole('button', { name: 'query · ReadRoot' }))
    await screen.findByText('[Order!]!')
    await userEvent.click(screen.getByTitle('Next Page'))
    await waitFor(() => expect(requests).toContain('operation:query:25'))
    await userEvent.click(screen.getByRole('button', { name: 'orders' }))
    expect(await screen.findByText('必填')).toBeInTheDocument()
    expect(view.onExample).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: '将样例填入请求草稿' }))
    expect(view.onExample).toHaveBeenCalledExactlyOnceWith(example)
    await userEvent.click(screen.getByRole('button', { name: '查看源文档' }))
    expect(await screen.findByText('schema { query: ReadRoot }')).toBeInTheDocument()
    expect(screen.getByText(/当前仅显示前缀/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '返回上层' }))
    expect(await screen.findByText('Filter!')).toBeInTheDocument()
  })
  it('refuses mismatched frozen identity and keeps scoped read failures explicit', async () => {
    server.use(
      http.get('/api/v1/protocol-assets/:id/structure', () =>
        HttpResponse.json({ ...response('root'), version: 4 }),
      ),
    )
    renderBrowser()
    expect(await screen.findByText(/契约结构身份与所选版本不一致/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '将样例填入请求草稿' })).not.toBeInTheDocument()
  })
  it('does not load source documents until selected and retains notices for unsupported input', async () => {
    server.use(
      http.get('/api/v1/protocol-assets/:id/structure', () =>
        HttpResponse.json(response('root', { notice: '必填输入包含递归,无法生成完整样例。' })),
      ),
    )
    const view = renderBrowser()
    expect(await screen.findByText(/必填输入包含递归/)).toBeInTheDocument()
    expect(view.onExample).not.toHaveBeenCalled()
    fireEvent.click(screen.getByText('契约结构与输入引导'))
    expect(screen.queryByRole('button', { name: '将样例填入请求草稿' })).not.toBeInTheDocument()
  })
})
