import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AxiosError, AxiosHeaders } from 'axios'
import * as dataSources from './data-source-service'

import type { MockRoute } from '../../lib/api'
import { project, user } from '../../test/fixtures'
import { server } from '../../test/server'
import type { MockPreviewResult } from './data-source-service'
import MockRouteForm from './MockRouteForm'

const route: MockRoute = {
  id: 'preview-route',
  mock_service_id: 'preview-service',
  name: '合成订单',
  method: 'GET',
  path_pattern: '/orders/{id}',
  query_conditions: {},
  header_conditions: {},
  response_headers: {},
  response_body: { id: '{{path.id}}' },
  response_status: 200,
  delay_ms: 100,
  scenario: null,
  priority: 10,
  is_enabled: true,
  created_by_id: user.id,
  created_at: '2026-10-21T00:00:00Z',
  updated_at: '2026-10-21T00:00:00Z',
}
const endpoint = `/api/v1/projects/${project.id}/mock-services/${route.mock_service_id}/routes/preview`
function evidence(id = '42'): MockPreviewResult {
  return {
    service_enabled: true,
    draft_matches: true,
    selected: {
      route_id: route.id,
      name: route.name,
      is_draft: true,
      priority: 10,
      scenario: null,
      delay_ms: 100,
    },
    checks: [{ field: 'path_pattern', matched: true, message: '应用收到的请求路径匹配' }],
    warnings: [],
    response: { status_code: 200, headers: {}, body: { id } },
  }
}
function renderForm(canEdit = true) {
  const saved = vi.fn()
  const props = {
    projectId: project.id,
    serviceId: route.mock_service_id,
    route,
    canEdit,
    readable: true,
    pending: false,
    onDirty: vi.fn(),
    onFinish: saved,
  }
  const rendered = render(<MockRouteForm {...props} />)
  return {
    ...rendered,
    saved,
    setReadable: (readable: boolean) =>
      rendered.rerender(<MockRouteForm {...props} readable={readable} />),
    switchRoute: () =>
      rendered.rerender(
        <MockRouteForm key="another" {...props} route={{ ...route, id: 'another' }} />,
      ),
    changeCatalog: () => rendered.rerender(<MockRouteForm {...props} previewScope="new-catalog" />),
  }
}
async function openPreview() {
  fireEvent.change(screen.getByLabelText('合成请求路径'), { target: { value: '/orders/42' } })
}

describe('MockRouteForm structured configuration and preview', () => {
  afterEach(() => vi.restoreAllMocks())
  it('saves key/value rows and preserves text as a JSON string value', async () => {
    const { saved } = renderForm()
    await userEvent.click(screen.getByRole('button', { name: 'Query 条件：添加一行' }))
    fireEvent.change(screen.getByLabelText('Query 条件 键 1'), { target: { value: 'mode' } })
    fireEvent.change(screen.getByLabelText('Query 条件 值 1'), { target: { value: 'full' } })
    await userEvent.click(screen.getByRole('combobox', { name: '响应体类型' }))
    await userEvent.click(screen.getByText('文本（JSON 字符串值）', { exact: true }))
    fireEvent.change(screen.getByLabelText('响应模板（文本）'), {
      target: { value: 'order {{path.id}}' },
    })
    await userEvent.click(screen.getByRole('button', { name: '保存路由' }))
    await waitFor(() =>
      expect(saved).toHaveBeenCalledWith(
        expect.objectContaining({
          query_conditions: { mode: 'full' },
          response_body: 'order {{path.id}}',
        }),
      ),
    )
  })

  it.each(['[]', '{"X-Team":4}', 'null'])(
    'locates invalid Header JSON %s before any write or preview',
    async (invalid) => {
      const preview = vi.fn()
      server.use(
        http.post(endpoint, () => {
          preview()
          return HttpResponse.json(evidence())
        }),
      )
      const { saved } = renderForm()
      await userEvent.click(screen.getByRole('button', { name: 'Header 条件：高级 JSON' }))
      fireEvent.change(screen.getByLabelText('Header 条件 JSON'), { target: { value: invalid } })
      await userEvent.click(screen.getByRole('button', { name: '保存路由' }))
      await screen.findByText(
        invalid.includes('4')
          ? '键“X-Team”的值必须是字符串'
          : '必须是 JSON 对象，不能是数组、数字或 null',
      )
      expect(saved).not.toHaveBeenCalled()
      await openPreview()
      const previewButton = screen.getByRole('button', { name: '预览匹配与响应' })
      await userEvent.click(previewButton)
      await waitFor(() => expect(previewButton).not.toHaveClass(/ant-btn-loading/))
      expect(preview).not.toHaveBeenCalled()
      expect(screen.getByLabelText('Header 条件 JSON')).toHaveValue(invalid)
    },
  )

  it('lets viewers enter synthetic requests and preview without enabling writes', async () => {
    const requested = vi.fn()
    server.use(
      http.post(endpoint, async ({ request }) => {
        requested(await request.json())
        return HttpResponse.json(evidence())
      }),
    )
    const { saved } = renderForm(false)
    expect(screen.getByLabelText('名称')).toBeDisabled()
    await openPreview()
    await userEvent.click(screen.getByRole('button', { name: '预览匹配与响应' }))
    const result = await screen.findByRole('region', { name: 'Mock 预览结果' })
    expect(result).toHaveTextContent('当前草稿')
    expect(result).toHaveTextContent('优先级 10')
    expect(result).toHaveTextContent('延迟 100 ms（仅展示）')
    expect(requested).toHaveBeenCalledWith(
      expect.objectContaining({
        route_id: route.id,
        request: { method: 'GET', path: '/orders/42', query: {}, headers: {}, body: {} },
      }),
    )
    expect(saved).not.toHaveBeenCalled()
    expect(screen.queryByRole('button', { name: '保存路由' })).not.toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('合成请求路径'), { target: { value: '/orders/43' } })
    expect(screen.queryByRole('region', { name: 'Mock 预览结果' })).not.toBeInTheDocument()
  })

  it('retains duplicate advanced Query keys and blocks save, preview and conversion to rows', async () => {
    const preview = vi.spyOn(dataSources, 'previewMockRoute')
    const { saved } = renderForm()
    const invalid = '{"mode":"full","mode":"short"}'
    fireEvent.click(screen.getByRole('button', { name: 'Query 条件：高级 JSON' }))
    const input = screen.getByLabelText('Query 条件 JSON')
    fireEvent.change(input, { target: { value: invalid } })
    fireEvent.click(screen.getByRole('button', { name: '保存路由' }))
    await screen.findByText('键名不能重复；Header 名称不区分大小写')
    expect(saved).not.toHaveBeenCalled()
    await openPreview()
    const previewButton = screen.getByRole('button', { name: '预览匹配与响应' })
    fireEvent.click(previewButton)
    await waitFor(() => expect(previewButton).not.toHaveClass(/ant-btn-loading/))
    expect(preview).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Query 条件：返回键值行' }))
    expect(input).toHaveValue(invalid)
    expect(screen.queryByLabelText('Query 条件 键 1')).not.toBeInTheDocument()
  })

  it('shows template field, escaped pointer and trace while retaining the draft', async () => {
    server.use(
      http.post(endpoint, () =>
        HttpResponse.json(
          {
            error: {
              code: 'MOCK_PREVIEW_TEMPLATE_ERROR',
              message: 'Mock 模板变量不存在: body.missing',
              trace_id: 'preview-field-trace',
              details: { field: 'response_body', pointer: '/a~1b/0', route_id: route.id },
            },
          },
          { status: 422 },
        ),
      ),
    )
    renderForm()
    await openPreview()
    await userEvent.click(screen.getByRole('button', { name: '预览匹配与响应' }))
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('response_body/a~1b/0'))
    expect(screen.getByRole('alert')).toHaveTextContent('preview-field-trace')
    expect(screen.getByLabelText('响应模板（JSON）')).toHaveValue(
      JSON.stringify(route.response_body, null, 2),
    )
    expect(
      document.querySelector('.ant-form-item-has-error #mock-route_response_body'),
    ).toBeInTheDocument()
  })

  it.each([
    ['draft', 'success'],
    ['request', 'success'],
    ['permission', 'success'],
    ['route', 'success'],
    ['catalog', 'success'],
    ['draft', 'error'],
    ['request', 'error'],
    ['permission', 'error'],
    ['route', 'error'],
    ['catalog', 'error'],
  ])('ignores a late %s preview %s after the source changes', async (change, outcome) => {
    let resolve!: (value: MockPreviewResult) => void
    let reject!: (error: Error) => void
    const response = new Promise<MockPreviewResult>((complete, fail) => {
      resolve = complete
      reject = fail
    })
    const requested = vi.spyOn(dataSources, 'previewMockRoute').mockReturnValue(response)
    const rendered = renderForm()
    await openPreview()
    await userEvent.click(screen.getByRole('button', { name: '预览匹配与响应' }))
    await waitFor(() => expect(requested).toHaveBeenCalledOnce())
    if (change === 'draft')
      fireEvent.change(screen.getByLabelText('名称'), { target: { value: '新草稿' } })
    if (change === 'request')
      fireEvent.change(screen.getByLabelText('合成请求体（JSON）'), {
        target: { value: '{"next":true}' },
      })
    if (change === 'permission') rendered.setReadable(false)
    if (change === 'route') rendered.switchRoute()
    if (change === 'catalog') rendered.changeCatalog()
    await act(async () => {
      if (outcome === 'success') resolve(evidence('obsolete-value'))
      else
        reject(
          new AxiosError('obsolete-error', 'UNAVAILABLE', undefined, undefined, {
            data: { error: { message: 'obsolete-error' } },
            status: 503,
            statusText: 'Unavailable',
            headers: {},
            config: { headers: new AxiosHeaders() },
          }),
        )
      await response.catch(() => undefined)
    })
    expect(screen.queryByText(/obsolete-value|obsolete-error/)).not.toBeInTheDocument()
    if (change === 'permission') {
      rendered.setReadable(true)
      expect(screen.queryByRole('region', { name: 'Mock 预览结果' })).not.toBeInTheDocument()
    }
  })
})
