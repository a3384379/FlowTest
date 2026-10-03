import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App, ConfigProvider } from 'antd'
import { createMemoryRouter, Link, RouterProvider, useLocation } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { DraftSessionProvider } from '../drafts/DraftSessionProvider'
import APIWorkbench from '../api-console/APIWorkbench'
import type { ApiDetail } from '../../lib/api'
import { apiDefinition, project, user, workflow } from '../../test/fixtures'
import WorkspaceObjectTabs from './WorkspaceObjectTabs'
import { readWorkspaceTabs } from './workspace-tab-store'

const flowHref = `/projects/${project.id}/workflows?focus=${workflow.id}&execution=run-1&node=loop&attempt=2&control_kind=iteration&control_ordinal=3&instance=__nested_request__%3Aitem&instance_attempt=2`
const apiHref = `/projects/${project.id}/apis?focus=${apiDefinition.id}`
const reportHref = `/projects/${project.id}/reports?execution=run-1&node=loop&attempt=2&control_ordinal=3`
const save = vi.fn()

function apiDetail(id: string): ApiDetail {
  return {
    definition: { ...apiDefinition, id, name: id === apiDefinition.id ? '接口A' : '接口B' },
    version: {
      id: 'api-v1',
      api_definition_id: id,
      version: 1,
      method: 'GET',
      path: '/users',
      query_parameters: [],
      headers: {},
      body_kind: 'none',
      body: null,
      auth_kind: 'none',
      auth_config: {},
      extraction_rules: [],
      assertions: [],
      created_at: '2026-10-01T00:00:00Z',
    },
  }
}

function Workspace() {
  const location = useLocation()
  const id = new URLSearchParams(location.search).get('focus') ?? apiDefinition.id
  return (
    <>
      <WorkspaceObjectTabs userId={user.id} projectId={project.id} />
      <Link to={flowHref}>打开流程A</Link>
      <Link to={`${apiHref.replace(apiDefinition.id, 'api-B')}&execution=api-run`}>打开接口B</Link>
      <Link to={apiHref}>打开接口A</Link>
      <Link to={reportHref}>打开报告A</Link>
      <output aria-label="当前定位">
        {location.pathname}
        {location.search}
        {location.hash}
      </output>
      {location.pathname.endsWith('/apis') && (
        <APIWorkbench
          detail={apiDetail(id)}
          editable
          loading={false}
          saving={false}
          previewing={false}
          onSave={save}
          onPreview={vi.fn()}
          onRename={vi.fn()}
          draftScope={`${user.id}:${project.id}`}
        />
      )}
    </>
  )
}

function renderWorkspace(initialEntry = apiHref) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  client.setQueryData(['api-detail', project.id, apiDefinition.id], apiDetail(apiDefinition.id))
  client.setQueryData(['api-detail', project.id, 'api-B'], apiDetail('api-B'))
  client.setQueryData(['workflow', project.id, workflow.id], { ...workflow, name: '流程A' })
  client.setQueryData(['report-detail', project.id, 'run-1'], {
    summary: { workflow_name: '流程A' },
  })
  const router = createMemoryRouter(
    [
      {
        path: '*',
        element: (
          <DraftSessionProvider>
            <Workspace />
          </DraftSessionProvider>
        ),
      },
    ],
    { initialEntries: [initialEntry] },
  )
  return render(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <App>
        <QueryClientProvider client={client}>
          <RouterProvider router={router} />
        </QueryClientProvider>
      </App>
    </ConfigProvider>,
  )
}

function closeTab(name: RegExp) {
  const tab = screen.getByRole('tab', { name })
  fireEvent.click(within(tab.parentElement!).getByRole('button'))
}

afterEach(() => {
  localStorage.clear()
  vi.restoreAllMocks()
  save.mockClear()
})

describe('global object workspace tabs', () => {
  it('opens workflow API and report object tabs and restores their exact contexts after reload', async () => {
    const browser = userEvent.setup()
    const view = renderWorkspace()
    await screen.findByRole('tab', { name: '接口 · 接口A' })
    await browser.click(screen.getByRole('link', { name: '打开流程A' }))
    await screen.findByRole('tab', { name: '流程 · 流程A' })
    await screen.findByRole('tab', { name: '流程 · 流程A' })
    await browser.click(screen.getByRole('link', { name: '打开接口B' }))
    await screen.findByRole('tab', { name: '接口 · 接口B' })
    await browser.click(screen.getByRole('link', { name: '打开报告A' }))
    await screen.findByRole('tab', { name: /报告 · 流程A · run-1/ })
    await browser.click(screen.getByRole('tab', { name: '流程 · 流程A' }))
    expect(screen.getByLabelText('当前定位')).toHaveTextContent(flowHref)
    await waitFor(() => expect(readWorkspaceTabs(user.id, project.id).tabs).toHaveLength(4))
    view.unmount()
    renderWorkspace(reportHref)
    await browser.click(await screen.findByRole('tab', { name: '接口 · 接口B' }))
    expect(screen.getByLabelText('当前定位')).toHaveTextContent('focus=api-B&execution=api-run')
    await browser.click(screen.getByRole('tab', { name: '流程 · 流程A' }))
    expect(screen.getByLabelText('当前定位')).toHaveTextContent(flowHref)
  })

  it('closes other object tabs from the context menu while retaining the selected object', async () => {
    const browser = userEvent.setup()
    renderWorkspace()
    await screen.findByRole('tab', { name: '接口 · 接口A' })
    await browser.click(screen.getByRole('link', { name: '打开接口B' }))
    await screen.findByRole('tab', { name: '接口 · 接口B' })
    await browser.click(screen.getByRole('link', { name: '打开流程A' }))
    const flowTab = await screen.findByRole('tab', { name: '流程 · 流程A' })
    fireEvent.contextMenu(within(flowTab).getByText('流程 · 流程A'))
    await browser.click(await screen.findByRole('menuitem', { name: '关闭其他标签' }))
    await waitFor(() =>
      expect(screen.queryByRole('tab', { name: /接口 · 接口/ })).not.toBeInTheDocument(),
    )
    expect(screen.getByRole('tab', { name: '流程 · 流程A' })).toBeVisible()
    expect(screen.getByLabelText('当前定位')).toHaveTextContent(flowHref)
  })

  it('asks before closing an inactive API draft and preserves it for reopening', async () => {
    const browser = userEvent.setup()
    renderWorkspace()
    await screen.findByRole('tab', { name: '接口 · 接口A' })
    fireEvent.change(screen.getByLabelText('请求路径'), { target: { value: '/draft-path' } })
    await waitFor(() =>
      expect(screen.getByRole('tab', { name: /接口 · 接口A/ })).toHaveTextContent('接口 · 接口A ·'),
    )
    await browser.click(screen.getByRole('link', { name: '打开流程A' }))
    closeTab(/接口 · 接口A/)
    const dialog = await screen.findByRole('dialog')
    await browser.click(within(dialog).getByRole('button', { name: '继续编辑' }))
    expect(screen.getByRole('tab', { name: /接口 · 接口A/ })).toBeVisible()
    closeTab(/接口 · 接口A/)
    await browser.click(
      within(await screen.findByRole('dialog')).getByRole('button', { name: '保留草稿并关闭标签' }),
    )
    await waitFor(() =>
      expect(screen.queryByRole('tab', { name: /接口 · 接口A/ })).not.toBeInTheDocument(),
    )
    await browser.click(screen.getByRole('link', { name: '打开接口A' }))
    expect(await screen.findByDisplayValue('/draft-path')).toBeVisible()
    expect(save).not.toHaveBeenCalled()
  })

  it('keeps the active tab on cancelled navigation and closes only after the draft guard accepts', async () => {
    const browser = userEvent.setup()
    renderWorkspace()
    await screen.findByRole('tab', { name: '接口 · 接口A' })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('quota')
    })
    fireEvent.change(screen.getByLabelText('请求路径'), { target: { value: '/memory-only' } })
    closeTab(/接口 · 接口A/)
    await browser.click(
      within(await screen.findByRole('dialog')).getByRole('button', { name: '留在当前页保存' }),
    )
    expect(screen.getByRole('tab', { name: /接口 · 接口A/ })).toBeVisible()
    expect(screen.getByDisplayValue('/memory-only')).toBeVisible()
    await browser.click(screen.getByRole('link', { name: '打开流程A' }))
    await browser.click(
      within(await screen.findByRole('dialog')).getByRole('button', { name: '保留草稿并切换' }),
    )
    await screen.findByRole('tab', { name: '流程 · 流程A' })
    expect(screen.getByRole('tab', { name: /接口 · 接口A/ })).toBeVisible()
    await browser.click(screen.getByRole('tab', { name: /接口 · 接口A/ }))
    await browser.click(
      within(await screen.findByRole('dialog')).getByRole('button', { name: '保留草稿并切换' }),
    )
    expect(await screen.findByDisplayValue('/memory-only')).toBeVisible()
    closeTab(/接口 · 接口A/)
    await browser.click(
      within(await screen.findByRole('dialog')).getByRole('button', { name: '保留草稿并切换' }),
    )
    await waitFor(() =>
      expect(screen.queryByRole('tab', { name: /接口 · 接口A/ })).not.toBeInTheDocument(),
    )
    await browser.click(screen.getByRole('link', { name: '打开接口A' }))
    await browser.click(
      within(await screen.findByRole('dialog')).getByRole('button', { name: '保留草稿并切换' }),
    )
    expect(await screen.findByDisplayValue('/memory-only')).toBeVisible()
  })
})
