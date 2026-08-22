import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import WorkflowRunInspector from './WorkflowRunInspector'
import { workflowDefinition } from '../test/fixtures'
import type { WorkflowNodeExecution } from '../lib/api'

describe('WorkflowRunInspector', () => {
  it('shows redacted request, response, timing, and retry snapshots', async () => {
    const browser = userEvent.setup()
    const execution = apiNodeExecution()
    render(
      <WorkflowRunInspector
        mode="history"
        node={workflowDefinition.nodes.find((node) => node.id === 'api') ?? null}
        definition={workflowDefinition}
        execution={execution}
        nodes={[execution]}
        context={{ resolved_variables: { tenant: 'demo' } }}
      />,
    )

    expect(screen.getByText('历史快照')).toBeVisible()
    expect(screen.getByLabelText('请求尝试')).toBeVisible()
    expect(screen.getByText('82.35 ms')).toBeVisible()

    await browser.click(screen.getByRole('tab', { name: '请求' }))
    expect(screen.getByText('https://api.example.com/users?id=42')).toBeVisible()
    expect(screen.getByText(/"Authorization": "\*\*\*\*\*\*"/)).toBeVisible()
    expect(screen.getByText(/"target_key": "id"/)).toBeVisible()

    await browser.click(screen.getByRole('tab', { name: '响应' }))
    expect(screen.getByText('HTTP 200')).toBeVisible()
    expect(screen.getByText(/"name": "Ada"/)).toBeVisible()
    expect(screen.getByText('128 B')).toBeVisible()
  })

  it('shows the live empty state and pending node fallbacks', async () => {
    const browser = userEvent.setup()
    const view = render(
      <WorkflowRunInspector
        mode="run"
        node={null}
        definition={workflowDefinition}
        execution={undefined}
        nodes={[]}
        context={{}}
      />,
    )

    expect(screen.getByText('运行节点详情')).toBeVisible()
    view.rerender(
      <WorkflowRunInspector
        mode="run"
        node={workflowDefinition.nodes[0]}
        definition={workflowDefinition}
        execution={undefined}
        nodes={[]}
        context={{ tenant: 'demo' }}
      />,
    )
    expect(screen.getByText('pending')).toBeVisible()
    expect(screen.getByText('计时中')).toBeVisible()
    expect(screen.queryByText('历史快照')).not.toBeInTheDocument()

    await browser.click(screen.getByRole('tab', { name: '请求' }))
    expect(screen.getByText('该节点没有 HTTP 请求记录')).toBeVisible()
    await browser.click(screen.getByRole('tab', { name: '响应' }))
    expect(screen.getByText('暂无响应数据')).toBeVisible()
  })

  it('handles failed, missing, and large HTTP responses across attempts', async () => {
    const browser = userEvent.setup()
    const execution = edgeCaseExecution()
    render(
      <WorkflowRunInspector
        mode="run"
        node={workflowDefinition.nodes.find((node) => node.id === 'api') ?? null}
        definition={workflowDefinition}
        execution={execution}
        nodes={[execution]}
        context={{}}
      />,
    )

    expect(screen.getByText('2 s')).toBeVisible()
    await browser.click(screen.getByRole('tab', { name: '请求' }))
    expect(screen.getByText('<request>demo</request>')).toBeVisible()
    await browser.click(screen.getByRole('tab', { name: '响应' }))
    expect(screen.getByText('2 MB')).toBeVisible()

    await selectAttempt(browser, /第 3 次 · HTTP 503/)
    expect(screen.getByText('HTTP 503')).toBeVisible()
    expect(screen.getByText('2 KB')).toBeVisible()

    await selectAttempt(browser, /第 1 次 · 无响应/)
    expect(screen.getByText('暂无响应数据')).toBeVisible()
    await selectAttempt(browser, /第 2 次 · 连接超时/)
    expect(screen.getByText('连接超时')).toBeVisible()
    await browser.click(screen.getByRole('tab', { name: '校验/错误' }))
    expect(screen.getByText('节点执行失败')).toBeVisible()
  })

  it('uses node timestamps when no HTTP observation exists', () => {
    const execution: WorkflowNodeExecution = {
      ...apiNodeExecution(),
      attempts: 1,
      result: { ...apiNodeExecution().result!, observations: [] },
    }
    render(
      <WorkflowRunInspector
        mode="run"
        node={workflowDefinition.nodes.find((node) => node.id === 'api') ?? null}
        definition={workflowDefinition}
        execution={execution}
        nodes={[execution]}
        context={{}}
      />,
    )

    expect(screen.getByText('1 s')).toBeVisible()
  })

  it('falls back to the latest observation after a live retry update', () => {
    const execution = apiNodeExecution()
    const first = observation(7, 202, 40, { state: 'queued' })
    const view = render(
      <WorkflowRunInspector
        mode="run"
        node={workflowDefinition.nodes.find((node) => node.id === 'api') ?? null}
        definition={workflowDefinition}
        execution={{
          ...execution,
          result: { ...execution.result!, observations: [first] },
        }}
        nodes={[execution]}
        context={{}}
      />,
    )
    const latest = {
      ...observation(8, 200, 50, { state: 'ready' }),
      request: { ...first.request, url: 'https://api.example.com/users?retry=8' },
    }

    view.rerender(
      <WorkflowRunInspector
        mode="run"
        node={workflowDefinition.nodes.find((node) => node.id === 'api') ?? null}
        definition={workflowDefinition}
        execution={{
          ...execution,
          result: { ...execution.result!, observations: [latest] },
        }}
        nodes={[execution]}
        context={{}}
      />,
    )
    expect(screen.getByText('50 ms')).toBeVisible()
  })
})

async function selectAttempt(browser: ReturnType<typeof userEvent.setup>, optionName: RegExp) {
  await browser.click(screen.getByLabelText('请求尝试'))
  await browser.click(await screen.findByText(optionName))
}

function apiNodeExecution(): WorkflowNodeExecution {
  return {
    id: 'node-execution-api',
    node_id: 'api',
    node_type: 'api',
    name: '查询用户',
    status: 'passed',
    attempts: 2,
    output: { status_code: 200, body: { name: 'Ada' } },
    error_code: null,
    error_message: null,
    started_at: '2026-08-15T08:00:00Z',
    completed_at: '2026-08-15T08:00:01Z',
    result: {
      status: 'passed',
      output: { status_code: 200, body: { name: 'Ada' } },
      assertions: [],
      metrics: [],
      artifacts: [],
      trace: null,
      redacted_paths: ['request.headers.Authorization'],
      error: null,
      observations: [
        observation(1, 503, 31.2, { message: 'busy' }),
        observation(2, 200, 82.35, { name: 'Ada' }),
      ],
    },
  }
}

function observation(attempt: number, statusCode: number, durationMs: number, body: unknown) {
  return {
    kind: 'http' as const,
    attempt,
    request: {
      method: 'GET',
      url: 'https://api.example.com/users?id=42',
      headers: { Authorization: '******', Accept: 'application/json' },
      body: null,
    },
    response: {
      status_code: statusCode,
      headers: { 'content-type': 'application/json' },
      body,
      size_bytes: 128,
    },
    mappings: [
      {
        source_node_id: 'start',
        source_path: 'user_id',
        target_location: 'query',
        target_key: 'id',
        value: '42',
      },
    ],
    duration_ms: durationMs,
    started_at: '2026-08-15T08:00:00Z',
    completed_at: '2026-08-15T08:00:00.082Z',
    error_code: statusCode >= 400 ? 'HTTP_ERROR' : null,
    error_message: statusCode >= 400 ? `HTTP ${statusCode}` : null,
  }
}

function edgeCaseExecution(): WorkflowNodeExecution {
  const execution = apiNodeExecution()
  const unavailable = {
    ...observation(1, 503, 1_250, null),
    response: null,
    request: {
      method: 'POST',
      url: 'https://api.example.com/users',
      headers: {},
      body: '<request>demo</request>',
    },
    error_code: null,
    error_message: null,
  }
  return {
    ...execution,
    status: 'failed',
    attempts: 4,
    error_code: 'WORKFLOW_NODE_FAILED',
    error_message: '节点执行失败',
    result: {
      ...execution.result!,
      observations: [
        unavailable,
        {
          ...unavailable,
          attempt: 2,
          error_code: 'HTTP_TIMEOUT',
          error_message: '连接超时',
        },
        {
          ...observation(3, 503, 1_500, { message: 'busy' }),
          error_code: null,
          error_message: null,
          response: {
            ...observation(3, 503, 1_500, {}).response!,
            size_bytes: 2_048,
          },
        },
        {
          ...observation(4, 200, 2_000, { payload: 'large' }),
          request: unavailable.request,
          response: {
            ...observation(4, 200, 2_000, {}).response!,
            size_bytes: 2 * 1024 * 1024,
          },
        },
      ],
    },
  }
}
