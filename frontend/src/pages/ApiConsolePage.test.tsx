import { createIceTheme } from '../theme/ice-theme'
import { useAuthStore } from '../features/auth/auth-store'
import { authenticateTestUser } from '../test/auth'
import { user as authenticatedUser } from '../test/fixtures'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App as AntdApp, ConfigProvider } from 'antd'
import { http, HttpResponse } from 'msw'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import ApiConsolePage from './ApiConsolePage'
import WorkspaceObjectTabs from '../features/navigation/WorkspaceObjectTabs'
import { apiDefinition, environment, executionDetail, project, user } from '../test/fixtures'
import type { ExecutionDetail } from '../lib/api'
import { server } from '../test/server'
import ProjectTestProvider from '../test/ProjectTestProvider'

beforeEach(() => {
  authenticateTestUser(authenticatedUser)
  server.use(
    http.get(`/api/v1/projects/${project.id}/folders`, () => HttpResponse.json([])),
    http.get(`/api/v1/projects/${project.id}/services`, () => HttpResponse.json([])),
    http.get(
      `/api/v1/projects/${project.id}/environments/${environment.id}/service-endpoints`,
      () => HttpResponse.json([]),
    ),
    http.get(`/api/v1/projects/${project.id}/apis/${apiDefinition.id}/versions`, () =>
      HttpResponse.json([{ version: 1 }]),
    ),
    http.post(`/api/v1/projects/${project.id}/apis/${apiDefinition.id}/preview`, () =>
      HttpResponse.json({
        url: `${environment.base_url}/users/me`,
        target: { environment_name: environment.name },
      }),
    ),
    http.get('/api/v1/projects', () =>
      HttpResponse.json({ items: [project], total: 1, page: 1, page_size: 100 }),
    ),
    http.get(`/api/v1/projects/${project.id}/apis`, () =>
      HttpResponse.json({ items: [apiDefinition], total: 1, page: 1, page_size: 50 }),
    ),
    http.get(`/api/v1/projects/${project.id}/environments`, () => HttpResponse.json([environment])),
    http.get(`/api/v1/projects/${project.id}/apis/${apiDefinition.id}`, () =>
      HttpResponse.json({
        definition: apiDefinition,
        version: {
          id: 'api-v1',
          api_definition_id: apiDefinition.id,
          version: 1,
          method: 'GET',
          path: '/users/me',
          query_parameters: [],
          headers: {},
          body_kind: 'none',
          body: null,
          auth_kind: 'none',
          auth_config: {},
          extraction_rules: [],
          assertions: [],
          created_at: '2026-08-09T08:00:00Z',
        },
      }),
    ),
    http.get(`/api/v1/projects/${project.id}/executions`, () =>
      HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 }),
    ),
    http.get(`/api/v1/projects/${project.id}/files`, () =>
      HttpResponse.json({ items: [], total: 0, page: 1, page_size: 100 }),
    ),
  )
})
afterEach(() => {
  useAuthStore.setState({ user: null })
  localStorage.clear()
})

describe('ApiConsolePage', () => {
  it.each(['directory', 'detail', 'both'] as const)(
    'does not use an old owner role after the %s project summary fails',
    async (failure) => {
      authenticateTestUser({ ...authenticatedUser, is_system_admin: false })
      const { queryClient } = renderPage()
      const create = await screen.findByRole('button', { name: '新建接口' })
      await waitFor(() => expect(create).toBeEnabled())
      const error = () =>
        HttpResponse.json(
          { error: { code: 'UNAVAILABLE', message: '项目摘要暂不可用', trace_id: 'role-refresh' } },
          { status: 503 },
        )
      server.use(
        http.get('/api/v1/projects', () =>
          failure === 'detail'
            ? HttpResponse.json({
                items: [{ ...project, role: 'viewer' }],
                total: 1,
                page: 1,
                page_size: 100,
              })
            : error(),
        ),
        http.get(`/api/v1/projects/${project.id}`, () =>
          failure === 'directory' ? HttpResponse.json({ ...project, role: 'viewer' }) : error(),
        ),
      )
      await act(async () => {
        await Promise.all([
          queryClient.invalidateQueries({ queryKey: ['projects'] }),
          queryClient.invalidateQueries({ queryKey: ['project', project.id] }),
        ])
      })
      await waitFor(() => expect(create).toBeDisabled())
    },
  )
  it.each([false, true])(
    'updates an inactive opened object tab after renaming that API from the real directory (late detail=%s)',
    async (lateDetail) => {
      const secondId = '00000000-0000-4000-8000-000000000998'
      let second = { ...apiDefinition, id: secondId, name: '接口B原名' }
      let writes = 0
      let secondReads = 0
      let delayNextRead = false
      let delayedReadStarted = false
      let release!: () => void
      const pending = new Promise<void>((resolve) => {
        release = resolve
      })
      const detailFor = (definition: typeof apiDefinition) => ({
        definition,
        version: {
          id: `version-${definition.id}`,
          api_definition_id: definition.id,
          version: 1,
          method: 'GET',
          path: '/users/me',
          query_parameters: [],
          headers: {},
          body_kind: 'none',
          body: null,
          auth_kind: 'none',
          auth_config: {},
          extraction_rules: [],
          assertions: [],
          created_at: '2026-08-09T00:00:00Z',
        },
      })
      server.use(
        http.get(`/api/v1/projects/${project.id}/apis`, () =>
          HttpResponse.json({ items: [apiDefinition, second], total: 2, page: 1, page_size: 50 }),
        ),
        http.post(`/api/v1/projects/${project.id}/apis/${secondId}/preview`, () =>
          HttpResponse.json({
            url: `${environment.base_url}/users/me`,
            target: { environment_name: environment.name },
          }),
        ),
        http.get(`/api/v1/projects/${project.id}/apis/${secondId}/versions`, () =>
          HttpResponse.json([{ version: 1 }]),
        ),
        http.get(`/api/v1/projects/${project.id}/apis/${secondId}`, async () => {
          secondReads += 1
          const snapshot = detailFor(second)
          if (delayNextRead) {
            delayNextRead = false
            delayedReadStarted = true
            await pending
          }
          return HttpResponse.json(snapshot)
        }),
        http.patch(`/api/v1/projects/${project.id}/apis/${secondId}`, async ({ request }) => {
          expect(await request.json()).toEqual({ name: '接口B新名' })
          writes += 1
          second = { ...second, name: '接口B新名' }
          return HttpResponse.json(second)
        }),
      )
      const { queryClient: client } = renderPage(
        `/projects/${project.id}/apis?focus=${secondId}`,
        true,
      )
      const browser = userEvent.setup()
      try {
        const tabs = within(screen.getByLabelText('全局对象工作区'))
        const directoryElement = screen.getByLabelText('接口目录')
        expect(directoryElement).toHaveRole('complementary')
        const directory = within(directoryElement)
        expect(await tabs.findByRole('tab', { name: '接口 · 接口B原名' })).toBeVisible()
        const draftPath = screen.getByLabelText('请求路径')
        await browser.clear(draftPath)
        await browser.click(draftPath)
        await browser.paste('/local-draft-b')
        let delayedRead = Promise.resolve()
        if (lateDetail) {
          delayNextRead = true
          await act(async () => {
            delayedRead = client.invalidateQueries({
              queryKey: ['api-detail', project.id, secondId],
            })
          })
          await waitFor(() => expect(delayedReadStarted).toBe(true))
        }
        const originalEntry = directory.getByLabelText(`选择接口 ${apiDefinition.name}`)
        expect(originalEntry).toHaveRole('button')
        await browser.click(originalEntry)
        await tabs.findByRole('tab', { name: `接口 · ${apiDefinition.name}` })
        expect(directory.getByLabelText(`选择接口 ${apiDefinition.name}`)).toHaveAttribute(
          'aria-pressed',
          'true',
        )
        const readsBeforeRename = secondReads
        const unrelated = { ...apiDefinition, name: '另一项目同名接口' }
        client.setQueryData(['api-definition', 'other-project', secondId], unrelated)
        const rename = directory.getByLabelText('重命名接口 接口B原名')
        expect(rename).toHaveRole('button')
        await browser.click(rename)
        const input = screen.getByLabelText('接口名称')
        const dialog = input.closest<HTMLElement>('[role=dialog]')!
        expect(dialog).toHaveRole('dialog')
        await browser.clear(input)
        await browser.click(input)
        await browser.paste('接口B新名')
        await browser.click(within(dialog).getByRole('button', { name: /保\s*存/ }))
        expect(await directory.findByLabelText('选择接口 接口B新名')).toHaveRole('button')
        expect(writes).toBe(1)
        expect(directory.getByLabelText(`选择接口 ${apiDefinition.name}`)).toHaveAttribute(
          'aria-pressed',
          'true',
        )
        expect(await tabs.findByRole('tab', { name: /^接口 · 接口B新名(?: ·)?$/ })).toBeVisible()
        if (lateDetail) {
          await act(async () => {
            release()
            await delayedRead
          })
          expect(tabs.queryByRole('tab', { name: /^接口 · 接口B新名(?: ·)?$/ })).toBeVisible()
        }
        expect(secondReads).toBe(readsBeforeRename)
        expect(client.getQueryData(['api-definition', 'other-project', secondId])).toBe(unrelated)
        await browser.click(tabs.getByRole('tab', { name: /^接口 · 接口B新名(?: ·)?$/ }))
        expect(await directory.findByLabelText('选择接口 接口B新名')).toHaveAttribute(
          'aria-pressed',
          'true',
        )
        expect(screen.getByLabelText('请求路径')).toHaveValue('/local-draft-b')
      } finally {
        release()
      }
    },
  )

  it('explains the whole project export scope before downloading', async () => {
    renderPage()
    const button = screen.getByRole('button', { name: '导出接口' })
    await waitFor(() => expect(button).toBeEnabled())
    await userEvent.click(button)
    await waitFor(() =>
      expect(
        screen.getByText(
          '使用各接口已保存的当前版本；搜索和方法筛选不影响范围。数量为当前查询结果，下载时由服务器重新校验。',
        ),
      ).toBeVisible(),
    )
    expect(screen.getByRole('button', { name: '导出整个项目' })).toBeEnabled()
  })
  it('shows the request method and path in the API directory', async () => {
    server.use(
      http.get(`/api/v1/projects/${project.id}/apis`, () =>
        HttpResponse.json({
          items: [{ ...apiDefinition, method: 'POST', path: '/orders/create' }],
          total: 1,
          page: 1,
          page_size: 50,
        }),
      ),
    )
    renderPage()
    await waitFor(() => {
      const entry = screen.getByRole('button', { name: `选择接口 ${apiDefinition.name}` })
      expect(entry).toHaveTextContent('POST')
      expect(entry).toHaveTextContent('/orders/create')
    })
  })
  it.each([
    [{ kind: 'status_code', operator: 'equals', target: null, expected: 200 }],
    [{ kind: 'json_path', operator: 'equals', target: '$.ok', expected: true }],
  ])(
    'shows the saved validation rules instead of an ignored quick status input: %j',
    async (rule) => {
      server.use(
        http.get(`/api/v1/projects/${project.id}/apis/${apiDefinition.id}`, () =>
          HttpResponse.json({
            definition: apiDefinition,
            version: {
              id: 'api-v1',
              api_definition_id: apiDefinition.id,
              version: 1,
              method: 'GET',
              path: '/users/me',
              query_parameters: [],
              headers: {},
              body_kind: 'none',
              body: null,
              auth_kind: 'none',
              auth_config: {},
              extraction_rules: [],
              assertions: [rule],
              created_at: '2026-08-09T08:00:00Z',
            },
          }),
        ),
      )
      renderPage()
      expect(await screen.findByText('按已保存断言校验（1 条）')).toBeVisible()
      expect(screen.queryByRole('spinbutton', { name: '预期状态码' })).not.toBeInTheDocument()
      if (rule.kind === 'json_path') expect(screen.getByText('未配置状态码断言')).toBeVisible()
      else expect(screen.getByText('状态码 equals 200')).toBeVisible()
    },
  )

  it('retains cross-page checkbox selection without changing the active API', async () => {
    const payloads: unknown[] = []
    server.use(
      http.get(`/api/v1/projects/${project.id}/apis`, ({ request }) => {
        const page = Number(new URL(request.url).searchParams.get('page'))
        return HttpResponse.json({
          items: [
            {
              ...apiDefinition,
              id: page === 1 ? apiDefinition.id : 'page-two-api',
              name: page === 1 ? apiDefinition.name : '第二页接口',
            },
          ],
          total: 51,
          page,
          page_size: 50,
        })
      }),
      http.post(`/api/v1/projects/${project.id}/apis/bulk-move`, async ({ request }) => {
        payloads.push(await request.json())
        return HttpResponse.json({ moved_count: 2, items: [] })
      }),
    )
    renderPage()
    const browser = userEvent.setup()
    const active = await screen.findByRole('button', { name: `选择接口 ${apiDefinition.name}` })
    await browser.click(screen.getByRole('checkbox', { name: `勾选接口 ${apiDefinition.name}` }))
    expect(active).toHaveAttribute('aria-pressed', 'true')
    await browser.click(screen.getByTitle('2'))
    await browser.click(await screen.findByRole('checkbox', { name: '勾选接口 第二页接口' }))
    expect(screen.getByText(apiDefinition.name, { exact: true })).toBeVisible()
    expect(screen.getByText('已选 2 个，本页 1 个，其他页 1 个')).toBeVisible()
    await browser.click(screen.getByRole('button', { name: '导出接口' }))
    fireEvent.mouseDown(screen.getByRole('combobox', { name: '导出范围' }))
    await browser.click(
      await screen.findByText('已选接口（包含其他页保留的选择）', {
        selector: '.ant-select-item-option-content',
      }),
    )
    expect(screen.getByText('已选接口（包含其他页保留的选择） · 当前共 2 个接口')).toBeVisible()
    await browser.click(screen.getByRole('button', { name: '取消' }))
    await browser.click(screen.getByRole('button', { name: '批量移动' }))
    expect(screen.getByRole('button', { name: '确认移动' })).toBeDisabled()
    await browser.click(screen.getByRole('combobox', { name: '接口目标分组' }))
    await browser.click(screen.getAllByText('未分组').at(-1)!)
    await browser.click(screen.getByRole('button', { name: '确认移动' }))
    await waitFor(() =>
      expect(payloads).toEqual([
        { definition_ids: [apiDefinition.id, 'page-two-api'], folder_id: null },
      ]),
    )
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: '批量移动' })).not.toBeInTheDocument(),
    )
  })
  it('keeps unsaved environment edits open when a catalog refresh fails', async () => {
    const { queryClient } = renderPage()
    const browser = userEvent.setup()
    await browser.click(await screen.findByRole('button', { name: '管理环境' }))
    fireEvent.change(screen.getByLabelText('名称'), { target: { value: '保留的环境草稿' } })
    server.use(
      http.get(`/api/v1/projects/${project.id}/environments`, () =>
        HttpResponse.json(
          { error: { code: 'UNAVAILABLE', message: '暂不可用', trace_id: 'environment-refresh' } },
          { status: 503 },
        ),
      ),
    )
    await act(async () => {
      await queryClient.invalidateQueries({ queryKey: ['environments', project.id] })
    })
    expect(await screen.findByText('环境列表暂时无法刷新，当前修改已保留。')).toBeVisible()
    expect(screen.getByLabelText('名称')).toHaveValue('保留的环境草稿')
  })

  it('retains a successfully created environment when catalog refresh fails', async () => {
    let created = false
    const newEnvironment = {
      ...environment,
      id: 'created-env',
      name: '新建后刷新失败',
      base_url: 'http://new.internal:9090',
    }
    server.use(
      http.get(`/api/v1/projects/${project.id}/environments`, () =>
        created
          ? HttpResponse.json(
              { error: { code: 'UNAVAILABLE', message: '暂不可用', trace_id: 'create-refresh' } },
              { status: 503 },
            )
          : HttpResponse.json([]),
      ),
      http.post(`/api/v1/projects/${project.id}/environments`, () => {
        created = true
        return HttpResponse.json(newEnvironment, { status: 201 })
      }),
    )
    renderPage()
    const management = screen.getByLabelText('管理环境')
    await waitFor(() => expect(management).toBeEnabled())
    fireEvent.click(management)
    const manager = within(screen.getByRole('dialog', { hidden: true }))
    fireEvent.change(manager.getByLabelText('名称'), { target: { value: newEnvironment.name } })
    fireEvent.change(manager.getByLabelText('默认地址'), {
      target: { value: newEnvironment.base_url },
    })
    fireEvent.click(manager.getByText('创建环境', { exact: true }).closest('button')!)
    expect(await manager.findByText('环境列表暂时无法刷新，当前修改已保留。')).toBeVisible()
    expect(manager.getByLabelText('名称')).toHaveValue(newEnvironment.name)
    await waitFor(() =>
      expect(manager.getByLabelText(`编辑环境 ${newEnvironment.name}`)).toBeEnabled(),
    )
    expect(
      screen.queryByText('正在编辑的环境已失效，请选择其他环境或新建环境。'),
    ).not.toBeInTheDocument()
    expect(screen.getByLabelText('发送环境')).toHaveDisplayValue('')
    fireEvent.click(manager.getByLabelText('Close'))
    expect(screen.queryByRole('dialog', { hidden: true })).not.toBeInTheDocument()
    fireEvent.click(management)
    expect(screen.getByLabelText('名称')).toHaveValue(newEnvironment.name)
  })
  it('selects or clears the current page without changing the active API', async () => {
    server.use(
      http.get(`/api/v1/projects/${project.id}/apis`, () =>
        HttpResponse.json({
          items: [apiDefinition, { ...apiDefinition, id: 'second-api', name: '另一个接口' }],
          total: 2,
          page: 1,
          page_size: 50,
        }),
      ),
    )
    renderPage()
    const browser = userEvent.setup()
    await screen.findByRole('checkbox', { name: '勾选接口 另一个接口' })
    await browser.click(screen.getByRole('checkbox', { name: '全选本页' }))
    expect(screen.getByText('已选 2 个，本页 2 个，其他页 0 个')).toBeVisible()
    expect(screen.getByRole('button', { name: `选择接口 ${apiDefinition.name}` })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    await browser.click(screen.getByRole('checkbox', { name: '全选本页' }))
    expect(screen.queryByRole('button', { name: '批量移动' })).not.toBeInTheDocument()
  })
  it('hides the previous final address when reloading its preview fails', async () => {
    const { queryClient } = renderPage()
    const finalAddress = `最终地址：${environment.base_url}/users/me`
    expect(await screen.findByText(finalAddress)).toBeVisible()
    server.use(
      http.post(`/api/v1/projects/${project.id}/apis/${apiDefinition.id}/preview`, () =>
        HttpResponse.json(
          {
            error: { code: 'UNAVAILABLE', message: '地址预览暂不可用', trace_id: 'preview-trace' },
          },
          { status: 503 },
        ),
      ),
    )
    await act(async () =>
      queryClient.invalidateQueries({ queryKey: ['api-target-preview', project.id] }),
    )
    expect(screen.queryByText(finalAddress)).not.toBeInTheDocument()
    expect(await screen.findByText(/地址预览暂不可用/)).toBeVisible()
  })

  it('shows the selected environment before the project has any API', async () => {
    server.use(
      http.get(`/api/v1/projects/${project.id}/apis`, () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 50 }),
      ),
    )
    renderPage()
    expect(await screen.findByText(environment.name, { exact: true })).toBeVisible()
    expect(screen.getByRole('button', { name: '管理环境' })).toBeEnabled()
  })

  it('pages this API history and opens its frozen request and response without an environment', async () => {
    const frozen = {
      ...executionDetail,
      execution: {
        ...executionDetail.execution,
        id: 'old-record',
        request_url: 'http://mock-target/old',
        response_body: { revision: 'old snapshot' },
      },
    }
    const requests: URLSearchParams[] = []
    server.use(
      http.get(`/api/v1/projects/${project.id}/environments`, () => HttpResponse.json([])),
      http.get(`/api/v1/projects/${project.id}/executions`, ({ request }) => {
        const params = new URL(request.url).searchParams
        requests.push(params)
        expect(params.get('api_definition_id')).toBe(apiDefinition.id)
        return HttpResponse.json({
          items: params.get('page') === '3' ? [frozen.execution] : [executionDetail.execution],
          total: 43,
          page: Number(params.get('page')),
          page_size: 20,
        })
      }),
      http.get(`/api/v1/projects/${project.id}/executions/old-record`, () =>
        HttpResponse.json(frozen),
      ),
    )
    const browser = userEvent.setup()
    renderPage()
    await browser.click(await screen.findByRole('tab', { name: '执行历史' }))
    const history = within(screen.getByRole('tabpanel', { name: '执行历史' }))
    expect(await history.findByText('共 43 次执行')).toBeVisible()
    fireEvent.click(history.getByTitle('3'))
    const record = await history.findByLabelText('查看执行 old-record')
    await browser.click(record)
    expect(await screen.findByText('正在查看历史执行的冻结请求与响应')).toBeVisible()
    expect(screen.getByText('"old snapshot"')).toBeVisible()
    await browser.click(screen.getByRole('tab', { name: '实际请求' }))
    expect(screen.getByText('GET http://mock-target/old')).toBeVisible()
    expect(requests.some((params) => params.get('page') === '3')).toBe(true)
  })

  it('restores frozen API evidence from a direct link without an environment', async () => {
    const frozen = {
      ...executionDetail,
      execution: {
        ...executionDetail.execution,
        id: 'old-record',
        request_url: 'http://mock-target/old',
        response_body: { revision: 'old snapshot' },
      },
    }
    server.use(
      http.get(`/api/v1/projects/${project.id}/environments`, () => HttpResponse.json([])),
      http.get(`/api/v1/projects/${project.id}/executions/old-record`, () =>
        HttpResponse.json(frozen),
      ),
    )
    renderPage(`/projects/${project.id}/apis?focus=${apiDefinition.id}&execution=old-record`)
    expect(await screen.findByText('正在查看历史执行的冻结请求与响应')).toBeVisible()
    expect(screen.getByText('"old snapshot"')).toBeVisible()
  })

  it('executes a selected historical version with a chosen environment while keeping configuration read-only', async () => {
    let sent: unknown
    server.use(
      http.get(`/api/v1/projects/${project.id}/environments`, () =>
        HttpResponse.json([environment, { ...environment, id: 'other-env', name: '其他环境' }]),
      ),
      http.get(`/api/v1/projects/${project.id}/apis/${apiDefinition.id}/versions`, () =>
        HttpResponse.json([{ version: 2 }, { version: 1 }]),
      ),
      http.get(`/api/v1/projects/${project.id}/apis/${apiDefinition.id}`, ({ request }) => {
        const version = Number(new URL(request.url).searchParams.get('version') ?? 2)
        return HttpResponse.json({
          definition: { ...apiDefinition, current_version: 2 },
          version: {
            id: `api-v${version}`,
            api_definition_id: apiDefinition.id,
            version,
            method: 'GET',
            path: `/v${version}/users`,
            query_parameters: [],
            variables: [],
            headers: {},
            body_kind: 'none',
            body: null,
            auth_kind: 'none',
            auth_config: {},
            extraction_rules: [],
            assertions: [],
          },
        })
      }),
      http.post(
        `/api/v1/projects/${project.id}/apis/${apiDefinition.id}/execute`,
        async ({ request }) => {
          sent = await request.json()
          return HttpResponse.json(executionDetail)
        },
      ),
    )
    renderPage()
    const browser = userEvent.setup()
    await browser.click(await screen.findByRole('combobox', { name: '接口版本' }))
    await browser.click(screen.getByText('v1（只读）'))
    expect(await screen.findByDisplayValue('/v1/users')).toBeDisabled()
    expect(screen.getByRole('button', { name: /保存新版本/ })).toBeDisabled()
    expect(screen.getByRole('button', { name: /发送请求/ })).toBeDisabled()
    expect(screen.getByRole('combobox', { name: '临时 Service' })).toBeEnabled()
    expect(screen.getByRole('combobox', { name: 'Endpoint Variant' })).toBeEnabled()
    await browser.click(screen.getByRole('combobox', { name: '发送环境' }))
    await browser.click(screen.getByText(environment.name))
    await browser.click(screen.getByRole('button', { name: /发送请求/ }))
    expect(await screen.findByText('接口执行通过')).toBeVisible()
    expect(sent).toMatchObject({ environment_id: environment.id, version: 1 })
    expect(screen.getByLabelText('请求路径')).toBeDisabled()
  })

  it('allows viewers to read historical evidence while editing and sending remain disabled', async () => {
    authenticateTestUser({ ...user, is_system_admin: false })
    server.use(
      http.get('/api/v1/projects', () =>
        HttpResponse.json({
          items: [{ ...project, role: 'viewer' }],
          total: 1,
          page: 1,
          page_size: 100,
        }),
      ),
      http.get(`/api/v1/projects/${project.id}/executions/${executionDetail.execution.id}`, () =>
        HttpResponse.json(executionDetail),
      ),
    )
    renderPage(
      `/projects/${project.id}/apis?focus=${apiDefinition.id}&execution=${executionDetail.execution.id}`,
    )
    expect(await screen.findByText('正在查看历史执行的冻结请求与响应')).toBeVisible()
    expect(screen.getByText('"测试用户"')).toBeVisible()
    expect(await screen.findByRole('button', { name: /保存新版本/ })).toBeDisabled()
    expect(screen.getByRole('button', { name: '发送请求' })).toBeDisabled()
    expect(screen.getByRole('checkbox', { name: `勾选接口 ${apiDefinition.name}` })).toBeEnabled()
    expect(screen.getByRole('button', { name: '导出接口' })).toBeEnabled()
    expect(screen.getByLabelText('请求路径')).toBeDisabled()
  })

  it.each([
    { verdict: 'passed', result: executionDetail, notification: '接口执行通过' },
    {
      verdict: 'failed despite HTTP 200',
      result: {
        execution: { ...executionDetail.execution, status: 'failed' },
        assertions: [{ ...executionDetail.assertions[0], passed: false, actual: 201 }],
      } satisfies ExecutionDetail,
      notification: '接口执行失败，请查看断言和响应',
    },
  ])(
    'runs an API and renders its assertion and history: $verdict',
    async ({ result, notification }) => {
      server.use(
        http.get('/api/v1/projects', () =>
          HttpResponse.json({ items: [project], total: 1, page: 1, page_size: 100 }),
        ),
        http.get(`/api/v1/projects/${project.id}/environments`, () =>
          HttpResponse.json([environment]),
        ),
        http.get(`/api/v1/projects/${project.id}/apis`, () =>
          HttpResponse.json({ items: [apiDefinition], total: 1, page: 1, page_size: 100 }),
        ),
        http.get(`/api/v1/projects/${project.id}/apis/${apiDefinition.id}`, () =>
          HttpResponse.json({
            definition: apiDefinition,
            version: {
              id: 'api-v1',
              api_definition_id: apiDefinition.id,
              version: 1,
              method: 'GET',
              path: '/users/me',
              query_parameters: [],
              headers: {},
              body_kind: 'none',
              body: null,
              auth_kind: 'none',
              auth_config: {},
              extraction_rules: [],
              assertions: [],
              created_at: '2026-08-09T08:00:00Z',
            },
          }),
        ),
        http.get(`/api/v1/projects/${project.id}/executions`, () =>
          HttpResponse.json({
            items: [result.execution],
            total: 1,
            page: 1,
            page_size: 20,
          }),
        ),
        http.get(`/api/v1/projects/${project.id}/files`, () =>
          HttpResponse.json({ items: [], total: 0, page: 1, page_size: 100 }),
        ),
        http.post(
          `/api/v1/projects/${project.id}/apis/${apiDefinition.id}/execute`,
          async ({ request }) => {
            expect(await request.json()).toMatchObject({ environment_id: environment.id })
            return HttpResponse.json(result)
          },
        ),
      )
      renderPage()
      const browser = userEvent.setup()

      await screen.findByRole('button', { name: /保存新版本/ })
      await browser.click(screen.getByRole('button', { name: /发送请求/ }))
      expect(await screen.findByText(/测试用户/)).toBeVisible()
      const notice = await screen.findByText(notification)
      const noticeType = result.execution.status === 'passed' ? 'success' : 'error'
      expect(notice.closest(`.ant-message-${noticeType}`)).not.toBeNull()

      await browser.click(screen.getByRole('tab', { name: '断言（1）' }))
      expect(
        within(screen.getByRole('tabpanel', { name: '断言（1）' })).getByText('状态码等于 200'),
      ).toBeVisible()
      await browser.click(screen.getByRole('tab', { name: '执行历史' }))
      expect(
        within(screen.getByLabelText('接口响应与验证')).getByText(
          executionDetail.execution.request_url,
        ),
      ).toBeVisible()
    },
  )

  it('renames an API and refreshes both the list and workbench title', async () => {
    let definition = apiDefinition
    let renamedPayload: unknown
    const detail = {
      definition,
      version: {
        id: 'version-1',
        api_definition_id: apiDefinition.id,
        version: 1,
        method: 'GET',
        path: '/users/me',
        query_parameters: [],
        headers: {},
        body_kind: 'none',
        body: null,
        auth_kind: 'none',
        auth_config: {},
        extraction_rules: [],
        assertions: [],
        created_at: '2026-08-09T00:00:00Z',
      },
    }
    server.use(
      http.get('/api/v1/projects', () =>
        HttpResponse.json({ items: [project], total: 1, page: 1, page_size: 100 }),
      ),
      http.get(`/api/v1/projects/${project.id}/environments`, () =>
        HttpResponse.json([environment]),
      ),
      http.get(`/api/v1/projects/${project.id}/apis`, () =>
        HttpResponse.json({ items: [definition], total: 1, page: 1, page_size: 100 }),
      ),
      http.get(`/api/v1/projects/${project.id}/apis/${apiDefinition.id}`, () =>
        HttpResponse.json({ ...detail, definition }),
      ),
      http.patch(`/api/v1/projects/${project.id}/apis/${apiDefinition.id}`, async ({ request }) => {
        renamedPayload = await request.json()
        definition = { ...definition, name: '重命名后的接口' }
        return HttpResponse.json(definition)
      }),
      http.get(`/api/v1/projects/${project.id}/executions`, () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 }),
      ),
      http.get(`/api/v1/projects/${project.id}/files`, () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 100 }),
      ),
    )
    renderPage()
    const browser = userEvent.setup()

    const renameButtons = await screen.findAllByRole('button', { name: /重命名接口/ })
    await browser.click(renameButtons.at(-1)!)
    const nameInput = screen.getByLabelText('接口名称')
    const dialog = nameInput.closest<HTMLElement>('.ant-modal')
    expect(dialog).not.toBeNull()
    await browser.clear(nameInput)
    await browser.type(nameInput, '重命名后的接口')
    await browser.click(within(dialog!).getByRole('button', { name: /保\s*存/ }))

    expect(renamedPayload).toEqual({ name: '重命名后的接口' })
    expect((await screen.findAllByText('重命名后的接口')).length).toBeGreaterThanOrEqual(2)
    expect(screen.getAllByText('v1', { exact: true }).length).toBeGreaterThanOrEqual(2)
  })
})

function renderPage(initialEntry?: string, showTabs = false) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const view = render(
    <ConfigProvider theme={createIceTheme(true)}>
      <AntdApp>
        <QueryClientProvider client={queryClient}>
          <ProjectTestProvider section="apis" initialEntry={initialEntry}>
            {showTabs && <WorkspaceObjectTabs userId={user.id} projectId={project.id} />}
            <ApiConsolePage />
          </ProjectTestProvider>
        </QueryClientProvider>
      </AntdApp>
    </ConfigProvider>,
  )
  return { ...view, queryClient }
}
