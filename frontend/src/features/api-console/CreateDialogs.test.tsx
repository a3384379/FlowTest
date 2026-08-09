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
    await browser.click(screen.getByLabelText('JSON Body（可选）'))
    await browser.paste('{invalid')
    await browser.click(screen.getByRole('button', { name: 'OK' }))
    expect(await screen.findByText('请输入有效 JSON')).toBeInTheDocument()

    await browser.clear(screen.getByLabelText('JSON Body（可选）'))
    await browser.click(screen.getByLabelText('JSON Body（可选）'))
    await browser.paste('{"amount":99}')
    await browser.click(screen.getByRole('button', { name: 'OK' }))
    expect(onCreateApi).toHaveBeenCalledWith({
      name: '创建订单',
      description: '',
      method: 'GET',
      path: '/orders',
      body: { amount: 99 },
    })
  })
})
