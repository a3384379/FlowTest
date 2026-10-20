import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App, ConfigProvider } from 'antd'
import { createMemoryRouter, Link, Outlet, RouterProvider, useSearchParams } from 'react-router-dom'
import { expect, it } from 'vitest'
import { DraftSessionProvider } from './DraftSessionProvider'
import { useProtocolRequestDraft } from '../protocols/use-protocol-request-draft'
import type { GraphQLRequestDraft } from '../protocols/protocol-request-draft'

const root = '/projects/00000000-0000-4000-8000-000000000101'
function ProtocolDraft() {
  const [params, setParams] = useSearchParams()
  const mode = params.get('mode') ?? 'graphql'
  const state = useProtocolRequestDraft<GraphQLRequestDraft>('protocol-nav-test', {
    mode: 'graphql',
    endpoint: '',
    operation: '',
    variables: '{}',
    operationName: '',
    authorization: '',
    headers: [],
    timeoutSeconds: 30,
  })
  return (
    <>
      <input
        aria-label="协议会话草稿"
        value={state.draft.operation}
        onChange={(event) => state.patch({ operation: event.target.value })}
      />
      <output>{mode}</output>
      <button onClick={() => setParams({ mode: 'grpc' })}>切换gRPC模式</button>
      <button onClick={() => setParams({ mode: 'graphql', graphqlPage: '2' })}>
        返回GraphQL第二页
      </button>
    </>
  )
}
it('retains protocol query navigation drafts while still guarding module and project exits', async () => {
  const router = createMemoryRouter(
    [
      {
        element: (
          <DraftSessionProvider>
            <Link to={`${root}/reports`}>前往报告</Link>
            <Link to="/projects/00000000-0000-4000-8000-000000000102/protocols">切换项目</Link>
            <Outlet />
          </DraftSessionProvider>
        ),
        children: [
          { path: '/projects/:projectId/protocols', element: <ProtocolDraft /> },
          { path: '/projects/:projectId/reports', element: <div>报告列表</div> },
        ],
      },
    ],
    { initialEntries: [`${root}/protocols?mode=graphql`] },
  )
  render(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <App>
        <RouterProvider router={router} />
      </App>
    </ConfigProvider>,
  )
  fireEvent.change(screen.getByLabelText('协议会话草稿'), {
    target: { value: 'preserved request input' },
  })
  await userEvent.click(screen.getByRole('button', { name: '切换gRPC模式' }))
  await waitFor(() => expect(router.state.location.search).toBe('?mode=grpc'))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: '返回GraphQL第二页' }))
  await waitFor(() => expect(router.state.location.search).toContain('graphqlPage=2'))
  expect(screen.getByLabelText('协议会话草稿')).toHaveValue('preserved request input')
  await userEvent.click(screen.getByRole('link', { name: '前往报告' }))
  const dialog = await screen.findByRole('dialog')
  expect(router.state.location.pathname).toBe(`${root}/protocols`)
  await userEvent.click(within(dialog).getByRole('button', { name: '留在当前页保存' }))
  await userEvent.click(screen.getByRole('link', { name: '切换项目' }))
  expect(await screen.findByRole('dialog')).toBeInTheDocument()
  expect(router.state.location.pathname).toBe(`${root}/protocols`)
})
