import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import APIWorkbench from './APIWorkbench'
import type { ApiDetail, ApiVersion, Artifact } from '../../lib/api'

describe('APIWorkbench', () => {
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
