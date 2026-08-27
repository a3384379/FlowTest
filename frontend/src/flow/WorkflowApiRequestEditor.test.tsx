import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import WorkflowApiRequestEditor from './WorkflowApiRequestEditor'
import { getApiDetail, previewApi } from '../features/api-console/api-service'
import type { ApiDetail, Artifact, WorkflowNode } from '../lib/api'

vi.mock('../features/api-console/api-service', () => ({
  getApiDetail: vi.fn(),
  previewApi: vi.fn(),
}))

describe('WorkflowApiRequestEditor', () => {
  it('inherits each request section and only persists node-level overrides', async () => {
    const user = userEvent.setup()
    vi.mocked(getApiDetail).mockResolvedValue(detail)
    const onUpdate = vi.fn()
    renderEditor(onUpdate)

    expect(screen.getByText('固定 v3')).toBeVisible()
    expect(screen.getByText('节点覆盖：Body')).toBeVisible()
    await user.click(screen.getByRole('button', { name: /配置节点请求/ }))
    expect(await screen.findByText('继承接口模板 v3')).toBeVisible()

    await user.click(screen.getByRole('tab', { name: 'Params' }))
    let panel = screen.getByRole('tabpanel')
    expect(within(panel).getByText('当前展示接口模板默认值（只读）')).toBeVisible()
    expect(within(panel).getByPlaceholderText('参数名')).toHaveValue('source')
    expect(within(panel).getByPlaceholderText('参数名')).toBeDisabled()
    expect(within(panel).getByPlaceholderText('值')).toHaveValue('template')
    expect(within(panel).getByPlaceholderText('值')).toBeDisabled()
    await user.click(within(panel).getByText('节点自定义'))
    expect(within(panel).getByPlaceholderText('参数名')).toBeEnabled()
    expect(within(panel).getByPlaceholderText('值')).toHaveValue('template')
    await user.clear(within(panel).getByPlaceholderText('值'))
    await user.type(within(panel).getByPlaceholderText('值'), 'workflow')

    await user.click(screen.getByRole('tab', { name: 'Headers' }))
    panel = screen.getByRole('tabpanel')
    expect(within(panel).getByPlaceholderText('Header 名称')).toHaveValue('X-Template')
    expect(within(panel).getByPlaceholderText('Header 名称')).toBeDisabled()
    expect(within(panel).getByPlaceholderText('值')).toHaveValue('true')
    expect(within(panel).getByPlaceholderText('值')).toBeDisabled()
    await user.click(within(panel).getByText('节点自定义'))
    expect(within(panel).getByPlaceholderText('Header 名称')).toBeEnabled()
    await user.clear(within(panel).getByPlaceholderText('值'))
    await user.type(within(panel).getByPlaceholderText('值'), 'node')

    await user.click(screen.getByRole('tab', { name: /Body/ }))
    panel = screen.getByRole('tabpanel')
    expect(within(panel).getByText('fixture.json (16 B)')).toBeVisible()
    await user.click(screen.getByRole('button', { name: '保存节点配置' }))

    await waitFor(() => expect(onUpdate).toHaveBeenCalledTimes(1))
    expect(onUpdate.mock.calls[0][0].config).toMatchObject({
      api_version: 3,
      request_overrides: {
        query_parameters: [{ enabled: true, name: 'source', value: 'workflow' }],
        headers: { 'X-Template': 'node' },
        body: {
          kind: 'multipart',
          value: {
            fields: { note: 'hello' },
            files: [{ field: 'document', artifact_id: artifact.id }],
          },
        },
      },
    })
  })

  it('shows inherited Body values as read-only and preserves an unsaved custom draft', async () => {
    const user = userEvent.setup()
    const inheritedNode: WorkflowNode = {
      ...node,
      config: { api_definition_id: 'api-1', api_version: 3, request_overrides: {} },
    }
    const jsonDetail: ApiDetail = {
      ...detail,
      version: {
        ...detail.version,
        body_kind: 'json',
        body: { name: 'template' },
      },
    }
    vi.mocked(getApiDetail).mockResolvedValue(jsonDetail)
    renderEditor(vi.fn(), jsonDetail.definition, inheritedNode)

    await user.click(screen.getByRole('button', { name: /配置节点请求/ }))
    await screen.findByText('继承接口模板 v3')
    await user.click(screen.getByRole('tab', { name: 'Body' }))
    const panel = screen.getByRole('tabpanel')
    let body = within(panel).getByRole('textbox', { name: 'JSON Body' })
    expect(body).toHaveValue('{\n  "name": "template"\n}')
    expect(body).toBeDisabled()

    await user.click(within(panel).getByText('节点自定义'))
    body = within(panel).getByRole('textbox', { name: 'JSON Body' })
    expect(body).toBeEnabled()
    fireEvent.change(body, { target: { value: '{"name":"workflow"}' } })

    await user.click(within(panel).getByText('继承接口模板'))
    body = within(panel).getByRole('textbox', { name: 'JSON Body' })
    expect(body).toHaveValue('{\n  "name": "template"\n}')
    expect(body).toBeDisabled()

    await user.click(within(panel).getByText('节点自定义'))
    expect(within(panel).getByRole('textbox', { name: 'JSON Body' })).toHaveValue(
      '{"name":"workflow"}',
    )
  })

  it('previews the effective request with resolved file metadata', async () => {
    const user = userEvent.setup()
    vi.mocked(getApiDetail).mockResolvedValue(detail)
    vi.mocked(previewApi).mockResolvedValue({
      method: 'POST',
      url: 'https://api.example.com/upload?source=template',
      headers: [],
      body: {
        fields: { note: 'hello' },
        files: [{ field: 'document', artifact_id: artifact.id }],
      },
    })
    renderEditor(vi.fn())

    await user.click(screen.getByRole('button', { name: /配置节点请求/ }))
    await screen.findByText('继承接口模板 v3')
    await user.click(screen.getByRole('button', { name: /预览最终请求/ }))

    expect(await screen.findByText(/file_previews/)).toBeInTheDocument()
    expect(screen.getAllByText(/fixture\.json/)).toHaveLength(2)
    expect(previewApi).toHaveBeenCalledWith('project-1', detail.definition.id, 'environment-1', {
      version: 3,
      queryParametersOverride: undefined,
      headersOverride: undefined,
      bodyOverride: bodyOverride.value,
      useBodyOverride: true,
    })
  })

  it('upgrades a pinned node to the latest interface version without dropping overrides', async () => {
    const user = userEvent.setup()
    const onUpdate = vi.fn()
    renderEditor(onUpdate, { ...detail.definition, current_version: 4 })

    await user.click(screen.getByRole('button', { name: '更新至接口最新 v4' }))
    expect(onUpdate).toHaveBeenCalledWith(
      expect.objectContaining({
        config: expect.objectContaining({
          api_version: 4,
          request_overrides: node.config.request_overrides,
        }),
      }),
    )
  })

  it('shows a disabled inherited state before an interface and project are available', () => {
    const queryClient = new QueryClient()
    render(
      <QueryClientProvider client={queryClient}>
        <WorkflowApiRequestEditor
          projectId={null}
          environmentId={null}
          node={{ ...node, config: { api_definition_id: '' } }}
          artifacts={[]}
          editable={false}
          onUpdate={vi.fn()}
        />
      </QueryClientProvider>,
    )

    expect(screen.getByText('版本待固定')).toBeVisible()
    expect(screen.getByText('全部继承接口模板')).toBeVisible()
    expect(screen.getByRole('button', { name: /配置节点请求/ })).toBeDisabled()
  })

  it('reports a missing pinned interface version', async () => {
    const user = userEvent.setup()
    vi.mocked(getApiDetail).mockRejectedValueOnce(new Error('missing'))
    renderEditor(vi.fn())

    await user.click(screen.getByRole('button', { name: /配置节点请求/ }))
    expect(await screen.findByText('接口版本加载失败')).toBeVisible()
  })
})

function renderEditor(
  onUpdate: (node: WorkflowNode) => void,
  api = detail.definition,
  targetNode = node,
) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <WorkflowApiRequestEditor
        projectId="project-1"
        environmentId="environment-1"
        node={targetNode}
        api={api}
        artifacts={[artifact]}
        editable
        onUpdate={onUpdate}
      />
    </QueryClientProvider>,
  )
}

const artifact: Artifact = {
  id: '00000000-0000-4000-8000-000000000123',
  project_id: 'project-1',
  filename: 'fixture.json',
  content_type: 'application/json',
  size_bytes: 16,
  sha256: 'abc',
  purpose: 'upload',
  created_at: '2026-08-15T00:00:00Z',
}

const detail: ApiDetail = {
  definition: {
    id: 'api-1',
    project_id: 'project-1',
    folder_id: null,
    name: '上传文件',
    description: '',
    current_version: 3,
    is_active: true,
  },
  version: {
    id: 'api-version-3',
    api_definition_id: 'api-1',
    version: 3,
    method: 'POST',
    path: '/upload',
    query_parameters: [{ name: 'source', value: 'template', enabled: true }],
    headers: { 'X-Template': 'true' },
    body_kind: 'none',
    body: null,
    auth_kind: 'bearer',
    auth_config: {},
    extraction_rules: [],
    assertions: [],
    created_at: '2026-08-15T00:00:00Z',
  },
}

const bodyOverride = {
  kind: 'multipart',
  value: {
    fields: { note: 'hello' },
    files: [{ field: 'document', artifact_id: artifact.id }],
  },
} as const

const node: WorkflowNode = {
  id: 'api',
  type: 'api',
  name: '上传文件',
  position: { x: 200, y: 100 },
  config: {
    api_definition_id: 'api-1',
    api_version: 3,
    request_overrides: {
      body: bodyOverride,
    },
  },
}
