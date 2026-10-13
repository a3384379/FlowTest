import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App as AntdApp, ConfigProvider } from 'antd'
import { http, HttpResponse } from 'msw'
import { describe, expect, it, vi } from 'vitest'

import type { Environment } from '../../lib/api'
import type { UpdateEnvironmentInput } from './api-service'
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
  options: {
    readonly?: boolean
    empty?: boolean
    failSave?: boolean
    gate?: Promise<void>
    catalog?: Environment[]
  } = {},
) {
  server.use(http.get(`/api/v1/projects/${project.id}/services`, () => HttpResponse.json([])))
  let serverCatalog = options.catalog ?? [environment, other]
  const onSave = vi.fn().mockImplementation(async (id: string, input: UpdateEnvironmentInput) => {
    if (options.failSave) throw new Error('save failed')
    await options.gate
    const saved = { ...(serverCatalog.find((item) => item.id === id) ?? environment), ...input }
    serverCatalog = serverCatalog.map((item) => (item.id === id ? saved : item))
    return saved
  })
  const onCreate = vi.fn().mockResolvedValue(other)
  const onDelete = vi.fn().mockResolvedValue(undefined)
  const onUse = vi.fn()
  const onClose = vi.fn()
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  function tree(catalog: Environment[]) {
    return (
      <QueryClientProvider client={client}>
        <ConfigProvider theme={{ token: { motion: false } }}>
          <AntdApp>
            <EnvironmentManager
              projectId={project.id}
              environments={catalog}
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
      </QueryClientProvider>
    )
  }
  const view = render(tree(options.empty ? [] : serverCatalog))
  return {
    onSave,
    onCreate,
    onDelete,
    onUse,
    onClose,
    updateCatalog: (catalog: Environment[]) => {
      serverCatalog = catalog
      view.rerender(tree(catalog))
    },
  }
}

describe('EnvironmentManager', () => {
  it('edits another environment without changing the sending environment and applies it explicitly', async () => {
    const handlers = renderManager()
    const browser = userEvent.setup()
    await browser.click(screen.getByRole('button', { name: '编辑环境 预发环境' }))
    expect(screen.getByDisplayValue(other.base_url)).toBeVisible()
    await browser.click(screen.getByRole('button', { name: /保存配置/ }))
    await waitFor(() => expect(handlers.onSave).toHaveBeenCalledWith(other.id, {}))
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
    expect(onSave.mock.calls[1][1]).toEqual({})
    expect(screen.getByLabelText('默认地址')).toHaveValue('http://new.internal:9090')
  })

  it('refreshes untouched fields after saving when the catalog changes again', async () => {
    const { onSave, updateCatalog } = renderManager()
    fireEvent.change(screen.getByLabelText('名称'), { target: { value: '保存名称' } })
    await userEvent.click(screen.getByRole('button', { name: /保存配置/ }))
    await waitFor(() => expect(onSave).toHaveBeenCalledOnce())
    updateCatalog([
      {
        ...environment,
        name: '保存名称',
        base_url: 'http://other-team.internal:9080',
        variables: { region: 'updated' },
      },
      other,
    ])
    await waitFor(() =>
      expect(screen.getByLabelText('默认地址')).toHaveValue('http://other-team.internal:9080'),
    )
    fireEvent.change(screen.getByLabelText('名称'), { target: { value: '再次改名' } })
    await userEvent.click(screen.getByRole('button', { name: /保存配置/ }))
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(2))
    expect(onSave.mock.calls[1][1]).toEqual({ name: '再次改名' })
  })
  it('preserves dirty edits on refresh and sends only changed fields', async () => {
    const configured = { ...environment, default_service_id: 'default-service' }
    const { onSave, updateCatalog } = renderManager({ catalog: [configured, other] })
    fireEvent.change(screen.getByLabelText('名称'), { target: { value: '本地名称草稿' } })
    updateCatalog([
      {
        ...configured,
        base_url: 'http://new-server.internal:9090',
        variables: { region: 'updated' },
      },
      other,
    ])
    expect(screen.getByLabelText('名称')).toHaveValue('本地名称草稿')
    await userEvent.click(screen.getByRole('button', { name: /保存配置/ }))
    await waitFor(() =>
      expect(onSave).toHaveBeenCalledWith(environment.id, { name: '本地名称草稿' }),
    )
    expect(onSave.mock.calls[0][1]).not.toHaveProperty('default_service_id')
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
