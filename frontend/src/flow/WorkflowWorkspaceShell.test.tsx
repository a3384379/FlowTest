import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import WorkflowWorkspaceShell from './WorkflowWorkspaceShell'

afterEach(() => {
  localStorage.clear()
  vi.restoreAllMocks()
})

function renderWorkspace() {
  return render(
    <WorkflowWorkspaceShell
      header={<div>工作台 Header</div>}
      preferenceKey="layout"
      list={<input aria-label="列表搜索" defaultValue="工作流" />}
    >
      <input aria-label="节点草稿" defaultValue="未保存" />
    </WorkflowWorkspaceShell>,
  )
}

it('opens a workflow directory without squeezing the canvas or losing its local draft', async () => {
  renderWorkspace()
  const trigger = screen.getByRole('button', { name: '切换工作流列表' })
  expect(trigger).toHaveAttribute('aria-expanded', 'false')
  fireEvent.click(trigger)
  expect(trigger).toHaveAttribute('aria-expanded', 'true')
  fireEvent.change(screen.getByLabelText('列表搜索'), { target: { value: '订单' } })
  fireEvent.click(screen.getByRole('button', { name: 'Close' }))
  await waitFor(() => expect(trigger).toHaveFocus())
  fireEvent.click(trigger)
  expect(screen.getByLabelText('列表搜索')).toHaveValue('订单')
  expect(screen.getByLabelText('节点草稿')).toHaveValue('未保存')
  expect(localStorage.getItem('layout')).toBeNull()
})

it('preserves existing layout and draft storage when switching to the new directory presentation', () => {
  const stored = JSON.stringify({ listWidth: 300, inspectorWidth: 480, listCollapsed: false })
  localStorage.setItem('layout', stored)
  localStorage.setItem('draft', 'retain')
  renderWorkspace()
  fireEvent.click(screen.getByRole('button', { name: '切换工作流列表' }))
  expect(screen.getByRole('dialog')).toBeVisible()
  expect(localStorage.getItem('layout')).toBe(stored)
  expect(localStorage.getItem('draft')).toBe('retain')
})

it('keeps the directory usable when stored preferences cannot be read', () => {
  vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
    throw new DOMException('disabled')
  })
  renderWorkspace()
  fireEvent.click(screen.getByRole('button', { name: '切换工作流列表' }))
  expect(screen.getByLabelText('列表搜索')).toHaveValue('工作流')
  expect(screen.getByLabelText('节点草稿')).toHaveValue('未保存')
})
