import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App, ConfigProvider } from 'antd'
import { createMemoryRouter, Link, RouterProvider } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import type { ComponentProps } from 'react'
import type {
  PerformanceDefinition,
  PerformanceScenario,
  PerformanceScenarioInput,
} from './performance-service'
import PerformanceScenarioDialog from './PerformanceScenarioDialog'
const definition: PerformanceDefinition = {
  executor: 'ramping_vus',
  steps: [
    {
      name: '原始步骤',
      method: 'POST',
      url: 'http://mock-target:8080/orders',
      headers: { 'X-Team': 'audit' },
      body: { order: 7 },
      expected_statuses: [200, 201],
      pause_seconds: 0.015,
    },
  ],
  thresholds: [
    {
      metric: 'http_req_failed',
      aggregation: 'rate',
      operator: '<=',
      value: 0.000000001,
      abort_on_fail: true,
      delay_abort_seconds: 5,
    },
  ],
  vus: null,
  duration_seconds: null,
  start_vus: 0,
  stages: [
    { duration_seconds: 20, target_vus: 3 },
    { duration_seconds: 10, target_vus: 0 },
  ],
  graceful_stop_seconds: 15,
}
const base: PerformanceScenario = {
  id: 'old-scene',
  project_id: 'owned-project',
  name: '原始场景',
  description: '原始说明',
  version: 1,
  status: 'published',
  target_type: 'rest',
  definition,
  compiled_sha256: 'hash',
  published_at: '2026-10-21T00:00:00Z',
  created_by_id: 'actor',
  created_at: '2026-10-21T00:00:00Z',
  updated_at: '2026-10-21T00:00:00Z',
}
function setup(props: Partial<ComponentProps<typeof PerformanceScenarioDialog>> = {}) {
  const submit = vi
      .fn<(input: PerformanceScenarioInput) => Promise<boolean>>()
      .mockResolvedValue(false),
    close = vi.fn()
  const router = createMemoryRouter([
    {
      path: '/',
      element: (
        <>
          <Link to="/other">离开性能页</Link>
          <PerformanceScenarioDialog
            submitting={false}
            onClose={close}
            onSubmit={submit}
            {...props}
          />
        </>
      ),
    },
    { path: '/other', element: <div>其他页面</div> },
  ])
  render(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <App>
        <RouterProvider router={router} />
      </App>
    </ConfigProvider>,
  )
  return { submit, close, router }
}
function card(title: string) {
  return within(screen.getByText(title, { exact: true }).closest('.ant-card') as HTMLElement)
}
describe('PerformanceScenarioDialog', () => {
  it('edits multiple HTTP steps and stages while retaining inactive load settings and retry input', async () => {
    const { submit } = setup()
    const browser = userEvent.setup()
    fireEvent.change(screen.getByLabelText('场景名称'), { target: { value: '多步骤阶梯' } })
    fireEvent.change(screen.getByLabelText('目标 URL'), {
      target: { value: 'http://mock-target:8080/health' },
    })
    await browser.click(screen.getByRole('button', { name: '添加 HTTP 步骤（最多20个）' }))
    const second = card('HTTP 步骤 2')
    fireEvent.change(second.getByLabelText('目标 URL'), {
      target: { value: 'http://mock-target:8080/orders' },
    })
    await browser.click(second.getByRole('button', { name: '添加请求头' }))
    fireEvent.change(second.getByLabelText('请求头1名称'), { target: { value: 'X-Team' } })
    fireEvent.change(second.getByLabelText('请求头1值'), { target: { value: 'audit' } })
    fireEvent.change(second.getByLabelText('请求体（JSON值，字符串使用双引号）'), {
      target: { value: '{"order":7}' },
    })
    await browser.clear(second.getByLabelText('步骤间隔（秒）'))
    await browser.type(second.getByLabelText('步骤间隔（秒）'), '0.015')
    await browser.tab()
    await browser.click(screen.getByText('阶梯升压'))
    await browser.click(screen.getByRole('button', { name: '添加升压阶段（最多20个）' }))
    const stage2 = card('升压阶段 2')
    fireEvent.change(stage2.getByLabelText('升压时间（秒）'), { target: { value: '30' } })
    fireEvent.change(stage2.getByLabelText('目标 VU'), { target: { value: '0' } })
    await browser.click(screen.getByText('固定 VU'))
    await browser.click(screen.getByText('阶梯升压'))
    expect(card('升压阶段 2').getByLabelText('升压时间（秒）')).toHaveValue('30')
    await browser.click(screen.getByRole('button', { name: 'OK' }))
    await waitFor(() => expect(submit).toHaveBeenCalledOnce())
    const payload = submit.mock.calls[0][0]
    expect(payload.definition).toMatchObject({
      executor: 'ramping_vus',
      vus: null,
      duration_seconds: null,
      start_vus: 0,
      stages: [
        { duration_seconds: 60, target_vus: 20 },
        { duration_seconds: 30, target_vus: 0 },
      ],
    })
    expect(payload.definition.steps).toHaveLength(2)
    expect(payload.definition.steps[1]).toMatchObject({
      headers: { 'X-Team': 'audit' },
      body: { order: 7 },
      pause_seconds: 0.015,
    })
    await browser.click(screen.getByRole('button', { name: 'OK' }))
    await waitFor(() => expect(submit).toHaveBeenCalledTimes(2))
    expect(submit.mock.calls[1][0]).toEqual(payload)
  })
  it('round-trips old configuration including fractional metrics and requires explicit validated JSON application', async () => {
    const { submit } = setup({ base })
    const browser = userEvent.setup()
    await browser.click(screen.getByRole('button', { name: 'OK' }))
    await waitFor(() =>
      expect(submit).toHaveBeenCalledWith({
        name: base.name,
        description: base.description,
        definition,
      }),
    )
    await browser.click(screen.getByRole('tab', { name: '高级 JSON' }))
    fireEvent.change(screen.getByLabelText('完整声明式配置'), {
      target: { value: JSON.stringify({ ...definition, script: 'forbidden' }) },
    })
    await browser.click(screen.getByRole('button', { name: '校验并应用 JSON' }))
    expect(await screen.findByText('配置校验失败：配置不支持字段 script')).toBeVisible()
    await browser.click(screen.getByRole('button', { name: 'OK' }))
    expect(
      await screen.findByText('配置校验失败：高级JSON尚未应用，请先应用或放弃JSON修改'),
    ).toBeVisible()
    expect(submit).toHaveBeenCalledOnce()
    fireEvent.change(screen.getByLabelText('完整声明式配置'), {
      target: {
        value: JSON.stringify({
          ...definition,
          stages: [
            { duration_seconds: 2000, target_vus: 2 },
            { duration_seconds: 2000, target_vus: 0 },
          ],
        }),
      },
    })
    await browser.click(screen.getByRole('button', { name: '校验并应用 JSON' }))
    expect(await screen.findByText('配置校验失败：各阶段总时长不能超过3600秒')).toBeVisible()
    fireEvent.change(screen.getByLabelText('完整声明式配置'), {
      target: { value: JSON.stringify({ ...definition, graceful_stop_seconds: 20 }) },
    })
    await browser.click(screen.getByRole('button', { name: '校验并应用 JSON' }))
    await browser.click(screen.getByRole('tab', { name: /与 v1 差异/ }))
    expect(await screen.findByText('graceful_stop_seconds')).toBeVisible()
    await browser.click(screen.getByRole('button', { name: 'OK' }))
    await waitFor(() => expect(submit).toHaveBeenCalledTimes(2))
    expect(submit.mock.calls[1][0].definition).toEqual({ ...definition, graceful_stop_seconds: 20 })
  })
  it('keeps malformed body input and protects close and navigation without submitting', async () => {
    const { submit, close, router } = setup({ base })
    const browser = userEvent.setup()
    fireEvent.change(screen.getByLabelText('请求体（JSON值，字符串使用双引号）'), {
      target: { value: '{invalid' },
    })
    await browser.click(screen.getByRole('button', { name: 'OK' }))
    expect(await screen.findByText('性能配置尚未提交')).toBeVisible()
    expect(submit).not.toHaveBeenCalled()
    await browser.click(screen.getByRole('button', { name: 'Cancel' }))
    await waitFor(() =>
      expect(screen.getByText('关闭将放弃当前表单和未应用的JSON修改。')).toBeVisible(),
    )
    await browser.click(screen.getByRole('button', { name: '继续编辑' }))
    expect(close).not.toHaveBeenCalled()
    await browser.click(screen.getByRole('link', { name: '离开性能页' }))
    await waitFor(() =>
      expect(screen.getByText('离开将放弃当前表单和未应用的JSON修改。')).toBeVisible(),
    )
    await browser.click(screen.getByRole('button', { name: '继续编辑' }))
    expect(router.state.location.pathname).toBe('/')
    expect(screen.getByLabelText('请求体（JSON值，字符串使用双引号）')).toHaveValue('{invalid')
  })
})
