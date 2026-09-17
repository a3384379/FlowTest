import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { globalPath, sectionFromPath } from '../projects/project-routing'
import ShellSidebar from './ShellSidebar'

function Workspace({ admin = true }: { admin?: boolean }) {
  const location = useLocation()
  const navigate = useNavigate()
  const [value, setValue] = useState('未保存草稿')
  return (
    <>
      <ShellSidebar
        userId="alice"
        isSystemAdmin={admin}
        section={sectionFromPath(location.pathname)}
        pathFor={globalPath}
      />
      <output data-testid="location">
        {location.pathname}
        {location.search}
        {location.hash}
      </output>
      <input
        aria-label="本地草稿"
        value={value}
        onChange={(event) => setValue(event.target.value)}
      />
      <button onClick={() => navigate('/reports')}>打开报告 Tab</button>
      <button onClick={() => navigate(-1)}>后退</button>
      <button onClick={() => setValue('普通 render')}>重新渲染</button>
    </>
  )
}

function renderWorkspace(route = '/workflows?focus=node&proposal=p#draft', admin = true) {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <Workspace admin={admin} />
    </MemoryRouter>,
  )
}

function mockViewport(width: number) {
  const listeners = new Set<() => void>()
  let current = width
  vi.spyOn(window, 'matchMedia').mockImplementation((query) => ({
    get matches() {
      return current <= Number(query.match(/max-width: (\d+)/)?.[1] ?? 0)
    },
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: () => true,
    addEventListener: (_event: string, listener: EventListenerOrEventListenerObject) =>
      listeners.add(listener as () => void),
    removeEventListener: (_event: string, listener: EventListenerOrEventListenerObject) =>
      listeners.delete(listener as () => void),
  }))
  return (next: number) =>
    act(() => {
      current = next
      listeners.forEach((listener) => listener())
    })
}

describe('grouped shell navigation', () => {
  beforeEach(() => localStorage.clear())
  afterEach(() => vi.restoreAllMocks())

  it('keeps URL, local draft and manually closed active group stable across ordinary renders', async () => {
    const browser = userEvent.setup()
    localStorage.setItem(
      'flowtest:navigation:v1:alice',
      JSON.stringify({ openKeys: ['nav:system'] }),
    )
    renderWorkspace()
    const group = screen.getByRole('menuitem', { name: '测试设计' })
    expect(group).toHaveAttribute('aria-expanded', 'true')
    await browser.click(group)
    await browser.click(screen.getByRole('button', { name: '重新渲染' }))
    expect(group).toHaveAttribute('aria-expanded', 'false')
    await browser.click(screen.getByRole('menuitem', { name: '项目与接口' }))
    expect(screen.getByTestId('location')).toHaveTextContent(
      '/workflows?focus=node&proposal=p#draft',
    )
    expect(screen.getByLabelText('本地草稿')).toHaveValue('普通 render')
    await browser.click(screen.getByRole('button', { name: '收起侧栏' }))
    await browser.click(screen.getByRole('button', { name: '展开侧栏' }))
    expect(group).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByLabelText('本地草稿')).toHaveValue('普通 render')
  })

  it('navigates via row and collapsed dashboard icon activation without a text Link', async () => {
    const browser = userEvent.setup()
    renderWorkspace()
    await browser.click(screen.getByRole('button', { name: '收起侧栏' }))
    await browser.click(screen.getByRole('menuitem', { name: '质量总览' }))
    expect(screen.getByTestId('location')).toHaveTextContent('/dashboard')
  })

  it('opens the matching parent on Tab navigation and browser history, and uses an accordion', async () => {
    const browser = userEvent.setup()
    renderWorkspace()
    await browser.click(screen.getByRole('menuitem', { name: '项目与接口' }))
    expect(screen.getByRole('menuitem', { name: '测试设计' })).toHaveAttribute(
      'aria-expanded',
      'false',
    )
    await browser.click(screen.getByRole('button', { name: '打开报告 Tab' }))
    expect(screen.getByRole('menuitem', { name: '质量分析' })).toHaveAttribute(
      'aria-expanded',
      'true',
    )
    await browser.click(screen.getByRole('button', { name: '后退' }))
    expect(screen.getByRole('menuitem', { name: '测试设计' })).toHaveAttribute(
      'aria-expanded',
      'true',
    )
    expect(screen.getByRole('menuitem', { name: '质量分析' })).toHaveAttribute(
      'aria-expanded',
      'false',
    )
  })

  it('defaults the dashboard to closed parents and filters admin leaves after role changes', async () => {
    const browser = userEvent.setup()
    const view = renderWorkspace('/dashboard')
    await browser.click(screen.getByRole('menuitem', { name: '系统管理' }))
    await waitFor(() => expect(screen.getByRole('link', { name: '平台管理' })).toBeVisible())
    view.rerender(
      <MemoryRouter initialEntries={['/dashboard']}>
        <Workspace admin={false} />
      </MemoryRouter>,
    )
    await browser.click(screen.getByRole('menuitem', { name: '系统管理' }))
    await waitFor(() => expect(screen.getByRole('link', { name: '组织治理' })).toBeVisible())
    expect(screen.queryByRole('link', { name: '平台管理' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: '分布式执行面' })).not.toBeInTheDocument()
  })

  it('defaults compact screens to collapsed without overwriting the explicit desktop preference', async () => {
    const resize = mockViewport(1100)
    const browser = userEvent.setup()
    renderWorkspace('/dashboard')
    expect(screen.getByRole('button', { name: '展开侧栏' })).toBeVisible()
    expect(localStorage.getItem('flowtest:navigation:v1:alice')).toBeNull()
    resize(1440)
    await browser.click(screen.getByRole('button', { name: '收起侧栏' }))
    resize(1100)
    resize(1920)
    expect(screen.getByRole('button', { name: '展开侧栏' })).toBeVisible()
    expect(JSON.parse(localStorage.getItem('flowtest:navigation:v1:alice')!).collapsed).toBe(true)
  })

  it('uses a narrow-screen drawer, closes after choosing a leaf and restores trigger focus', async () => {
    mockViewport(390)
    const browser = userEvent.setup()
    renderWorkspace('/dashboard')
    const trigger = screen.getByRole('button', { name: '打开导航' })
    await browser.click(trigger)
    const drawer = await screen.findByRole('dialog')
    await browser.click(within(drawer).getByRole('menuitem', { name: '测试设计' }))
    await browser.click(within(drawer).getByRole('link', { name: '流程编排' }))
    expect(screen.getByTestId('location')).toHaveTextContent('/workflows')
    await waitFor(() => expect(trigger).toHaveFocus())
    await browser.click(trigger)
    fireEvent.keyDown(await screen.findByRole('dialog'), { key: 'Escape', keyCode: 27 })
    await waitFor(() => expect(trigger).toHaveAttribute('aria-expanded', 'false'))
    expect(localStorage.getItem('flowtest:navigation:v1:alice')).toEqual(expect.any(String))
  })
})
