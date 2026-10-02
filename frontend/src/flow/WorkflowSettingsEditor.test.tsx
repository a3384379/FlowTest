import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import WorkflowSettingsEditor from './WorkflowSettingsEditor'
import { workflowDefinition } from '../test/fixtures'
import type { WorkflowDefinition } from '../lib/api'

describe('WorkflowSettingsEditor', () => {
  it('validates new variables and preserves execution policy and graph content', async () => {
    const browser = userEvent.setup()
    const onChange = vi.fn()
    const initial: WorkflowDefinition = {
      ...workflowDefinition,
      variables: { order_id: 'initial' },
      run_policy: {
        request_budget: 30,
        max_runtime_seconds: 90,
        cleanup_request_budget: 2,
        force_cancel_skips_cleanup: false,
      },
    }
    function Harness() {
      const [definition, setDefinition] = useState(initial)
      return (
        <WorkflowSettingsEditor
          definition={definition}
          editable
          historical={false}
          beforeOpen={() => Promise.resolve(true)}
          onChange={(next) => {
            onChange(next)
            setDefinition(next)
          }}
        />
      )
    }
    render(<Harness />)
    await browser.click(screen.getByRole('button', { name: '流程设置' }))
    fireEvent.change(await screen.findByRole('textbox', { name: '新变量名' }), {
      target: { value: 'order_id' },
    })
    await browser.click(screen.getByRole('button', { name: '添加变量' }))
    await waitFor(() => expect(screen.getByText('变量名已存在')).toBeVisible())
    expect(onChange).not.toHaveBeenCalled()
    fireEvent.change(screen.getByRole('textbox', { name: '新变量名' }), {
      target: { value: '1invalid' },
    })
    await browser.click(screen.getByRole('button', { name: '添加变量' }))
    await waitFor(() => expect(screen.getByText(/使用字母或下划线开头/)).toBeVisible())
    expect(onChange).not.toHaveBeenCalled()
    fireEvent.change(screen.getByRole('textbox', { name: '新变量名' }), {
      target: { value: 'expected.amount' },
    })
    fireEvent.change(screen.getByRole('textbox', { name: '新变量初始值' }), {
      target: { value: '29900' },
    })
    await browser.click(screen.getByRole('button', { name: '添加变量' }))
    await waitFor(() => expect(onChange).toHaveBeenCalledOnce())
    const next = onChange.mock.calls[0][0] as WorkflowDefinition
    expect(next.variables).toEqual({ order_id: 'initial', 'expected.amount': '29900' })
    expect(next.run_policy).toEqual(initial.run_policy)
    expect(next.nodes).toEqual(initial.nodes)
    expect(next.edges).toEqual(initial.edges)
    await browser.click(screen.getByRole('button', { name: '删除变量 expected.amount' }))
    await browser.click(await screen.findByRole('button', { name: '确认删除变量' }))
    expect(onChange.mock.lastCall?.[0].variables).toEqual({ order_id: 'initial' })
  })

  it('keeps the settings closed when unapplied node edits cancel the transition', async () => {
    const browser = userEvent.setup()
    render(
      <WorkflowSettingsEditor
        definition={workflowDefinition}
        editable
        historical={false}
        beforeOpen={() => Promise.resolve(false)}
        onChange={vi.fn()}
      />,
    )
    await browser.click(screen.getByRole('button', { name: '流程设置' }))
    expect(screen.queryByRole('spinbutton', { name: '并发上限' })).not.toBeInTheDocument()
  })
})
