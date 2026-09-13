import WorkflowRequestDrawer from './WorkflowRequestDrawer'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { useEffect, useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import WorkflowInspectorShell from './WorkflowInspectorShell'
import WorkflowContextMenu from './WorkflowContextMenu'
afterEach(() => {
  localStorage.clear()
  vi.unstubAllGlobals()
})
describe('workflow editor surfaces', () => {
  it('keeps the same form instance across maximize, keyboard restore, and responsive overlay', () => {
    let observe: ResizeObserverCallback = () => undefined
    vi.stubGlobal(
      'ResizeObserver',
      class {
        constructor(callback: ResizeObserverCallback) {
          observe = callback
        }
        observe() {}
        disconnect() {}
        unobserve() {}
      },
    )
    const mounted = vi.fn()
    function Input() {
      const [value, setValue] = useState('')
      useEffect(mounted, [])
      return (
        <input
          aria-label="未完成配置"
          value={value}
          onChange={(event) => setValue(event.target.value)}
        />
      )
    }
    const close = vi.fn()
    render(
      <WorkflowInspectorShell
        canvas={<div>画布</div>}
        visible
        onClose={close}
        preferenceKey="layout"
      >
        <Input />
      </WorkflowInspectorShell>,
    )
    fireEvent.change(screen.getByLabelText('未完成配置'), { target: { value: '{"unfinished":' } })
    fireEvent.click(screen.getByRole('button', { name: '最大化配置' }))
    expect(screen.getByRole('dialog')).toBeVisible()
    const first = screen.getByRole('button', { name: '还原配置' })
    first.focus()
    fireEvent.keyDown(first, { key: 'Tab', shiftKey: true })
    expect(screen.getByLabelText('未完成配置')).toHaveFocus()
    fireEvent.keyDown(screen.getByLabelText('未完成配置'), { key: 'Tab' })
    expect(first).toHaveFocus()
    fireEvent.keyDown(first, { key: 'Escape', isComposing: true })
    expect(screen.getByRole('dialog')).toBeVisible()
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    act(() =>
      observe([{ contentRect: { width: 740 } }] as ResizeObserverEntry[], {} as ResizeObserver),
    )
    expect(screen.getByLabelText('未完成配置')).toHaveValue('{"unfinished":')
    expect(mounted).toHaveBeenCalledTimes(1)
    fireEvent.click(screen.getByRole('button', { name: '关闭配置' }))
    expect(close).toHaveBeenCalled()
  })
  it.each([
    'not-json',
    'null',
    '{"inspectorWidth":10000}',
    '{"inspectorWidth":50}',
    '{"inspectorWidth":"wrong"}',
  ])('tolerates malformed and out-of-range preferences: %s', (value) => {
    localStorage.setItem('layout', value)
    render(
      <WorkflowInspectorShell
        canvas={<div>画布</div>}
        visible={false}
        onClose={vi.fn()}
        preferenceKey="layout"
      >
        <input aria-label="隐藏配置" />
      </WorkflowInspectorShell>,
    )
    expect(screen.getByText('画布')).toBeVisible()
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
    expect(localStorage.getItem('layout')).toBe(value)
  })
  it('dispatches the chosen context action once and rejects disabled actions', () => {
    const run = vi.fn()
    const close = vi.fn()
    render(
      <WorkflowContextMenu
        point={{ x: 100, y: 100 }}
        actions={[
          { key: 'delete', label: '删除选中对象', run },
          { key: 'edit', label: '不可修改', disabled: true, run },
        ]}
        onClose={close}
      />,
    )
    fireEvent.click(screen.getByText('不可修改'))
    expect(run).not.toHaveBeenCalled()
    fireEvent.click(screen.getByText('删除选中对象'))
    expect(run).toHaveBeenCalledTimes(1)
    expect(close).toHaveBeenCalled()
  })
})

it('resizes the same request drawer instance to the viewport and maximizes without losing raw input', () => {
  const close = vi.fn()
  const view = render(
    <WorkflowRequestDrawer open projectId="project" onClose={close}>
      <input aria-label="原始请求" defaultValue="unfinished" />
    </WorkflowRequestDrawer>,
  )
  fireEvent.change(screen.getByLabelText('原始请求'), { target: { value: '{"raw":' } })
  fireEvent.click(screen.getByRole('button', { name: '最大化' }))
  expect(screen.getByRole('button', { name: /还\s*原/ })).toBeVisible()
  expect(screen.getByLabelText('原始请求')).toHaveValue('{"raw":')
  fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape', keyCode: 27 })
  expect(close).not.toHaveBeenCalled()
  expect(screen.getByRole('button', { name: '最大化' })).toBeVisible()
  expect(screen.getByLabelText('原始请求')).toHaveValue('{"raw":')
  vi.stubGlobal('innerWidth', 500)
  fireEvent(window, new Event('resize'))
  expect(document.querySelector('.ant-drawer-content-wrapper')).toHaveStyle({ width: '500px' })
  fireEvent.click(screen.getByRole('button', { name: 'Close' }))
  expect(close).toHaveBeenCalled()
  view.rerender(
    <WorkflowRequestDrawer open={false} projectId="project" onClose={close}>
      <input aria-label="原始请求" defaultValue="unfinished" />
    </WorkflowRequestDrawer>,
  )
  view.rerender(
    <WorkflowRequestDrawer open projectId="project" onClose={close}>
      <input aria-label="原始请求" defaultValue="unfinished" />
    </WorkflowRequestDrawer>,
  )
  expect(screen.getByLabelText('原始请求')).toHaveValue('{"raw":')
})
