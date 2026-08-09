import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import CreateDialogs from './CreateDialogs'

const baseProps = {
  submitting: false,
  onClose: vi.fn(),
  onCreateProject: vi.fn(async () => undefined),
  onCreateEnvironment: vi.fn(async () => undefined),
  onCreateApi: vi.fn(async () => undefined),
}

describe('CreateDialogs', () => {
  it('submits a project', async () => {
    const onCreateProject = vi.fn(async () => undefined)
    render(<CreateDialogs {...baseProps} open="project" onCreateProject={onCreateProject} />)
    const browser = userEvent.setup()

    await browser.type(screen.getByLabelText('项目名称'), '支付服务')
    await browser.type(screen.getByLabelText('项目说明'), '回归测试')
    await browser.click(screen.getByRole('button', { name: 'OK' }))

    expect(onCreateProject).toHaveBeenCalledWith({ name: '支付服务', description: '回归测试' })
  })

  it('normalizes an environment payload', async () => {
    const onCreateEnvironment = vi.fn(async () => undefined)
    render(
      <CreateDialogs {...baseProps} open="environment" onCreateEnvironment={onCreateEnvironment} />,
    )
    const browser = userEvent.setup()

    await browser.type(screen.getByLabelText('环境名称'), '集成环境')
    await browser.type(screen.getByLabelText('基础 URL'), 'https://example.test')
    await browser.click(screen.getByRole('button', { name: 'OK' }))

    expect(onCreateEnvironment).toHaveBeenCalledWith({
      name: '集成环境',
      base_url: 'https://example.test',
      variables: {},
      headers: {},
    })
  })

  it('validates and parses an API JSON body', async () => {
    const onCreateApi = vi.fn(async () => undefined)
    render(<CreateDialogs {...baseProps} open="api" onCreateApi={onCreateApi} />)
    const browser = userEvent.setup()

    await browser.type(screen.getByLabelText('接口名称'), '创建订单')
    await browser.type(screen.getByLabelText('请求路径'), '/orders')
    await browser.click(screen.getByLabelText('请求体类型'))
    await browser.click(screen.getByText('JSON'))
    await browser.click(screen.getByLabelText('JSON Body'))
    await browser.paste('{invalid')
    await browser.click(screen.getByRole('button', { name: 'OK' }))
    expect(await screen.findByText('请输入有效 JSON')).toBeInTheDocument()

    await browser.clear(screen.getByLabelText('JSON Body'))
    await browser.click(screen.getByLabelText('JSON Body'))
    await browser.paste('{"amount":99}')
    await browser.click(screen.getByRole('button', { name: 'OK' }))
    expect(onCreateApi).toHaveBeenCalledWith({
      name: '创建订单',
      description: '',
      method: 'GET',
      path: '/orders',
      body_kind: 'json',
      body: { amount: 99 },
      auth: { kind: 'none', values: {} },
    })
  })

  it('builds bearer authentication and multipart file references', async () => {
    const onCreateApi = vi.fn(async () => undefined)
    render(
      <CreateDialogs
        {...baseProps}
        open="api"
        onCreateApi={onCreateApi}
        artifacts={[
          {
            id: 'file-1',
            project_id: 'project-1',
            filename: 'payload.txt',
            content_type: 'text/plain',
            size_bytes: 12,
            sha256: 'hash',
            purpose: 'upload',
            created_at: '2026-08-09T00:00:00Z',
          },
        ]}
      />,
    )
    const browser = userEvent.setup()
    await browser.type(screen.getByLabelText('接口名称'), '上传文件')
    await browser.type(screen.getByLabelText('请求路径'), '/upload')
    await browser.click(screen.getByLabelText('请求体类型'))
    await browser.click(screen.getByText('multipart 文件上传'))
    await browser.click(screen.getByLabelText('文件'))
    await browser.click(screen.getByText('payload.txt (12 B)'))
    await browser.click(screen.getByLabelText('认证方式'))
    await browser.click(screen.getByText('Bearer Token'))
    await browser.click(screen.getByRole('button', { name: 'OK' }))

    expect(onCreateApi).toHaveBeenCalledWith(
      expect.objectContaining({
        body_kind: 'multipart',
        body: { fields: {}, files: [{ field: 'file', artifact_id: 'file-1' }] },
        auth: { kind: 'bearer', values: { token: '{{secret.BEARER_TOKEN}}' } },
      }),
    )
  })

  it.each([
    {
      option: 'Basic Auth',
      expected: {
        kind: 'basic',
        values: {
          username: '{{secret.BASIC_USERNAME}}',
          password: '{{secret.BASIC_PASSWORD}}',
        },
      },
    },
    {
      option: 'API Key',
      expected: {
        kind: 'api_key',
        values: { name: 'X-API-Key', value: '{{secret.API_KEY}}', in: 'header' },
      },
    },
  ])('builds $option configuration', async ({ option, expected }) => {
    const onCreateApi = vi.fn(async () => undefined)
    render(<CreateDialogs {...baseProps} open="api" onCreateApi={onCreateApi} />)
    const browser = userEvent.setup()
    await browser.type(screen.getByLabelText('接口名称'), `${option} 接口`)
    await browser.type(screen.getByLabelText('请求路径'), '/secure')
    await browser.click(screen.getByLabelText('认证方式'))
    await browser.click(screen.getByText(option))
    await browser.click(screen.getByRole('button', { name: 'OK' }))
    expect(onCreateApi).toHaveBeenCalledWith(expect.objectContaining({ auth: expected }))
  })
})
