import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it, vi } from 'vitest'

import WorkflowRunInspector from './WorkflowRunInspector'
import { workflowDefinition } from '../test/fixtures'
import type { WorkflowNodeExecution } from '../lib/api'
import { server } from '../test/server'

describe('WorkflowRunInspector', () => {
  it('opens the linked attempt and reports a later attempt selection', async () => {
    const browser = userEvent.setup()
    const execution = apiNodeExecution()
    const onSelectAttempt = vi.fn()
    render(
      <WorkflowRunInspector
        mode="history"
        node={workflowDefinition.nodes.find((node) => node.id === 'api') ?? null}
        definition={workflowDefinition}
        execution={execution}
        nodes={[execution]}
        context={{}}
        initialAttempt={1}
        onSelectAttempt={onSelectAttempt}
      />,
    )
    expect(screen.getByText('31.2 ms')).toBeVisible()
    await browser.click(screen.getByRole('tab', { name: '响应' }))
    expect(screen.getByText(/"busy"/)).toBeVisible()
    expect(screen.queryByText(/"Ada"/)).not.toBeInTheDocument()
    await selectAttempt(browser, /第 2 次/)
    expect(onSelectAttempt).toHaveBeenCalledWith(2)
    expect(screen.getAllByText('82.35 ms')[0]).toBeVisible()
    expect(screen.getByText(/"Ada"/)).toBeVisible()
  })

  it('shows an authorized download action for a stored response body', async () => {
    const browser = userEvent.setup()
    const execution = apiNodeExecution()
    render(
      <WorkflowRunInspector
        mode="history"
        projectId="project-1"
        executionId="execution-1"
        node={workflowDefinition.nodes.find((node) => node.id === 'api') ?? null}
        definition={workflowDefinition}
        execution={{
          ...execution,
          output: {
            status_code: 200,
            headers: {},
            size_bytes: 3_000_000,
            body: {
              __flowtest_workflow_output_ref__: {
                artifact_id: '00000000-0000-4000-8000-000000000001',
                size_bytes: 3_000_000,
              },
            },
          },
        }}
        nodes={[execution]}
        context={{}}
      />,
    )
    await browser.click(screen.getByRole('tab', { name: '输出' }))
    expect(screen.getByText(/大型响应已保存为对象引用/)).toBeVisible()
    expect(screen.getByRole('button', { name: '下载响应体' })).toBeVisible()
  })

  it('shows parallel branch status separately from its test verdict', async () => {
    const browser = userEvent.setup()
    const execution = apiNodeExecution()
    render(
      <WorkflowRunInspector
        mode="run"
        node={workflowDefinition.nodes.find((node) => node.id === 'api') ?? null}
        definition={workflowDefinition}
        execution={{
          ...execution,
          output: {
            join: 'all',
            started_count: 1,
            failed_count: 1,
            branches: [
              {
                definition_index: 0,
                status: 'passed',
                test_verdict: 'failed',
                nodes: [{ node_id: 'assertion', status: 'failed', error_message: '断言未通过' }],
              },
            ],
          },
        }}
        nodes={[execution]}
        context={{}}
      />,
    )
    await browser.click(screen.getByLabelText('选择并行分支'))
    await browser.click(screen.getByText('分支 1 · failed'))
    expect(screen.getByText('assertion · failed')).toBeVisible()
    expect(screen.getByText('断言未通过')).toBeVisible()
  })

  it('loads one report page and an exact persisted instance on demand', async () => {
    const browser = userEvent.setup()
    const execution = apiNodeExecution()
    const projectId = 'project-1'
    const executionId = 'execution-1'
    const nodeId = 'api'
    const reportPath = `/api/v1/projects/${projectId}/workflow-executions/${executionId}`
    const requestedPages: number[] = []
    server.use(
      http.get(`${reportPath}/control-records`, ({ request }) => {
        const page = Number(new URL(request.url).searchParams.get('page'))
        requestedPages.push(page)
        return HttpResponse.json({
          items: [{ ordinal: page === 2 ? 20 : 0, status: 'failed', test_verdict: 'failed' }],
          total: 21,
          page,
          page_size: 20,
        })
      }),
      http.get(`${reportPath}/control-records/iteration/20`, () =>
        HttpResponse.json({
          kind: 'iteration',
          ordinal: 20,
          status: 'failed',
          test_verdict: 'failed',
          payload: {
            input_index: 20,
            status: 'failed',
            test_verdict: 'failed',
            nodes: [
              { node_id: 'check', instance_id: '__nested_request__:example', status: 'failed' },
            ],
          },
        }),
      ),
      http.get(`${reportPath}/instances/__nested_request__:example`, () =>
        HttpResponse.json({
          node_id: '__nested_request__:example',
          node_name: '校验',
          status: 'failed',
          output: { actual: 409 },
          result: { error_code: 'CASE_FAIL', observations: [{ response: { status_code: 409 } }] },
        }),
      ),
    )
    render(
      <WorkflowRunInspector
        mode="history"
        projectId={projectId}
        executionId={executionId}
        node={workflowDefinition.nodes.find((node) => node.id === nodeId) ?? null}
        definition={workflowDefinition}
        execution={{
          ...execution,
          output: {
            input_count: 21,
            completed_count: 21,
            failed_count: 21,
            termination_reason: 'completed',
            report_kind: 'iteration',
            report_paged: true,
            record_count: 21,
          },
        }}
        nodes={[execution]}
        context={{}}
      />,
    )
    await screen.findByRole('region', { name: '循环执行详情' })
    await browser.click(screen.getByTitle('2'))
    await browser.click(screen.getByLabelText('选择循环轮次'))
    await browser.click(await screen.findByText('第 21 项 · failed'))
    expect(await screen.findByText('check · failed')).toBeVisible()
    await browser.click(screen.getByRole('button', { name: '查看实例详情' }))
    expect(await screen.findByText(/"actual": 409/)).toBeVisible()
    await browser.click(
      within(screen.getByRole('region', { name: '实例执行证据' })).getByRole('tab', {
        name: '原始证据',
      }),
    )
    expect(screen.getByText(/"status_code": 409/)).toBeVisible()
    expect(requestedPages).toEqual([1, 2])
  })

  it('restores a third iteration and its exact instance request attempt from a deep link', async () => {
    const browser = userEvent.setup()
    const execution = apiNodeExecution()
    const instanceId = '__nested_request__:third-item'
    const onSelectEvidence = vi.fn()
    const reportPath = '/api/v1/projects/project-1/workflow-executions/execution-1'
    server.use(
      http.get(`${reportPath}/control-records`, () =>
        HttpResponse.json({
          items: [0, 1, 2].map((ordinal) => ({
            ordinal,
            status: 'failed',
            test_verdict: 'failed',
          })),
          total: 3,
          page: 1,
          page_size: 20,
        }),
      ),
      http.get(`${reportPath}/control-records/iteration/2`, () =>
        HttpResponse.json({
          kind: 'iteration',
          ordinal: 2,
          status: 'failed',
          test_verdict: 'failed',
          payload: {
            input_index: 2,
            status: 'failed',
            test_verdict: 'failed',
            nodes: [{ node_id: 'check', instance_id: instanceId, status: 'failed' }],
          },
        }),
      ),
      http.get(`${reportPath}/instances/${instanceId}`, () =>
        HttpResponse.json({
          id: 'checkpoint-3',
          node_id: instanceId,
          node_name: '第3项校验',
          status: 'failed',
          phase: 'main',
          attempt: 2,
          output: {},
          result: execution.result,
        }),
      ),
    )
    render(
      <WorkflowRunInspector
        mode="history"
        projectId="project-1"
        executionId="execution-1"
        node={workflowDefinition.nodes.find((node) => node.id === 'api') ?? null}
        definition={workflowDefinition}
        execution={{
          ...execution,
          output: {
            report_kind: 'iteration',
            report_paged: true,
            record_count: 3,
            completed_count: 3,
            input_count: 3,
            failed_count: 3,
          },
        }}
        nodes={[execution]}
        context={{}}
        evidence={{ controlKind: 'iteration', controlOrdinal: 2, instanceId, instanceAttempt: 1 }}
        onSelectEvidence={onSelectEvidence}
      />,
    )
    const evidence = await screen.findByRole('region', { name: '实例执行证据' })
    expect(within(evidence).getByText(/"busy"/)).toBeVisible()
    expect(within(evidence).queryByText(/"Ada"/)).not.toBeInTheDocument()
    await browser.click(within(evidence).getByRole('combobox'))
    await browser.click(
      screen.getByText(/第 2 次/, { selector: '.ant-select-item-option-content' }),
    )
    expect(onSelectEvidence).toHaveBeenLastCalledWith({
      controlKind: 'iteration',
      controlOrdinal: 2,
      instanceId,
      instanceAttempt: 2,
    })
    expect(within(evidence).getByText(/"Ada"/)).toBeVisible()
  })

  it('shows the selected loop item and its actual failed node', async () => {
    const browser = userEvent.setup()
    const execution = apiNodeExecution()
    render(
      <WorkflowRunInspector
        mode="run"
        node={workflowDefinition.nodes.find((node) => node.id === 'api') ?? null}
        definition={workflowDefinition}
        execution={{
          ...execution,
          output: {
            input_count: 3,
            completed_count: 2,
            failed_count: 1,
            termination_reason: 'failed',
            items: [
              { input_index: 0, status: 'passed', test_verdict: 'passed', nodes: [] },
              {
                input_index: 1,
                status: 'failed',
                test_verdict: 'failed',
                nodes: [
                  {
                    node_id: 'check',
                    status: 'failed',
                    error_code: 'CASE_FAIL',
                    error_message: '第二项失败',
                  },
                ],
              },
            ],
          },
        }}
        nodes={[execution]}
        context={{}}
      />,
    )
    expect(screen.getByRole('region', { name: '循环执行详情' })).toHaveTextContent('已完成 2/3')
    await browser.click(screen.getByLabelText('选择循环轮次'))
    await browser.click(screen.getByText('第 2 项 · failed'))
    expect(screen.getByText('第二项失败')).toBeVisible()
    expect(screen.getByText('CASE_FAIL')).toBeVisible()
  })

  it('pages loop choices without losing their original input indices', async () => {
    const browser = userEvent.setup()
    const execution = apiNodeExecution()
    render(
      <WorkflowRunInspector
        mode="run"
        node={workflowDefinition.nodes.find((node) => node.id === 'api') ?? null}
        definition={workflowDefinition}
        execution={{
          ...execution,
          output: {
            input_count: 21,
            completed_count: 21,
            items: Array.from({ length: 21 }, (_, input_index) => ({
              input_index,
              status: 'passed',
              test_verdict: 'passed',
              nodes: [{ node_id: `case-${input_index}`, status: 'passed' }],
            })),
          },
        }}
        nodes={[execution]}
        context={{}}
      />,
    )
    await browser.click(screen.getByTitle('2'))
    await browser.click(screen.getByLabelText('选择循环轮次'))
    await browser.click(screen.getByText('第 21 项 · passed'))
    expect(screen.getByText('case-20 · passed')).toBeVisible()
  })

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
    expect(screen.queryByText('计时中')).not.toBeInTheDocument()
    expect(screen.getAllByText('未提供').length).toBeGreaterThanOrEqual(2)
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
