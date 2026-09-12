import { ConfigProvider } from 'antd'
import { createMemoryRouter, RouterProvider, Link, Outlet } from 'react-router-dom'
import { DraftSessionProvider } from '../drafts/DraftSessionProvider'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import APIWorkbench from './APIWorkbench'
import type { ApiDetail, ApiVersion, Artifact } from '../../lib/api'

describe('APIWorkbench', () => {
  afterEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
  })

  it('restores independent local API edits and clears them after save', async () => {
    const user = userEvent.setup()
    const onSave = vi.fn(async (input) => ({ ...detail.version, ...input, version: 2 }))
    const props = {
      detail,
      loading: false,
      saving: false,
      previewing: false,
      onSave,
      onPreview: vi.fn(),
      onRename: vi.fn(),
      draftScope: 'user-1:project-1',
    }
    const first = render(<APIWorkbench {...props} />)
    const path = screen.getByPlaceholderText('/api/users/{{user_id}}')
    await user.clear(path)
    await user.type(path, '/locally-edited')
    expect(await screen.findByText('本地未保存')).toBeInTheDocument()
    first.unmount()

    render(<APIWorkbench {...props} />)
    expect(await screen.findByDisplayValue('/locally-edited')).toBeVisible()
    await user.click(screen.getByRole('button', { name: /保存新版本/ }))
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1))
    expect(screen.queryByText('本地未保存')).not.toBeInTheDocument()
  })

  it('retains a newer A draft after an A to B to A save race, including another project', async () => {
    let finish!: (value: ApiVersion) => void
    const onSave = vi.fn(
      () =>
        new Promise<ApiVersion>((resolve) => {
          finish = resolve
        }),
    )
    const common = {
      loading: false,
      saving: false,
      previewing: false,
      onSave,
      onPreview: vi.fn(),
      onRename: vi.fn(),
    }
    const view = (resource: ApiDetail, scope = 'aba:project-a') => (
      <APIWorkbench {...common} detail={resource} draftScope={scope} />
    )
    const rendered = render(view(detail))
    fireEvent.change(screen.getByPlaceholderText('/api/users/{{user_id}}'), {
      target: { value: '/submitted-a' },
    })
    fireEvent.click(screen.getByRole('button', { name: /保存新版本/ }))
    await waitFor(() => expect(onSave).toHaveBeenCalledOnce())
    rendered.rerender(view({ ...detail, definition: { ...detail.definition, id: 'b' } }))
    rendered.rerender(view(detail, 'aba:project-b'))
    fireEvent.change(screen.getByPlaceholderText('/api/users/{{user_id}}'), {
      target: { value: '/project-b' },
    })
    rendered.rerender(view(detail))
    fireEvent.change(screen.getByPlaceholderText('/api/users/{{user_id}}'), {
      target: { value: '/newer-a' },
    })
    finish({ ...detail.version, version: 2, path: '/submitted-a' })
    expect(await screen.findByDisplayValue('/newer-a')).toBeVisible()
    expect(screen.getByText('本地未保存')).toBeVisible()
    const key = `flowtest:api-draft:v1:${encodeURIComponent('aba:project-a')}:${detail.definition.id}`
    expect(JSON.parse(localStorage.getItem(key)!).path).toBe('/newer-a')
    rendered.rerender(view(detail, 'aba:project-b'))
    expect(await screen.findByDisplayValue('/project-b')).toBeVisible()
  })

  it('refreshes a clean baseline but retains and flags dirty edits on server updates', async () => {
    const props = {
      loading: false,
      saving: false,
      previewing: false,
      onSave: vi.fn(),
      onPreview: vi.fn(),
      onRename: vi.fn(),
      draftScope: 'refresh:project',
    }
    const rendered = render(<APIWorkbench {...props} detail={detail} />)
    rendered.rerender(
      <APIWorkbench
        {...props}
        detail={{ ...detail, version: { ...detail.version, version: 2, path: '/server-v2' } }}
      />,
    )
    expect(await screen.findByDisplayValue('/server-v2')).toBeVisible()
    fireEvent.change(screen.getByPlaceholderText('/api/users/{{user_id}}'), {
      target: { value: '/dirty-v2' },
    })
    rendered.rerender(
      <APIWorkbench
        {...props}
        detail={{ ...detail, version: { ...detail.version, version: 3, path: '/server-v3' } }}
      />,
    )
    expect(await screen.findByDisplayValue('/dirty-v2')).toBeVisible()
    expect(await screen.findByText('服务器有新版本，已保留本地编辑，请核对后保存')).toBeVisible()
  })

  it('guards real SPA links and restores memory drafts after editor unmount with failed storage', async () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('quota')
    })
    const user = userEvent.setup()
    const router = createMemoryRouter(
      [
        {
          element: (
            <DraftSessionProvider>
              <Link to="/other">侧栏变量</Link>
              <Link to="/api">接口模块</Link>
              <Outlet />
            </DraftSessionProvider>
          ),
          children: [
            {
              path: '/api',
              element: (
                <APIWorkbench
                  detail={detail}
                  loading={false}
                  saving={false}
                  previewing={false}
                  onSave={vi.fn()}
                  onPreview={vi.fn()}
                  onRename={vi.fn()}
                  draftScope="spa:project"
                />
              ),
            },
            { path: '/other', element: <div>变量模块内容</div> },
          ],
        },
      ],
      { initialEntries: ['/api'] },
    )
    render(
      <ConfigProvider theme={{ token: { motion: false } }}>
        <RouterProvider router={router} />
      </ConfigProvider>,
    )
    fireEvent.change(await screen.findByPlaceholderText('/api/users/{{user_id}}'), {
      target: { value: '/memory-only' },
    })
    await user.click(screen.getByRole('link', { name: '侧栏变量' }))
    await waitFor(() => expect(screen.getByText('草稿尚未持久化')).toBeVisible())
    await user.click(screen.getByRole('button', { name: '留在当前页保存' }))
    expect(screen.getByDisplayValue('/memory-only')).toBeVisible()
    await user.click(screen.getByRole('link', { name: '侧栏变量' }))
    await user.click(screen.getByRole('button', { name: '保留草稿并切换' }))
    expect(await screen.findByText('变量模块内容')).toBeVisible()
    const unload = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(unload)
    expect(unload.defaultPrevented).toBe(true)
    await user.click(screen.getByRole('link', { name: '接口模块' }))
    await user.click(screen.getByRole('button', { name: '保留草稿并切换' }))
    expect(await screen.findByDisplayValue('/memory-only')).toBeVisible()
    expect(screen.getByText('本地未保存')).toBeVisible()
  })

  it('renders loading and empty states without a selected API', () => {
    const common = {
      saving: false,
      previewing: false,
      onSave: vi.fn(),
      onPreview: vi.fn(),
      onRename: vi.fn(),
    }
    const loading = render(<APIWorkbench {...common} loading />)
    expect(document.querySelector('.ant-skeleton')).toBeInTheDocument()
    loading.unmount()
    render(<APIWorkbench {...common} loading={false} />)
    expect(screen.getByText('请选择接口后进行持续编辑')).toBeVisible()
  })

  it('keeps edits visible and warns when browser draft storage is unavailable', async () => {
    const scope = 'user-storage:project-storage'
    const key = `flowtest:api-draft:v1:${encodeURIComponent(scope)}:${detail.definition.id}`
    localStorage.setItem(key, '{corrupt')
    const setItem = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('Storage is unavailable')
    })
    const removeItem = vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => {
      throw new DOMException('Storage is unavailable')
    })
    const user = userEvent.setup()
    render(
      <APIWorkbench
        detail={detail}
        loading={false}
        saving={false}
        previewing={false}
        onSave={vi.fn(async (input) => ({ ...detail.version, ...input, version: 2 }))}
        onPreview={vi.fn()}
        onRename={vi.fn()}
        draftScope={scope}
      />,
    )

    const path = await screen.findByPlaceholderText('/api/users/{{user_id}}')
    await user.clear(path)
    await user.type(path, '/kept-in-form')
    expect(screen.getByDisplayValue('/kept-in-form')).toBeVisible()
    expect(screen.getByText('浏览器无法持久化草稿，请先保存再离开')).toBeVisible()
    const unload = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(unload)
    expect(unload.defaultPrevented).toBe(true)
    await user.click(screen.getByRole('button', { name: /保存新版本/ }))
    expect(await screen.findByDisplayValue('/kept-in-form')).toBeVisible()

    setItem.mockRestore()
    removeItem.mockRestore()
  })

  it('keeps edits made while an API save is pending as the next local draft', async () => {
    const scope = 'user-race:project-race'
    let finishSave: ((value: ApiVersion) => void) | undefined
    const onSave = vi.fn(
      () =>
        new Promise<ApiVersion>((resolve) => {
          finishSave = resolve
        }),
    )
    const user = userEvent.setup()
    const rendered = render(
      <APIWorkbench
        detail={detail}
        loading={false}
        saving={false}
        previewing={false}
        onSave={onSave}
        onPreview={vi.fn()}
        onRename={vi.fn()}
        draftScope={scope}
      />,
    )
    const path = await screen.findByPlaceholderText('/api/users/{{user_id}}')
    await user.clear(path)
    await user.type(path, '/submitted')
    await user.click(screen.getByRole('button', { name: /保存新版本/ }))
    await user.clear(path)
    await user.type(path, '/edited-while-saving')
    rendered.rerender(
      <APIWorkbench
        detail={{ ...detail, version: { ...detail.version, path: '/submitted', version: 2 } }}
        loading={false}
        saving
        previewing={false}
        onSave={onSave}
        onPreview={vi.fn()}
        onRename={vi.fn()}
        draftScope={scope}
      />,
    )
    finishSave?.({ ...detail.version, path: '/submitted', version: 2 })

    expect(await screen.findByDisplayValue('/edited-while-saving')).toBeVisible()
    expect(screen.getByText('本地未保存')).toBeVisible()
    const key = `flowtest:api-draft:v1:${encodeURIComponent(scope)}:${detail.definition.id}`
    expect(JSON.parse(localStorage.getItem(key) ?? '{}').path).toBe('/edited-while-saving')
  })

  it('does not clear the newly selected API when the previous save finishes', async () => {
    const scope = 'user-switch:project-switch'
    let finishSave: ((value: ApiVersion) => void) | undefined
    const onSave = vi.fn(
      () =>
        new Promise<ApiVersion>((resolve) => {
          finishSave = resolve
        }),
    )
    const user = userEvent.setup()
    const rendered = render(
      <APIWorkbench
        detail={detail}
        loading={false}
        saving={false}
        previewing={false}
        onSave={onSave}
        onPreview={vi.fn()}
        onRename={vi.fn()}
        draftScope={scope}
      />,
    )
    const firstPath = await screen.findByPlaceholderText('/api/users/{{user_id}}')
    await user.clear(firstPath)
    await user.type(firstPath, '/first-draft')
    await user.click(screen.getByRole('button', { name: /保存新版本/ }))
    await waitFor(() => expect(finishSave).toBeTypeOf('function'))
    const nextDetail = {
      ...detail,
      definition: { ...detail.definition, id: 'api-definition-2', name: '第二个接口' },
      version: { ...detail.version, path: '/second-api' },
    }
    rendered.rerender(
      <APIWorkbench
        detail={nextDetail}
        loading={false}
        saving={false}
        previewing={false}
        onSave={onSave}
        onPreview={vi.fn()}
        onRename={vi.fn()}
        draftScope={scope}
      />,
    )
    finishSave?.({ ...detail.version, path: '/first-draft', version: 2 })

    expect(await screen.findByDisplayValue('/second-api')).toBeVisible()
    const firstKey = `flowtest:api-draft:v1:${encodeURIComponent(scope)}:${detail.definition.id}`
    expect(JSON.parse(localStorage.getItem(firstKey) ?? '{}').path).toBe('/first-draft')
  })

  it('edits a selected API continuously and saves a new typed version', async () => {
    const user = userEvent.setup()
    const onSave = vi.fn(async (input) => ({ ...detail.version, ...input, version: 2 }))
    const onRename = vi.fn()
    render(
      <APIWorkbench
        detail={detail}
        loading={false}
        saving={false}
        previewing={false}
        onSave={onSave}
        onPreview={vi.fn(async () => ({ url: 'https://api.example.com/users' }))}
        onRename={onRename}
      />,
    )

    expect(await screen.findByText('查询用户')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '重命名接口' }))
    expect(onRename).toHaveBeenCalledTimes(1)
    const path = screen.getByPlaceholderText('/api/users/{{user_id}}')
    fireEvent.change(path, { target: { value: '/users/{id}' } })
    await user.click(screen.getByRole('tab', { name: 'Params' }))
    await user.click(screen.getByRole('button', { name: /添加一行/ }))
    await user.type(screen.getByPlaceholderText('参数名'), 'verbose')
    await user.type(screen.getByPlaceholderText('值或 {{变量}}'), 'true')
    await user.click(screen.getByRole('button', { name: /保存新版本/ }))

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1))
    expect(onSave.mock.calls[0][0]).toEqual(
      expect.objectContaining({
        method: 'GET',
        path: '/users/{id}',
        query_parameters: [{ enabled: true, name: 'verbose', value: 'true' }],
        extraction_rules: [{ name: 'user_id', kind: 'jsonpath', expression: '$.data.id' }],
      }),
    )
  })

  it('shows the final resolved request preview', async () => {
    const user = userEvent.setup()
    const onPreview = vi.fn(async () => ({
      method: 'GET',
      url: 'https://api.example.com/users',
      headers: [{ name: 'Authorization', value: '******', source: 'api' }],
    }))
    render(
      <APIWorkbench
        detail={detail}
        loading={false}
        saving={false}
        previewing={false}
        onSave={vi.fn()}
        onPreview={onPreview}
        onRename={vi.fn()}
      />,
    )
    await user.click(await screen.findByRole('button', { name: '预览最终请求' }))
    expect(await screen.findByText(/api\.example\.com\/users/)).toBeInTheDocument()
    expect(screen.getByText(/\*\*\*\*\*\*/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Close' }))
    await waitFor(() => expect(screen.getByRole('dialog')).toHaveClass('ant-zoom-leave-active'))
  })

  it('validates JSON and supports adding and removing every structured rule', async () => {
    const user = userEvent.setup()
    const onSave = vi.fn(async (input) => ({ ...detail.version, ...input, version: 2 }))
    render(
      <APIWorkbench
        detail={detail}
        loading={false}
        saving={false}
        previewing={false}
        onSave={onSave}
        onPreview={vi.fn()}
        onRename={vi.fn()}
      />,
    )

    await user.click(screen.getByRole('tab', { name: 'Headers' }))
    let panel = screen.getByRole('tabpanel')
    await user.click(within(panel).getByRole('button', { name: '删除配置行' }))
    await user.click(within(panel).getByRole('button', { name: /添加一行/ }))
    await user.type(within(panel).getByPlaceholderText('名称'), 'X-Region')
    await user.type(within(panel).getByPlaceholderText('值或 {{secret.NAME}}'), 'cn')

    await user.click(screen.getByRole('tab', { name: 'Body' }))
    panel = screen.getByRole('tabpanel')
    expect(within(panel).getByText('该请求不发送 Body')).toBeVisible()
    await user.click(within(panel).getByText('raw', { exact: true }))
    const body = within(panel).getByPlaceholderText(/"name": "demo"/)
    fireEvent.change(body, { target: { value: '{invalid' } })
    await user.click(screen.getByRole('button', { name: /保存新版本/ }))
    expect(await screen.findByText('Body 请输入有效 JSON')).toBeInTheDocument()
    fireEvent.change(body, { target: { value: '{"enabled":true}' } })

    await user.click(screen.getByRole('tab', { name: '提取' }))
    panel = screen.getByRole('tabpanel')
    await user.click(within(panel).getByRole('button', { name: '删除配置行' }))
    await user.click(within(panel).getByRole('button', { name: /添加一行/ }))
    await user.type(within(panel).getByPlaceholderText('变量名'), 'trace_id')
    await user.type(within(panel).getByPlaceholderText('$.data.token'), '$.trace_id')

    await user.click(screen.getByRole('tab', { name: '断言' }))
    panel = screen.getByRole('tabpanel')
    await user.click(within(panel).getByRole('button', { name: '删除配置行' }))
    await user.click(within(panel).getByRole('button', { name: /添加一行/ }))
    await user.type(within(panel).getByPlaceholderText('目标（可选）'), '$.status')
    await user.clear(within(panel).getByPlaceholderText('预期值（JSON 或文本）'))
    await user.type(within(panel).getByPlaceholderText('预期值（JSON 或文本）'), 'created')
    await user.click(within(panel).getByRole('button', { name: /添加一行/ }))
    const expectedValues = within(panel).getAllByPlaceholderText('预期值（JSON 或文本）')
    await user.clear(expectedValues[1])
    await user.click(screen.getByRole('button', { name: /保存新版本/ }))

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1))
    expect(onSave.mock.calls[0][0]).toMatchObject({
      headers: { 'X-Region': 'cn' },
      body: { enabled: true },
      extraction_rules: [{ name: 'trace_id', kind: 'jsonpath', expression: '$.trace_id' }],
      assertions: [
        { kind: 'status_code', operator: 'equals', target: '$.status', expected: 'created' },
        { kind: 'status_code', operator: 'equals', target: null, expected: null },
      ],
    })
  })

  it('shows an empty state before an API is selected', () => {
    render(
      <APIWorkbench
        loading={false}
        saving={false}
        previewing={false}
        onSave={vi.fn()}
        onPreview={vi.fn()}
        onRename={vi.fn()}
      />,
    )
    expect(screen.getByText('请选择接口后进行持续编辑')).toBeInTheDocument()
  })

  it('formats an existing JSON body for editing', async () => {
    const user = userEvent.setup()
    render(
      <APIWorkbench
        detail={{ ...detail, version: { ...version, body_kind: 'json', body: { active: true } } }}
        loading={false}
        saving={false}
        previewing={false}
        onSave={vi.fn()}
        onPreview={vi.fn()}
        onRename={vi.fn()}
      />,
    )
    await user.click(screen.getByRole('tab', { name: 'Body' }))
    expect(screen.getByDisplayValue(/"active": true/)).toBeInTheDocument()
  })

  it('saves raw text and form-urlencoded bodies without JSON parsing', async () => {
    const user = userEvent.setup()
    const onSave = vi.fn(async (input) => ({ ...detail.version, ...input, version: 2 }))
    render(
      <APIWorkbench
        detail={detail}
        loading={false}
        saving={false}
        previewing={false}
        onSave={onSave}
        onPreview={vi.fn()}
        onRename={vi.fn()}
      />,
    )

    await user.click(screen.getByRole('tab', { name: 'Body' }))
    let panel = screen.getByRole('tabpanel')
    await user.click(within(panel).getByText('raw', { exact: true }))
    await user.click(within(panel).getByLabelText('raw 数据类型'))
    await user.click(screen.getAllByText('Text', { exact: true }).at(-1)!)
    await user.type(within(panel).getByLabelText('原始 Body'), '<not-json>')
    await user.click(screen.getByRole('button', { name: /保存新版本/ }))

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1))
    expect(onSave.mock.calls[0][0]).toMatchObject({
      body_kind: 'raw',
      body: '<not-json>',
      headers: { 'Content-Type': 'text/plain' },
    })

    onSave.mockClear()
    await user.click(within(panel).getByText('x-www-form-urlencoded', { exact: true }))
    panel = screen.getByRole('tabpanel')
    await user.click(within(panel).getByRole('button', { name: '批量编辑' }))
    fireEvent.change(within(panel).getByLabelText('批量编辑 x-www-form-urlencoded'), {
      target: { value: 'username: demo\npassword: {{secret.PASSWORD}}' },
    })
    await user.click(within(panel).getByRole('button', { name: '应用并返回表格' }))
    await user.click(screen.getByRole('button', { name: /保存新版本/ }))

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1))
    expect(onSave.mock.calls[0][0]).toMatchObject({
      body_kind: 'form',
      body: { username: 'demo', password: '{{secret.PASSWORD}}' },
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    })
  })

  it('builds multipart text and file rows from the artifact repository', async () => {
    const user = userEvent.setup()
    const onSave = vi.fn(async (input) => ({ ...detail.version, ...input, version: 2 }))
    render(
      <APIWorkbench
        detail={detail}
        loading={false}
        saving={false}
        previewing={false}
        onSave={onSave}
        onPreview={vi.fn()}
        onRename={vi.fn()}
        artifacts={[artifact]}
      />,
    )

    await user.click(screen.getByRole('tab', { name: 'Body' }))
    const panel = screen.getByRole('tabpanel')
    await user.click(within(panel).getByText('form-data', { exact: true }))
    await user.click(within(panel).getByRole('button', { name: /添加一行/ }))
    await user.type(within(panel).getByPlaceholderText('Key'), 'description')
    await user.type(within(panel).getByPlaceholderText('Value 或 {{变量}}'), 'avatar')
    await user.click(within(panel).getByRole('button', { name: /添加一行/ }))
    await user.type(within(panel).getAllByPlaceholderText('Key')[1], 'file')
    await user.click(within(panel).getAllByLabelText('form-data 字段类型')[1])
    await user.click(screen.getByText('File', { exact: true }))
    await user.click(within(panel).getByLabelText('form-data 文件'))
    await user.click(screen.getByText('payload.txt (12 B)', { exact: true }))
    await user.click(screen.getByRole('button', { name: /保存新版本/ }))

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1))
    expect(onSave.mock.calls[0][0]).toMatchObject({
      body_kind: 'multipart',
      body: {
        fields: { description: 'avatar' },
        files: [{ field: 'file', artifact_id: 'artifact-1' }],
      },
    })
  })

  it('applies bulk Params and Headers without exposing an existing sensitive value', async () => {
    const user = userEvent.setup()
    const onSave = vi.fn(async (input) => ({ ...detail.version, ...input, version: 2 }))
    const sensitiveDetail: ApiDetail = {
      ...detail,
      version: {
        ...detail.version,
        headers: { Authorization: 'Bearer legacy-token', Accept: 'application/json' },
      },
    }
    render(
      <APIWorkbench
        detail={sensitiveDetail}
        loading={false}
        saving={false}
        previewing={false}
        onSave={onSave}
        onPreview={vi.fn()}
        onRename={vi.fn()}
        redactionMode="on"
        draftScope="bulk-user:bulk-project"
      />,
    )

    await user.click(screen.getByRole('tab', { name: 'Params' }))
    let panel = screen.getByRole('tabpanel')
    await user.click(within(panel).getByRole('button', { name: '批量编辑' }))
    fireEvent.change(within(panel).getByLabelText('批量编辑 Params'), {
      target: {
        value: 'source: s14\nsource: duplicate\n# callback: https://example.test/result',
      },
    })
    await user.click(within(panel).getByRole('button', { name: '应用并返回表格' }))

    await user.click(screen.getByRole('tab', { name: 'Headers' }))
    panel = screen.getByRole('tabpanel')
    await user.click(within(panel).getByRole('button', { name: '批量编辑' }))
    const headers = within(panel).getByLabelText('批量编辑 Headers')
    expect((headers as HTMLTextAreaElement).value).toContain('Authorization: ******')
    expect((headers as HTMLTextAreaElement).value).not.toContain('legacy-token')
    fireEvent.change(headers, {
      target: { value: 'Authorization: ******\nX-Region: cn' },
    })
    await user.click(within(panel).getByRole('button', { name: '应用并返回表格' }))
    await user.click(screen.getByRole('button', { name: /保存新版本/ }))

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1))
    expect(onSave.mock.calls[0][0]).toMatchObject({
      query_parameters: [
        { enabled: true, name: 'source', value: 's14' },
        { enabled: true, name: 'source', value: 'duplicate' },
        { enabled: false, name: 'callback', value: 'https://example.test/result' },
      ],
      headers: { Authorization: 'Bearer legacy-token', 'X-Region': 'cn' },
    })
  })

  it('shows sensitive API fields as ordinary inputs when redaction is off', async () => {
    const user = userEvent.setup()
    const sensitiveDetail: ApiDetail = {
      ...detail,
      version: {
        ...detail.version,
        headers: { Authorization: 'Bearer synthetic-token' },
        auth_config: { token: 'Bearer synthetic-token' },
      },
    }
    render(
      <APIWorkbench
        detail={sensitiveDetail}
        loading={false}
        saving={false}
        previewing={false}
        onSave={vi.fn()}
        onPreview={vi.fn()}
        onRename={vi.fn()}
      />,
    )

    await user.click(screen.getByRole('tab', { name: 'Headers' }))
    expect(
      within(screen.getByRole('tabpanel')).getByDisplayValue('Bearer synthetic-token'),
    ).toHaveAttribute('type', 'text')
    await user.click(screen.getByRole('tab', { name: 'Auth' }))
    expect(
      within(screen.getByRole('tabpanel')).getByDisplayValue('Bearer synthetic-token'),
    ).toHaveAttribute('type', 'text')
  })
})

const version: ApiVersion = {
  id: 'version-1',
  api_definition_id: 'api-1',
  version: 1,
  method: 'GET',
  path: '/users',
  query_parameters: [],
  headers: { Accept: 'application/json' },
  body_kind: 'none',
  body: null,
  auth_kind: 'bearer',
  auth_config: { token: '{{secret.API_TOKEN}}' },
  extraction_rules: [{ name: 'user_id', kind: 'jsonpath', expression: '$.data.id' }],
  assertions: [{ kind: 'status_code', operator: 'equals', target: null, expected: 200 }],
  created_at: '2026-08-09T00:00:00Z',
}

const detail: ApiDetail = {
  definition: {
    id: 'api-1',
    project_id: 'project-1',
    folder_id: null,
    name: '查询用户',
    description: '',
    current_version: 1,
    is_active: true,
  },
  version,
}

const artifact: Artifact = {
  id: 'artifact-1',
  project_id: 'project-1',
  filename: 'payload.txt',
  content_type: 'text/plain',
  size_bytes: 12,
  sha256: 'hash',
  purpose: 'upload',
  created_at: '2026-08-09T00:00:00Z',
}
