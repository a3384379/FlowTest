import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App as AntdApp, ConfigProvider } from 'antd'
import { http, HttpResponse } from 'msw'
import { describe, expect, it, vi } from 'vitest'

import { environment, project } from '../../test/fixtures'
import { server } from '../../test/server'
import EnvironmentManager from './EnvironmentManager'

const other = {
  ...environment,
  id: 'other-env',
  name: '预发环境',
  base_url: 'https://stage.example.test',
}
function renderManager(
  options: { readonly?: boolean; empty?: boolean; failSave?: boolean; gate?: Promise<void> } = {},
) {
  server.use(http.get(`/api/v1/projects/${project.id}/services`, () => HttpResponse.json([])))
  const onSave = vi.fn().mockImplementation(async (id, input) => {
    if (options.failSave) throw new Error('save failed')
    await options.gate
    return { ...(id === environment.id ? environment : other), ...input }
  })
  const onCreate = vi.fn().mockResolvedValue(other)
  const onDelete = vi.fn().mockResolvedValue(undefined)
  const onUse = vi.fn()
  const onClose = vi.fn()
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <ConfigProvider theme={{ token: { motion: false } }}>
        <AntdApp>
          <EnvironmentManager
            projectId={project.id}
            environments={options.empty ? [] : [environment, other]}
            sendingEnvironmentId={environment.id}
            editable={!options.readonly}
            canUse={!options.readonly}
            saving={false}
            deleting={false}
            onClose={onClose}
            onCreate={onCreate}
            onSave={onSave}
            onDelete={onDelete}
            onUse={onUse}
          />
        </AntdApp>
      </ConfigProvider>
    </QueryClientProvider>,
  )
  return { onSave, onCreate, onDelete, onUse, onClose }
}

describe('EnvironmentManager', () => {
  it('edits another environment without changing the sending environment and applies it explicitly', async () => {
    const handlers = renderManager()
    const browser = userEvent.setup()
    await browser.click(screen.getByRole('button', { name: '编辑环境 预发环境' }))
    expect(screen.getByDisplayValue(other.base_url)).toBeVisible()
    await browser.click(screen.getByRole('button', { name: /保存配置/ }))
    await waitFor(() =>
      expect(handlers.onSave).toHaveBeenCalledWith(
        other.id,
        expect.objectContaining({ base_url: other.base_url }),
      ),
    )
    expect(handlers.onUse).not.toHaveBeenCalled()
    await browser.click(screen.getByRole('button', { name: '用此环境调试' }))
    expect(handlers.onUse).toHaveBeenCalledWith(other.id)
    expect(handlers.onClose).not.toHaveBeenCalled()
  })
  it('validates JSON, saves typed maps, and retains drafts after save failure', async () => {
    const { onSave } = renderManager({ failSave: true })
    const browser = userEvent.setup()
    await browser.click(screen.getByRole('tab', { name: '变量与请求头' }))
    await browser.click(screen.getByRole('button', { name: '变量高级 JSON' }))
    fireEvent.change(screen.getByLabelText('变量 JSON'), { target: { value: '[]' } })
    await browser.click(screen.getByRole('button', { name: /保存配置/ }))
    expect(await screen.findByText('变量必须是 JSON 对象')).toBeVisible()
    expect(onSave).not.toHaveBeenCalled()
    fireEvent.change(screen.getByLabelText('变量 JSON'), { target: { value: '{"region":"cn"}' } })
    await browser.click(screen.getByRole('button', { name: /保存配置/ }))
    await waitFor(() =>
      expect(onSave).toHaveBeenCalledWith(
        environment.id,
        expect.objectContaining({ variables: { region: 'cn' } }),
      ),
    )
    expect(await screen.findByText('保存失败，修改已保留，请修正后重试。')).toBeVisible()
    expect(screen.getByLabelText('变量 JSON')).toHaveValue('{"region":"cn"}')
  })
  it('guards changing environments and closing with unsaved changes', async () => {
    const { onClose } = renderManager()
    const browser = userEvent.setup()
    fireEvent.change(screen.getByLabelText('名称'), { target: { value: '未保存名称' } })
    await browser.click(screen.getByRole('button', { name: '编辑环境 预发环境' }))
    expect(await screen.findByRole('button', { name: '丢弃修改并继续' })).toBeInTheDocument()
    await browser.click(screen.getByRole('button', { name: '继续编辑' }))
    expect(screen.getByLabelText('名称')).toHaveValue('未保存名称')
    await browser.click(screen.getByRole('button', { name: 'Close' }))
    expect(onClose).not.toHaveBeenCalled()
    await browser.click(await screen.findByRole('button', { name: '丢弃修改并继续' }))
    await waitFor(() => expect(onClose).toHaveBeenCalledOnce())
  })
  it('creates a first environment without applying it and disables writes for viewers', async () => {
    const { onCreate, onUse } = renderManager({ empty: true })
    fireEvent.change(screen.getByLabelText('名称'), { target: { value: '新环境' } })
    fireEvent.change(screen.getByLabelText('默认地址'), {
      target: { value: 'https://new.example.test' },
    })
    await userEvent.click(screen.getByRole('button', { name: /创建环境/ }))
    await waitFor(() =>
      expect(onCreate).toHaveBeenCalledWith({
        name: '新环境',
        base_url: 'https://new.example.test',
        variables: {},
        headers: {},
      }),
    )
    expect(onUse).not.toHaveBeenCalled()
  })
  it('uses the returned saved environment while catalog props still contain the old values', async () => {
    const { onSave } = renderManager()
    fireEvent.change(screen.getByLabelText('名称'), { target: { value: '已保存的新名称' } })
    fireEvent.change(screen.getByLabelText('默认地址'), {
      target: { value: 'http://new.internal:9090' },
    })
    await userEvent.click(screen.getByRole('button', { name: /保存配置/ }))
    await waitFor(() => expect(onSave).toHaveBeenCalledOnce())
    await waitFor(() => expect(screen.getByLabelText('名称')).toHaveValue('已保存的新名称'))
    expect(screen.getByLabelText('默认地址')).toHaveValue('http://new.internal:9090')
    await userEvent.click(screen.getByRole('button', { name: /保存配置/ }))
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(2))
    expect(onSave.mock.calls[1][1]).toEqual(
      expect.objectContaining({ name: '已保存的新名称', base_url: 'http://new.internal:9090' }),
    )
  })
  it('keeps the editor locked until saving and catalog refresh both finish', async () => {
    let release!: () => void
    const gate = new Promise<void>((resolve) => {
      release = resolve
    })
    const { onSave } = renderManager({ gate })
    const browser = userEvent.setup()
    fireEvent.change(screen.getByLabelText('名称'), { target: { value: '待刷新的配置' } })
    await browser.click(screen.getByRole('button', { name: /保存配置/ }))
    await waitFor(() => expect(onSave).toHaveBeenCalledOnce())
    expect(screen.getByRole('button', { name: '编辑环境 预发环境' })).toBeDisabled()
    expect(screen.getByRole('button', { name: /新建环境/ })).toBeDisabled()
    expect(screen.getByRole('button', { name: '用此环境调试' })).toBeDisabled()
    release()
    await waitFor(() =>
      expect(screen.getByRole('button', { name: '编辑环境 预发环境' })).toBeEnabled(),
    )
  })
  it('allows viewers to browse configurations without writable controls', async () => {
    renderManager({ readonly: true })
    await userEvent.click(screen.getByRole('button', { name: '编辑环境 预发环境' }))
    expect(screen.getByDisplayValue(other.base_url)).toBeDisabled()
    expect(screen.getByRole('button', { name: /保存配置/ })).toBeDisabled()
    expect(screen.getByRole('button', { name: /删除环境/ })).toBeDisabled()
    expect(screen.getByRole('button', { name: /新建环境/ })).toBeDisabled()
  })
})
