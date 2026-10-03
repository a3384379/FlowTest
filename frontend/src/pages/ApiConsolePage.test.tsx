import { createIceTheme } from '../theme/ice-theme'
import { useAuthStore } from '../features/auth/auth-store'
import { authenticateTestUser } from '../test/auth'
import { user as authenticatedUser } from '../test/fixtures'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App as AntdApp, ConfigProvider } from 'antd'
import { http, HttpResponse } from 'msw'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import ApiConsolePage from './ApiConsolePage'
import { apiDefinition, environment, executionDetail, project, user } from '../test/fixtures'
import type { ExecutionDetail } from '../lib/api'
import { server } from '../test/server'
import ProjectTestProvider from '../test/ProjectTestProvider'

beforeEach(() => {
  authenticateTestUser(authenticatedUser)
  server.use(
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
      expect(screen.getByText(executionDetail.execution.request_url)).toBeVisible()
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

function renderPage(initialEntry?: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <ConfigProvider theme={createIceTheme(true)}>
      <AntdApp>
        <QueryClientProvider client={queryClient}>
          <ProjectTestProvider section="apis" initialEntry={initialEntry}>
            <ApiConsolePage />
          </ProjectTestProvider>
        </QueryClientProvider>
      </AntdApp>
    </ConfigProvider>,
  )
}
