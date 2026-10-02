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

describe('task rail and full module directory', () => {
  beforeEach(() => localStorage.clear())
  afterEach(() => vi.restoreAllMocks())

  async function openDirectory(browser: ReturnType<typeof userEvent.setup>) {
    await browser.click(screen.getByRole('button', { name: '全部模块' }))
    return within(await screen.findByRole('dialog'))
  }

  it('keeps the six task shortcuts and preserves deep links and drafts while searching the directory', async () => {
    const browser = userEvent.setup()
    renderWorkspace()
    expect(
      within(screen.getByRole('navigation', { name: '常用任务' })).getAllByRole('link'),
    ).toHaveLength(6)
    const directory = await openDirectory(browser)
    await browser.type(directory.getByLabelText('搜索模块'), '协议')
    expect(directory.getByRole('link', { name: '多协议工作台' })).toHaveAttribute(
      'href',
      '/protocols',
    )
    expect(directory.queryByRole('link', { name: '平台管理' })).not.toBeInTheDocument()
    expect(screen.getByTestId('location')).toHaveTextContent(
      '/workflows?focus=node&proposal=p#draft',
    )
    expect(screen.getByLabelText('本地草稿')).toHaveValue('未保存草稿')
  })

  it('restores a manually expanded dashboard group without overwriting the old collapse preference', async () => {
    const browser = userEvent.setup()
    localStorage.setItem(
      'flowtest:navigation:v1:alice',
      JSON.stringify({ collapsed: true, openKeys: [] }),
    )
    const view = renderWorkspace('/dashboard')
    const directory = await openDirectory(browser)
    const group = directory.getByRole('menuitem', { name: '质量分析' })
    expect(group).toHaveAttribute('aria-expanded', 'false')
    await browser.click(group)
    view.unmount()
    renderWorkspace('/dashboard')
    const restored = await openDirectory(browser)
    expect(restored.getByRole('menuitem', { name: '质量分析' })).toHaveAttribute(
      'aria-expanded',
      'true',
    )
    expect(JSON.parse(localStorage.getItem('flowtest:navigation:v1:alice')!).collapsed).toBe(true)
  })

  it('keeps a manually closed group stable across ordinary renders', async () => {
    const browser = userEvent.setup()
    renderWorkspace()
    const directory = await openDirectory(browser)
    const group = directory.getByRole('menuitem', { name: '测试设计' })
    await browser.click(group)
    await browser.click(screen.getByRole('button', { name: '重新渲染' }))
    expect(group).toHaveAttribute('aria-expanded', 'false')
    expect(screen.getByLabelText('本地草稿')).toHaveValue('普通 render')
  })

  it('tracks task navigation and browser history without discarding drafts', async () => {
    const browser = userEvent.setup()
    renderWorkspace()
    await browser.click(screen.getByRole('link', { name: '测试报告' }))
    expect(screen.getByTestId('location')).toHaveTextContent('/reports')
    expect(screen.getByRole('link', { name: '测试报告' })).toHaveAttribute('aria-current', 'page')
    await browser.click(screen.getByRole('button', { name: '后退' }))
    expect(screen.getByTestId('location')).toHaveTextContent(
      '/workflows?focus=node&proposal=p#draft',
    )
    const directory = await openDirectory(browser)
    expect(directory.getByRole('menuitem', { name: '测试设计' })).toHaveAttribute(
      'aria-expanded',
      'true',
    )
    expect(screen.getByLabelText('本地草稿')).toHaveValue('未保存草稿')
  })

  it('filters administrator modules from both browsing and search after role changes', async () => {
    const browser = userEvent.setup()
    const view = renderWorkspace('/dashboard')
    const directory = await openDirectory(browser)
    await browser.type(directory.getByLabelText('搜索模块'), '平台')
    expect(directory.getByRole('link', { name: '平台管理' })).toBeVisible()
    view.rerender(
      <MemoryRouter initialEntries={['/dashboard']}>
        <Workspace admin={false} />
      </MemoryRouter>,
    )
    const filtered = await openDirectory(browser)
    expect(filtered.queryByRole('link', { name: '平台管理' })).not.toBeInTheDocument()
    await browser.clear(filtered.getByLabelText('搜索模块'))
    await browser.click(filtered.getByRole('menuitem', { name: '系统管理' }))
    await waitFor(() => expect(filtered.getByRole('link', { name: '组织治理' })).toBeVisible())
    expect(filtered.queryByRole('link', { name: '分布式执行面' })).not.toBeInTheDocument()
  })

  it('uses the same compact rail at desktop widths without changing saved preferences', () => {
    const resize = mockViewport(1100)
    localStorage.setItem(
      'flowtest:navigation:v1:alice',
      JSON.stringify({ collapsed: true, openKeys: [] }),
    )
    renderWorkspace('/dashboard')
    expect(screen.getByRole('button', { name: '全部模块' })).toBeVisible()
    resize(1920)
    expect(screen.getByRole('button', { name: '全部模块' })).toBeVisible()
    expect(JSON.parse(localStorage.getItem('flowtest:navigation:v1:alice')!).collapsed).toBe(true)
  })

  it('closes the mobile directory on navigation or Escape and restores trigger focus', async () => {
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
  })
})
