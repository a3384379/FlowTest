import { describe, expect, it } from 'vitest'
import {
  executionAttempt,
  reportExecutionPath,
  workflowExecutionPath,
} from './execution-navigation'

describe('execution navigation', () => {
  it('keeps the project, execution, node and request attempt across both views', () => {
    const location = {
      workflowId: 'workflow-2',
      executionId: 'run-3',
      nodeId: '订单 & 校验',
      attempt: 2,
    }
    const workflowUrl = new URL(
      workflowExecutionPath('project-1', location),
      'https://flowtest.test',
    )
    const reportUrl = new URL(reportExecutionPath('project-1', location), 'https://flowtest.test')
    expect(workflowUrl.pathname).toBe('/projects/project-1/workflows')
    expect(workflowUrl.searchParams.get('focus')).toBe('workflow-2')
    for (const url of [workflowUrl, reportUrl]) {
      expect(url.searchParams.get('execution')).toBe('run-3')
      expect(url.searchParams.get('node')).toBe(location.nodeId)
      expect(executionAttempt(url.searchParams)).toBe(2)
    }
  })

  it('allows frozen snapshots without a current workflow and ignores invalid attempts', () => {
    expect(workflowExecutionPath('project-1', { executionId: 'run-3', workflowId: null })).toBe(
      '/projects/project-1/workflows?execution=run-3',
    )
    expect(reportExecutionPath('project-1', { executionId: 'run-3', attempt: 2 })).toBe(
      '/projects/project-1/reports?execution=run-3',
    )
    for (const value of ['0', '-1', '1.2', 'abc', '9007199254740992'])
      expect(executionAttempt(new URLSearchParams({ attempt: value }))).toBeUndefined()
  })
})
