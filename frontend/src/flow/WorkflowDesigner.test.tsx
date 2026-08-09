import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import WorkflowDesigner from './WorkflowDesigner'
import { apiDefinition, workflowDefinition } from '../test/fixtures'

describe('WorkflowDesigner', () => {
  it('locks the published execution snapshot while a run is active', () => {
    render(
      <WorkflowDesigner
        definition={workflowDefinition}
        apis={[apiDefinition]}
        statuses={{ api: 'running' }}
        editable={false}
        onChange={vi.fn()}
      />,
    )

    expect(screen.getByRole('button', { name: /添加接口节点/ })).toBeDisabled()
    expect(screen.getByRole('button', { name: /添加结束节点/ })).toBeDisabled()
    fireEvent.click(screen.getByText('查询用户'))
    expect(screen.getByDisplayValue('查询用户')).toBeDisabled()
    expect(screen.getByRole('button', { name: /删除节点/ })).toBeDisabled()
    expect(screen.getByText('运行中')).toBeVisible()
  })

  it('shows an empty state before a workflow is selected', () => {
    render(
      <WorkflowDesigner
        definition={{
          schema_version: '1.0',
          nodes: [],
          edges: [],
          settings: { fail_fast: true, concurrency: 20, default_timeout_seconds: 30 },
        }}
        apis={[]}
        statuses={{}}
        editable
        onChange={vi.fn()}
      />,
    )

    expect(screen.getByText('请选择工作流')).toBeVisible()
  })
})
