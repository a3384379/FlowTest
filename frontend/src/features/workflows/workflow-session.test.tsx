import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App as AntdApp, ConfigProvider } from 'antd'
import { createMemoryRouter, RouterProvider, Link, Outlet, useParams } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import { DraftSessionProvider } from '../drafts/DraftSessionProvider'
import { useWorkflows } from './use-workflows'
import { useAuthStore } from '../auth/auth-store'
import { workflow, workflowDefinition, user as actor } from '../../test/fixtures'

vi.mock('../projects/use-project-context', () => ({
  useProjectContext: () => ({
    projects: { data: { items: [] } },
    projectId: useParams().projectId,
    selectProject: vi.fn(),
  }),
}))
vi.mock('./workflow-service', () => ({
  listWorkflows: async () => ({ items: [workflow] }),
  listEnvironments: async () => [],
  listApis: async () => ({ items: [] }),
  listArtifacts: async () => ({ items: [] }),
  listWorkflowExecutions: async () => ({ items: [] }),
  updateWorkflowDraft: vi.fn(),
}))
vi.mock('../data-sources/data-source-service', () => ({ listCredentials: async () => [] }))
vi.mock('../protocols/protocol-service', () => ({
  listGraphQLSchemas: async () => ({ items: [] }),
  listGrpcDescriptors: async () => ({ items: [] }),
  listEventSources: async () => ({ items: [] }),
}))
function Editor() {
  const state = useWorkflows(workflow.id)
  return (
    <>
      <button
        onClick={() =>
          state.setDraftDefinition({
            ...workflowDefinition,
            nodes: workflowDefinition.nodes.map((node) => ({ ...node, name: '会话中的新稿' })),
          })
        }
      >
        编辑工作流
      </button>
      <button onClick={() => state.discardWorkflowDraft(workflow.id)}>丢弃工作流</button>
      <output>{state.draftDefinition.nodes[0]?.name}</output>
      <span>{state.draftStorageError}</span>
    </>
  )
}
afterEach(() => {
  vi.restoreAllMocks()
  localStorage.clear()
  useAuthStore.setState({ user: null })
})
it('preserves workflow memory across actual module unmounts and project switches with unavailable storage', async () => {
  useAuthStore.setState({ user: actor })
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
    throw new DOMException('quota')
  })
  const user = userEvent.setup()
  const router = createMemoryRouter(
    [
      {
        element: (
          <DraftSessionProvider>
            <Link to="/one/other">关闭当前模块</Link>
            <Link to="/two/workflows">切换项目</Link>
            <Link to="/one/workflows">返回流程模块</Link>
            <Outlet />
          </DraftSessionProvider>
        ),
        children: [
          { path: '/:projectId/workflows', element: <Editor /> },
          { path: '/:projectId/other', element: <span>其他模块</span> },
        ],
      },
    ],
    { initialEntries: ['/one/workflows'] },
  )
  render(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <AntdApp>
        <QueryClientProvider
          client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
        >
          <RouterProvider router={router} />
        </QueryClientProvider>
      </AntdApp>
    </ConfigProvider>,
  )
  await waitFor(() => expect(screen.getByRole('status')).not.toBeEmptyDOMElement())
  fireEvent.click(screen.getByText('编辑工作流'))
  expect(await screen.findByText('会话中的新稿')).toBeVisible()
  await user.click(screen.getByRole('link', { name: '关闭当前模块' }))
  await user.click(await screen.findByRole('button', { name: '保留草稿并切换' }))
  expect(await screen.findByText('其他模块')).toBeVisible()
  await user.click(screen.getByRole('link', { name: '切换项目' }))
  await user.click(await screen.findByRole('button', { name: '保留草稿并切换' }))
  await waitFor(() => expect(screen.getByRole('status')).not.toBeEmptyDOMElement())
  expect(screen.queryByText('会话中的新稿')).not.toBeInTheDocument()
  await user.click(screen.getByRole('link', { name: '返回流程模块' }))
  await user.click(await screen.findByRole('button', { name: '保留草稿并切换' }))
  expect(await screen.findByText('会话中的新稿')).toBeVisible()
  fireEvent.click(screen.getByText('丢弃工作流'))
  await waitFor(() => expect(screen.queryByText('会话中的新稿')).not.toBeInTheDocument())
  await user.click(screen.getByRole('link', { name: '关闭当前模块' }))
  expect(await screen.findByText('其他模块')).toBeVisible()
})
