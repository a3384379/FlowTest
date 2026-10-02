import { createIceTheme } from '../theme/ice-theme'
import { useAuthStore } from '../features/auth/auth-store'
import { authenticateTestUser } from '../test/auth'
import { user as authenticatedUser } from '../test/fixtures'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App as AntdApp, ConfigProvider } from 'antd'
import { http, HttpResponse } from 'msw'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import ApiConsolePage from './ApiConsolePage'
import { apiDefinition, environment, executionDetail, project } from '../test/fixtures'
import type { ExecutionDetail } from '../lib/api'
import { server } from '../test/server'
import ProjectTestProvider from '../test/ProjectTestProvider'

beforeEach(() => authenticateTestUser(authenticatedUser))
afterEach(() => {
  useAuthStore.setState({ user: null })
  localStorage.clear()
})

describe('ApiConsolePage', () => {
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

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <ConfigProvider theme={createIceTheme(true)}>
      <AntdApp>
        <QueryClientProvider client={queryClient}>
          <ProjectTestProvider section="apis">
            <ApiConsolePage />
          </ProjectTestProvider>
        </QueryClientProvider>
      </AntdApp>
    </ConfigProvider>,
  )
}
