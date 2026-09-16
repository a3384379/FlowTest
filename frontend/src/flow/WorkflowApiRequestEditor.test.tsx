import { useState } from 'react'
import { ConfigProvider } from 'antd'
import { DraftContext, DraftSession } from '../features/drafts/draft-session'
import WorkflowNodeEditSession from './WorkflowNodeEditSession'
import { InspectorPresentationContext } from './editor/inspector-presentation'
import { workflowDefinition } from '../test/fixtures'
import { editorNode, restoreEditedNode } from './editor/graph-analysis'
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
  it.each(['api', 'capability'] as const)(
    'F01: mounted and unmounted %s request forms produce identical persistent sections',
    async (type) => {
      vi.mocked(getApiDetail).mockResolvedValue({
        ...detail,
        version: { ...detail.version, body_kind: 'json', body: { initial: true } },
      })
      const apiNode = {
        ...node,
        config: {
          ...node.config,
          request_overrides: { auth_disabled: true, suppressed_headers: ['X'] },
        },
      }
      const target: WorkflowNode =
        type === 'api'
          ? apiNode
          : {
              ...apiNode,
              type: 'capability',
              config: {},
              configuration: apiNode.config,
              capability_id: 'http.request',
              capability_version: '2.0.0',
              bindings: [],
              phase: 'cleanup',
              cleanup_for: ['start'],
            }
      const results: WorkflowNode[] = []
      for (const unmount of [false, true]) {
        const changed = vi.fn()
        const view = render(
          <RequestSessionHarness
            session={new DraftSession()}
            changed={changed}
            startFullscreen
            initialNode={target}
          />,
        )
        await screen.findByText('继承接口模板 v3')
        for (const section of ['Params', 'Headers', 'Body']) {
          fireEvent.click(screen.getByRole('tab', { name: section }))
          fireEvent.click(within(screen.getByRole('tabpanel')).getByText('节点自定义'))
        }
        fireEvent.change(screen.getByRole('textbox', { name: 'JSON Body' }), {
          target: { value: '{"preserved":true}' },
        })
        if (unmount) {
          fireEvent.click(screen.getByRole('button', { name: '还原配置测试' }))
          await waitFor(() => expect(screen.queryByText('继承接口模板 v3')).not.toBeInTheDocument())
        }
        fireEvent.click(screen.getByRole('button', { name: '应用节点配置' }))
        await waitFor(() => expect(changed).toHaveBeenCalledTimes(1))
        results.push(changed.mock.calls[0][0].nodes[0])
        view.unmount()
      }
      expect(results[1]).toEqual(results[0])
      expect(results[1].type).toBe(type)
      const config = type === 'capability' ? results[1].configuration : results[1].config
      expect(config?.request_overrides).toMatchObject({
        auth_disabled: true,
        suppressed_headers: ['X'],
        body: { kind: 'json', value: { preserved: true } },
        headers: detail.version.headers,
        query_parameters: detail.version.query_parameters,
      })
      if (type === 'capability')
        expect(results[1]).toMatchObject({
          config: {},
          bindings: [],
          capability_id: 'http.request',
          capability_version: '2.0.0',
          phase: 'cleanup',
          cleanup_for: ['start'],
        })
    },
  )

  it.each([false, true])(
    'F02: confirms an API switch with pending input (unmounted=%s)',
    async (unmount) => {
      vi.mocked(getApiDetail).mockImplementation(async (_project, id) => ({
        definition: { ...detail.definition, id, current_version: id === 'api-1' ? 12 : 2 },
        version: {
          ...detail.version,
          api_definition_id: id,
          version: id === 'api-1' ? 12 : 2,
          body_kind: 'json',
          body: { api: id },
        },
      }))
      const changed = vi.fn()
      render(
        <RequestSessionHarness
          session={new DraftSession()}
          changed={changed}
          startFullscreen
          initialNode={{ ...node, config: { api_definition_id: 'api-1', api_version: 12 } }}
        />,
      )
      await screen.findByText('继承接口模板 v12')
      fireEvent.click(screen.getByRole('tab', { name: 'Body' }))
      fireEvent.click(within(screen.getByRole('tabpanel')).getByText('节点自定义'))
      fireEvent.change(screen.getByRole('textbox', { name: 'JSON Body' }), {
        target: { value: '{"pending":"A"}' },
      })
      if (unmount) fireEvent.click(screen.getByRole('button', { name: '还原配置测试' }))
      fireEvent.click(screen.getByRole('button', { name: '切换接口测试' }))
      const confirmation = await screen.findByRole('dialog', { name: '切换请求目标？' })
      await userEvent.click(within(confirmation).getByRole('button', { name: '取消切换' }))
      await waitFor(() => expect(confirmation).not.toBeInTheDocument())
      expect(screen.getByText('固定 v12')).toBeInTheDocument()
      if (!unmount) {
        expect(screen.getByRole('textbox', { name: 'JSON Body' })).toHaveValue('{"pending":"A"}')
        expect(screen.getByRole('tab', { name: /Body/ })).toHaveAttribute('aria-selected', 'true')
      }
      fireEvent.click(screen.getByRole('button', { name: '切换接口测试' }))
      await userEvent.click(
        within(await screen.findByRole('dialog', { name: '切换请求目标？' })).getByRole('button', {
          name: '丢弃请求草稿并切换',
        }),
      )
      await screen.findByText('固定 v2')
      if (!unmount) await screen.findByText('继承接口模板 v2')
      fireEvent.click(screen.getByRole('button', { name: '应用节点配置' }))
      await waitFor(() => expect(changed).toHaveBeenCalledTimes(1))
      expect(changed.mock.calls[0][0].nodes[0].config).toMatchObject({
        api_definition_id: 'api-2',
        api_version: 2,
        request_overrides: {},
      })
    },
  )
  it.each([false, true])(
    'F02: rebases a version upgrade without old pending input (unmounted=%s)',
    async (unmount) => {
      vi.mocked(getApiDetail).mockImplementation(async (_project, id, version) => ({
        ...detail,
        version: {
          ...detail.version,
          api_definition_id: id,
          version: version ?? 3,
          body_kind: 'json',
          body: { template: version },
        },
      }))
      const session = new DraftSession()
      const changed = vi.fn()
      render(
        <RequestSessionHarness
          session={session}
          changed={changed}
          startFullscreen
          initialNode={{
            ...node,
            config: {
              api_definition_id: 'api-1',
              api_version: 1,
              request_overrides: {
                headers: { 'X-Applied': 'kept' },
                auth_disabled: true,
                suppressed_cookies: ['sid'],
              },
            },
          }}
        />,
      )
      await screen.findByText('继承接口模板 v1')
      fireEvent.click(screen.getByRole('tab', { name: 'Body' }))
      fireEvent.click(within(screen.getByRole('tabpanel')).getByText('节点自定义'))
      fireEvent.change(screen.getByRole('textbox', { name: 'JSON Body' }), {
        target: { value: '{"pending":' },
      })
      if (unmount) fireEvent.click(screen.getByRole('button', { name: '还原配置测试' }))
      await userEvent.click(screen.getByRole('button', { name: /更新至接口最新 v3/ }))
      await userEvent.click(
        within(await screen.findByRole('dialog', { name: '切换请求目标？' })).getByRole('button', {
          name: '取消切换',
        }),
      )
      expect([...session.nodeEditors.values()][0].requestDraft).toMatchObject({
        identity: { apiVersion: 1, apiDefinitionId: 'api-1' },
        activeTab: 'body',
        fields: { body_text: '{"pending":' },
      })
      await userEvent.click(screen.getByRole('button', { name: /更新至接口最新 v3/ }))
      await userEvent.click(
        within(await screen.findByRole('dialog', { name: '切换请求目标？' })).getByRole('button', {
          name: '丢弃请求草稿并切换',
        }),
      )
      await screen.findByText('固定 v3')
      if (!unmount) await screen.findByText('继承接口模板 v3')
      await userEvent.click(screen.getByRole('button', { name: '应用节点配置' }))
      await waitFor(() => expect(changed).toHaveBeenCalledTimes(1))
      expect(changed.mock.calls[0][0].nodes[0].config).toMatchObject({
        api_version: 3,
        request_overrides: {
          headers: { 'X-Applied': 'kept' },
          auth_disabled: true,
          suppressed_cookies: ['sid'],
        },
      })
      expect(changed.mock.calls[0][0].nodes[0].config.request_overrides.body).toBeUndefined()
    },
  )
  it('F02: late API A query results cannot hydrate the switched API B editor', async () => {
    let resolveA!: (value: ApiDetail) => void
    const pendingA = new Promise<ApiDetail>((resolve) => {
      resolveA = resolve
    })
    vi.mocked(getApiDetail).mockImplementation((_project, id) =>
      id === 'api-1'
        ? pendingA
        : Promise.resolve({
            ...detail,
            version: {
              ...detail.version,
              api_definition_id: id,
              version: 2,
              body_kind: 'json',
              body: { owner: 'B' },
            },
          }),
    )
    render(<RequestSessionHarness session={new DraftSession()} changed={vi.fn()} startFullscreen />)
    await waitFor(() => expect(getApiDetail).toHaveBeenCalledWith('project-1', 'api-1', 3))
    await userEvent.click(screen.getByRole('button', { name: '切换接口测试' }))
    await screen.findByText('继承接口模板 v2')
    resolveA({ ...detail, version: { ...detail.version, body_kind: 'json', body: { owner: 'A' } } })
    await userEvent.click(screen.getByRole('tab', { name: 'Body' }))
    expect(screen.getByRole('textbox', { name: 'JSON Body' })).toHaveValue(
      JSON.stringify({ owner: 'B' }, null, 2),
    )
    expect(screen.queryByText('继承接口模板 v3')).not.toBeInTheDocument()
  })
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

  it('DATA01 preserves independent request policies when applying request fields', async () => {
    vi.mocked(getApiDetail).mockResolvedValue(detail)
    const onUpdate = vi.fn()
    const policies = {
      auth_mode: 'disabled',
      auth_disabled: true,
      replace_headers: true,
      suppressed_headers: ['Authorization'],
      suppressed_query_parameters: ['debug'],
      suppressed_cookies: ['session'],
    }
    renderEditor(onUpdate, detail.definition, {
      ...node,
      config: {
        ...node.config,
        polling: { expression: 'body.ready', expected: true },
        request_overrides: { body: bodyOverride, ...policies },
      },
    })
    fireEvent.click(screen.getByRole('button', { name: /配置节点请求/ }))
    await screen.findByText('继承接口模板 v3')
    fireEvent.click(screen.getByRole('button', { name: '保存节点配置' }))
    await waitFor(() => expect(onUpdate).toHaveBeenCalledTimes(1))
    expect(onUpdate.mock.calls[0][0].config.request_overrides).toMatchObject(policies)
    expect(onUpdate.mock.calls[0][0].config.polling).toEqual({
      expression: 'body.ready',
      expected: true,
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
    vi.mocked(getApiDetail).mockResolvedValue({
      ...detail,
      version: { ...detail.version, body_kind: 'multipart' },
    })
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
    await user.click(screen.getByRole('button', { name: /预览模板请求/ }))

    expect(await screen.findByText(/file_previews/)).toBeInTheDocument()
    expect(screen.getAllByText(/fixture\.json/)).toHaveLength(2)
    expect(previewApi).toHaveBeenCalledWith('project-1', detail.definition.id, 'environment-1', {
      version: 3,
      serviceOverride: '',
      endpointVariant: '',
      queryParametersOverride: undefined,
      headersOverride: undefined,
      bodyOverride: bodyOverride.value,
      useBodyOverride: true,
    })
  })

  it('preserves the preview server error message and trace ID', async () => {
    vi.mocked(getApiDetail).mockResolvedValue({
      ...detail,
      version: { ...detail.version, body_kind: 'multipart' },
    })
    vi.mocked(previewApi).mockRejectedValue({
      isAxiosError: true,
      response: {
        data: { error: { message: '无权预览此接口', trace_id: 'preview-trace-403' } },
      },
    })
    renderEditor(vi.fn())
    fireEvent.click(screen.getByRole('button', { name: /配置节点请求/ }))
    await screen.findByText('继承接口模板 v3')
    fireEvent.click(screen.getByRole('button', { name: /预览模板请求/ }))
    expect(await screen.findByText(/无权预览此接口.*preview-trace-403/)).toBeVisible()
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

  it('FORM11 restores invalid request text, section mode, and active tab from the shared session', async () => {
    const user = userEvent.setup()
    const session = new DraftSession()
    const changed = vi.fn()
    vi.mocked(getApiDetail).mockResolvedValue({
      ...detail,
      version: { ...detail.version, body_kind: 'json', body: { initial: true } },
    })
    const view = render(<RequestSessionHarness session={session} changed={changed} />)
    await user.click(screen.getByRole('button', { name: /配置节点请求/ }))
    await screen.findByText('继承接口模板 v3')
    await user.click(screen.getByRole('tab', { name: 'Body' }))
    expect(session.unsafe.size).toBe(0)
    await user.click(within(screen.getByRole('tabpanel')).getByText('节点自定义'))
    fireEvent.change(screen.getByRole('textbox', { name: 'JSON Body' }), {
      target: { value: '{"unfinished":' },
    })
    await user.click(screen.getByRole('button', { name: '保存节点配置' }))
    expect(changed).not.toHaveBeenCalled()
    expect(session.unsafe.size).toBe(1)
    view.unmount()
    render(<RequestSessionHarness session={session} changed={changed} />)
    await user.click(screen.getByRole('button', { name: /配置节点请求/ }))
    expect(await screen.findByRole('textbox', { name: 'JSON Body' })).toHaveValue('{"unfinished":')
    expect(screen.getByRole('tab', { name: /Body/ })).toHaveAttribute('aria-selected', 'true')
    fireEvent.change(screen.getByRole('textbox', { name: 'JSON Body' }), {
      target: { value: '{"ready":true}' },
    })
    await user.click(screen.getByRole('button', { name: '保存节点配置' }))
    await waitFor(() => expect(changed).toHaveBeenCalledTimes(1))
    expect(session.unsafe.size).toBe(0)
  })

  it('applies request edits after restoring the fullscreen inspector to quick mode', async () => {
    const user = userEvent.setup()
    const session = new DraftSession()
    const changed = vi.fn()
    vi.mocked(getApiDetail).mockResolvedValue({
      ...detail,
      version: { ...detail.version, body_kind: 'json', body: { initial: true } },
    })
    render(<RequestSessionHarness session={session} changed={changed} startFullscreen />)

    await screen.findByText('继承接口模板 v3')
    await user.click(screen.getByRole('tab', { name: 'Body' }))
    await user.click(within(screen.getByRole('tabpanel')).getByText('节点自定义'))
    fireEvent.change(screen.getByRole('textbox', { name: 'JSON Body' }), {
      target: { value: '{"preserved":true}' },
    })
    await user.click(screen.getByRole('button', { name: '还原配置测试' }))
    await user.click(screen.getByRole('button', { name: '应用节点配置' }))

    await waitFor(() => expect(changed).toHaveBeenCalledTimes(1))
    expect(changed.mock.calls[0][0].nodes[0].config).toMatchObject({
      api_version: 3,
      request_overrides: { body: { kind: 'json', value: { preserved: true } } },
    })
    expect(session.unsafe.size).toBe(0)
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

function RequestSessionHarness({
  session,
  changed,
  startFullscreen = false,
  initialNode = { ...node, config: { ...node.config, request_overrides: {} } },
}: {
  session: DraftSession
  changed: (value: import('../lib/api').WorkflowDefinition) => void
  startFullscreen?: boolean
  initialNode?: WorkflowNode
}) {
  const [queryClient] = useState(
    () => new QueryClient({ defaultOptions: { queries: { retry: false } } }),
  )
  const [definition, setDefinition] = useState<import('../lib/api').WorkflowDefinition>({
    ...workflowDefinition,
    nodes: [initialNode],
  })
  const [presentation, setPresentation] = useState<'quick' | 'fullscreen'>(
    startFullscreen ? 'fullscreen' : 'quick',
  )
  return (
    <QueryClientProvider client={queryClient}>
      <DraftContext.Provider value={session}>
        <ConfigProvider theme={{ token: { motion: false } }}>
          {startFullscreen && (
            <button onClick={() => setPresentation('quick')}>还原配置测试</button>
          )}
          <WorkflowNodeEditSession
            scope="request-session:"
            projectId="project-1"
            node={definition.nodes[0]}
            definition={definition}
            editable
            onChange={(next) => {
              setDefinition(next)
              changed(next)
            }}
          >
            {(draft, update) => (
              <InspectorPresentationContext.Provider value={presentation}>
                <button
                  onClick={() =>
                    update({
                      ...definition,
                      nodes: [
                        restoreEditedNode(draft, {
                          ...editorNode(draft),
                          config: {
                            ...editorNode(draft).config,
                            api_definition_id: 'api-2',
                            api_version: 2,
                            request_overrides: {},
                          },
                        }),
                      ],
                    })
                  }
                >
                  切换接口测试
                </button>
                <WorkflowApiRequestEditor
                  node={editorNode(draft)}
                  projectId="project-1"
                  environmentId="environment-1"
                  api={detail.definition}
                  artifacts={[artifact]}
                  editable
                  onUpdate={(updated) =>
                    update({ ...definition, nodes: [restoreEditedNode(draft, updated)] })
                  }
                />
              </InspectorPresentationContext.Provider>
            )}
          </WorkflowNodeEditSession>
        </ConfigProvider>
      </DraftContext.Provider>
    </QueryClientProvider>
  )
}
