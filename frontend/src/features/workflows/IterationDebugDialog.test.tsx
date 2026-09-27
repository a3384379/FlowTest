import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App as AntdApp } from 'antd'
import { http, HttpResponse } from 'msw'
import { describe, expect, it, vi } from 'vitest'

import type { WorkflowIterationDebugSession, WorkflowVersion } from '../../lib/api'
import {
  environment,
  project,
  workflow,
  workflowRunningExecution,
  workflowVersion,
} from '../../test/fixtures'
import { server } from '../../test/server'
import IterationDebugDialog from './IterationDebugDialog'

const version: WorkflowVersion = {
  ...workflowVersion,
  definition: {
    ...workflowVersion.definition,
    schema_version: '4.0',
    nodes: [
      ...workflowVersion.definition.nodes,
      {
        id: 'loop',
        type: 'capability',
        name: '重复三轮',
        position: { x: 100, y: 100 },
        config: {},
        capability_id: 'flow.control.repeat',
        configuration: { count: 3, body: { kind: 'inline', region_id: 'body' } },
      },
    ],
  },
}
const session: WorkflowIterationDebugSession = {
  execution_id: workflowRunningExecution.id,
  target_node_id: 'loop',
  pause_before_index: 0,
  pause_on_error: true,
  pause_scope: 'target_loop',
  status: 'paused',
  pause_reason: 'before_iteration',
  paused_input_index: 0,
  last_completed_index: -1,
  expires_at: '2099-09-01T00:00:00Z',
  revision: 2,
}

describe('IterationDebugDialog', () => {
  it('starts from a published serial loop and sends revisioned step and continue commands', async () => {
    let current = session
    const commands: unknown[] = []
    const onStarted = vi.fn()
    server.use(
      http.get(`/api/v1/projects/${project.id}/workflows/${workflow.id}/versions`, () =>
        HttpResponse.json([version]),
      ),
      http.post(
        `/api/v1/projects/${project.id}/workflows/${workflow.id}/debug-sessions`,
        async ({ request }) => {
          expect(await request.json()).toMatchObject({
            environment_id: environment.id,
            version: version.version,
            loop_node_id: 'loop',
            pause_before_index: 0,
            pause_on_error: true,
            pause_scope: 'target_loop',
          })
          return HttpResponse.json({ execution: workflowRunningExecution, session: current })
        },
      ),
      http.get(
        `/api/v1/projects/${project.id}/workflow-executions/${session.execution_id}/debug-session`,
        () => HttpResponse.json(current),
      ),
      http.post(
        `/api/v1/projects/${project.id}/workflow-executions/${session.execution_id}/debug-session/commands`,
        async ({ request }) => {
          const payload = await request.json()
          commands.push(payload)
          current = {
            ...current,
            revision: current.revision + 1,
            status: 'paused',
            pause_reason: 'step_completed',
          }
          return HttpResponse.json(current)
        },
      ),
    )
    render(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <AntdApp>
          <IterationDebugDialog
            open
            projectId={project.id}
            workflowId={workflow.id}
            environmentId={environment.id}
            version={version.version}
            currentExecution={null}
            canStart
            onStarted={onStarted}
            onClose={vi.fn()}
          />
        </AntdApp>
      </QueryClientProvider>,
    )
    const browser = userEvent.setup()
    await browser.click(await screen.findByText('启动逐轮调试'))
    await waitFor(() => expect(onStarted).toHaveBeenCalledWith(workflowRunningExecution))
    await browser.click(await screen.findByRole('button', { name: '单步一轮' }))
    await waitFor(() => expect(commands).toContainEqual({ action: 'step', expected_revision: 2 }))
    await browser.click(screen.getByRole('button', { name: '继续运行' }))
    await waitFor(() =>
      expect(commands).toContainEqual({ action: 'continue', expected_revision: 3 }),
    )
  })
})
