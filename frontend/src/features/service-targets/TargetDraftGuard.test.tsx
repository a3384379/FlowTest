import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App, ConfigProvider, Input } from 'antd'
import { Link, Outlet, RouterProvider, createMemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { DraftSessionProvider } from '../drafts/DraftSessionProvider'
import TargetDraftGuard from './TargetDraftGuard'

function Editor() {
  return (
    <>
      <TargetDraftGuard projectId="project-one" dirty />
      <Input aria-label="未保存的候选名称" defaultValue="原候选" />
      <Link to="/other">切换模块</Link>
    </>
  )
}
function Layout() {
  return (
    <DraftSessionProvider>
      <Outlet />
    </DraftSessionProvider>
  )
}

describe('request target navigation protection', () => {
  it('uses the shared blocker, retains cancelled input and discards only after explicit navigation', async () => {
    const router = createMemoryRouter([
      {
        path: '/',
        element: <Layout />,
        children: [
          { index: true, element: <Editor /> },
          { path: 'other', element: <h1>其他模块</h1> },
        ],
      },
    ])
    render(
      <ConfigProvider theme={{ token: { motion: false } }}>
        <App>
          <RouterProvider router={router} />
        </App>
      </ConfigProvider>,
    )
    const browser = userEvent.setup()
    await browser.type(screen.getByRole('textbox', { name: '未保存的候选名称' }), '修改')
    const unload = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(unload)
    expect(unload.defaultPrevented).toBe(true)
    await browser.click(screen.getByRole('link', { name: '切换模块' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText('请求目标候选尚未保存')).toBeInTheDocument()
    await browser.click(within(dialog).getByRole('button', { name: '留在当前页保存' }))
    expect(router.state.location.pathname).toBe('/')
    expect(screen.getByRole('textbox', { name: '未保存的候选名称' })).toHaveValue('原候选修改')
    await browser.click(screen.getByRole('link', { name: '切换模块' }))
    const confirmed = await screen.findByRole('dialog')
    await browser.click(within(confirmed).getByRole('button', { name: '放弃候选并切换' }))
    await screen.findByRole('heading', { name: '其他模块' })
    await waitFor(() => expect(router.state.location.pathname).toBe('/other'))
    const cleanUnload = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(cleanUnload)
    expect(cleanUnload.defaultPrevented).toBe(false)
  })
})
