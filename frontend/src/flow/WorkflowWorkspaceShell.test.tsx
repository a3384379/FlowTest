import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import WorkflowWorkspaceShell from './WorkflowWorkspaceShell'
afterEach(() => {
  localStorage.clear()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})
it('collapses by workspace width without changing preferences, preserves input, and accepts explicit expansion', () => {
  let callback: ResizeObserverCallback = () => undefined
  vi.stubGlobal(
    'ResizeObserver',
    class {
      constructor(observe: ResizeObserverCallback) {
        callback = observe
      }
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  )
  render(
    <WorkflowWorkspaceShell
      header={<div>工作台 Header</div>}
      preferenceKey="layout"
      list={<input aria-label="列表搜索" defaultValue="工作流" />}
    >
      <input aria-label="节点草稿" defaultValue="未保存" />
    </WorkflowWorkspaceShell>,
  )
  act(() =>
    callback([{ contentRect: { width: 1050 } }] as ResizeObserverEntry[], {} as ResizeObserver),
  )
  expect(screen.getByRole('button', { name: '切换工作流列表' })).toHaveAttribute(
    'aria-expanded',
    'false',
  )
  expect(localStorage.getItem('layout')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '切换工作流列表' }))
  expect(screen.getByRole('button', { name: '切换工作流列表' })).toHaveAttribute(
    'aria-expanded',
    'true',
  )
  expect(screen.getByLabelText('列表搜索')).toHaveValue('工作流')
  expect(screen.getByLabelText('节点草稿')).toHaveValue('未保存')
  expect(JSON.parse(localStorage.getItem('layout')!).listCollapsed).toBe(false)
  fireEvent.click(screen.getByRole('button', { name: '切换工作流列表' }))
  expect(JSON.parse(localStorage.getItem('layout')!).listCollapsed).toBe(true)
})
it('forces the list closed only when the workspace cannot fit its minimum surfaces', () => {
  let callback: ResizeObserverCallback = () => undefined
  vi.stubGlobal(
    'ResizeObserver',
    class {
      constructor(observe: ResizeObserverCallback) {
        callback = observe
      }
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  )
  localStorage.setItem('layout', JSON.stringify({ listCollapsed: false }))
  render(
    <WorkflowWorkspaceShell
      header={<div>Header</div>}
      preferenceKey="layout"
      list={<div>列表</div>}
    >
      <div>画布</div>
    </WorkflowWorkspaceShell>,
  )
  act(() =>
    callback([{ contentRect: { width: 880 } }] as ResizeObserverEntry[], {} as ResizeObserver),
  )
  expect(screen.getByRole('button', { name: '切换工作流列表' })).toHaveAttribute(
    'aria-expanded',
    'false',
  )
  act(() =>
    callback([{ contentRect: { width: 1180 } }] as ResizeObserverEntry[], {} as ResizeObserver),
  )
  expect(screen.getByRole('button', { name: '切换工作流列表' })).toHaveAttribute(
    'aria-expanded',
    'true',
  )
})
it('keeps an explicit layout usable when preference storage fails', () => {
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
    throw new Error('quota')
  })
  render(
    <WorkflowWorkspaceShell
      header={<div>Header</div>}
      preferenceKey="layout"
      list={<div>列表内容</div>}
    >
      <div>画布内容</div>
    </WorkflowWorkspaceShell>,
  )
  fireEvent.click(screen.getByRole('button', { name: '切换工作流列表' }))
  expect(screen.getByRole('status')).toHaveTextContent('布局偏好未保存')
  expect(screen.getByText('画布内容')).toBeVisible()
})
