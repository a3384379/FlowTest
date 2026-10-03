import { useDraftSession } from '../drafts/draft-session'
import { useState } from 'react'
import { nodeEditorScope } from '../../flow/editor/editor-identity'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, fireEvent, waitFor, act, within } from '@testing-library/react'
import { App as AntdApp, ConfigProvider } from 'antd'
import { createMemoryRouter, RouterProvider, useParams } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { DraftSessionProvider } from '../drafts/DraftSessionProvider'
import { useWorkflows } from './use-workflows'
import { useAuthStore } from '../auth/auth-store'
import { authenticateTestUser } from '../../test/auth'
import {
  environment,
  workflow,
  workflowVersion,
  workflowRunningExecution,
  user as actor,
} from '../../test/fixtures'

vi.mock('../projects/use-project-context', () => ({
  useProjectContext: () => ({
    projects: { data: { items: [] } },
    projectId: useParams().projectId,
    selectProject: vi.fn(),
  }),
}))
vi.mock('./workflow-service', () => ({
  listWorkflows: vi.fn(async () => ({
    items: [workflow, secondWorkflow],
    total: 2,
    page: 1,
    page_size: 100,
  })),
  getWorkflow: vi.fn(async (_project: string, id: string) =>
    id === workflow.id ? workflow : secondWorkflow,
  ),
  listEnvironments: async () => [environment],
  listApis: async () => ({ items: [] }),
  listArtifacts: async () => ({ items: [] }),
  listWorkflowExecutions: async () => ({ items: [] }),
  updateWorkflowDraft: vi.fn(),
  publishWorkflow: vi.fn(),
  executeWorkflow: vi.fn(),
}))
vi.mock('../data-sources/data-source-service', () => ({ listCredentials: async () => [] }))
vi.mock('../protocols/protocol-service', () => ({
  listGraphQLSchemas: async () => ({ items: [] }),
  listGrpcDescriptors: async () => ({ items: [] }),
  listEventSources: async () => ({ items: [] }),
}))
import {
  updateWorkflowDraft,
  publishWorkflow,
  executeWorkflow,
  listWorkflows,
  getWorkflow,
} from './workflow-service'
import { readWorkflowDraft, workflowDraftKey } from './workflow-draft-store'
import type { WorkflowDefinition } from '../../lib/api'

const secondWorkflow = {
  ...workflow,
  id: '00000000-0000-4000-8000-000000000099',
  draft_definition: {
    ...workflow.draft_definition,
    nodes: workflow.draft_definition.nodes.map((node) => ({ ...node, name: '另一个流程' })),
  },
}

function Editor() {
  const state = useWorkflows(workflow.id)
  const session = useDraftSession()
  const [closeResult, setCloseResult] = useState('等待关闭')
  return (
    <>
      <output data-testid="published-version">
        {state.selectedWorkflow?.current_version ?? '未发布'}
      </output>
      <span>{closeResult}</span>
      <button onClick={() => state.setDraftDefinition({ ...state.draftDefinition, edges: [] })}>
        构造未完成图
      </button>
      <button
        onClick={() =>
          void state.saveWorkflowDraft(workflow.id).then(
            () => setCloseResult('允许关闭'),
            () => setCloseResult('保持打开'),
          )
        }
      >
        保存后关闭
      </button>
      <button
        onClick={() =>
          void state.saveWorkflowDraft(state.workflowId ?? '').then(
            () => setCloseResult('允许关闭'),
            () => setCloseResult('保持打开'),
          )
        }
      >
        保存当前流程后关闭
      </button>
      <button
        onClick={() => {
          const node = state.draftDefinition.nodes[0]
          session.updateNodeEditor(`${nodeEditorScope(actor.id, 'one', workflow.id)}${node.id}`, {
            nodeId: node.id,
            baseNode: node,
            draftNode: { ...node, name: '未应用' },
            generation: session.nextGeneration(),
            dirty: true,
            rawFields: {},
            activeTab: 'params',
            requestDraft: null,
            requestDirty: false,
          })
        }}
      >
        暂存配置
      </button>
      <button onClick={() => void state.publish()}>发布</button>
      <button onClick={() => void state.execute()}>运行</button>
      <input
        aria-label="草稿名称"
        value={state.draftDefinition.nodes[0]?.name ?? ''}
        onChange={(event) =>
          state.setDraftDefinition({
            ...state.draftDefinition,
            nodes: state.draftDefinition.nodes.map((node, index) =>
              index === 0 ? { ...node, name: event.target.value } : node,
            ),
          })
        }
      />
      <button
        disabled={!state.canEdit}
        onClick={() => void state.saveDraft().catch(() => undefined)}
      >
        保存
      </button>
      <button onClick={() => state.discardWorkflowDraft(workflow.id)}>丢弃</button>
      <button onClick={() => state.setWorkflowSelection(secondWorkflow.id)}>切换流程</button>
    </>
  )
}
function setup(client = new QueryClient({ defaultOptions: { queries: { retry: false } } })) {
  const router = createMemoryRouter(
    [
      {
        path: '/:projectId/workflows',
        element: (
          <DraftSessionProvider>
            <Editor />
          </DraftSessionProvider>
        ),
      },
    ],
    { initialEntries: ['/one/workflows'] },
  )
  render(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <AntdApp>
        <QueryClientProvider client={client}>
          <RouterProvider router={router} />
        </QueryClientProvider>
      </AntdApp>
    </ConfigProvider>,
  )
  return workflowDraftKey(actor.id, 'one', workflow.id)
}
beforeEach(() => {
  authenticateTestUser(actor)
  vi.mocked(updateWorkflowDraft).mockReset()
  vi.mocked(publishWorkflow).mockReset()
  vi.mocked(listWorkflows)
    .mockReset()
    .mockResolvedValue({ items: [workflow, secondWorkflow], total: 2, page: 1, page_size: 100 })
  vi.mocked(getWorkflow)
    .mockReset()
    .mockImplementation(async (_project, id) => (id === workflow.id ? workflow : secondWorkflow))
  vi.mocked(executeWorkflow).mockReset()
})

it('saves an off-page workflow draft by its exact object before permitting a close', async () => {
  vi.mocked(listWorkflows).mockResolvedValue({
    items: [workflow],
    total: 126,
    page: 1,
    page_size: 100,
  })
  vi.mocked(updateWorkflowDraft).mockImplementation(async (_project, target, definition) => ({
    ...target,
    draft_revision: 2,
    draft_definition: definition,
  }))
  setup()
  await waitFor(() => expect(screen.getByRole('button', { name: '保存' })).toBeEnabled())
  fireEvent.click(screen.getByRole('button', { name: '切换流程' }))
  await waitFor(() => expect(screen.getByLabelText('草稿名称')).toHaveValue('另一个流程'))
  fireEvent.change(screen.getByLabelText('草稿名称'), { target: { value: '页外流程的新稿' } })
  fireEvent.click(screen.getByRole('button', { name: '保存当前流程后关闭' }))
  expect(await screen.findByText('允许关闭')).toBeVisible()
  expect(getWorkflow).toHaveBeenCalledWith('one', secondWorkflow.id)
  expect(updateWorkflowDraft).toHaveBeenCalledWith(
    'one',
    expect.objectContaining({ id: secondWorkflow.id }),
    expect.objectContaining({
      nodes: expect.arrayContaining([expect.objectContaining({ name: '页外流程的新稿' })]),
    }),
    1,
  )
})

it('keeps the tab open when another edit appears while saving before close', async () => {
  const complete = pendingSave()
  setup()
  await waitFor(() => expect(screen.getByRole('button', { name: '保存' })).toBeEnabled())
  fireEvent.change(screen.getByLabelText('草稿名称'), { target: { value: '关闭前待保存' } })
  fireEvent.click(screen.getByRole('button', { name: '保存后关闭' }))
  await waitFor(() => expect(updateWorkflowDraft).toHaveBeenCalledOnce())
  const sent = vi.mocked(updateWorkflowDraft).mock.calls[0][2]
  fireEvent.change(screen.getByLabelText('草稿名称'), { target: { value: '保存中的更新' } })
  await act(async () => complete({ ...workflow, draft_revision: 2, draft_definition: sent }))
  expect(await screen.findByText('保持打开')).toBeVisible()
  expect(screen.getByLabelText('草稿名称')).toHaveValue('保存中的更新')
})
afterEach(() => {
  localStorage.clear()
  useAuthStore.setState({ user: null })
})
function pendingSave() {
  let resolve!: (value: typeof workflow) => void
  const promise = new Promise<typeof workflow>((done) => {
    resolve = done
  })
  vi.mocked(updateWorkflowDraft).mockReturnValue(promise)
  return resolve
}
async function editAndSave() {
  await waitFor(() => expect(screen.getByRole('button', { name: '保存' })).toBeEnabled())
  await waitFor(() => expect(screen.getByLabelText('草稿名称')).toHaveValue('开始'))
  fireEvent.change(screen.getByLabelText('草稿名称'), { target: { value: '发起保存时的草稿' } })
  fireEvent.click(screen.getByRole('button', { name: '保存' }))
  await waitFor(() => expect(updateWorkflowDraft).toHaveBeenCalledTimes(1))
}
it('LIFE02 rebases edits made during save without replacing their content', async () => {
  const complete = pendingSave()
  const key = setup()
  await editAndSave()
  const sent = vi.mocked(updateWorkflowDraft).mock.calls[0][2] as WorkflowDefinition
  fireEvent.change(screen.getByLabelText('草稿名称'), { target: { value: '保存期间的新修改' } })
  await act(async () => complete({ ...workflow, draft_revision: 2, draft_definition: sent }))
  await waitFor(() => expect(readWorkflowDraft(key)?.baseRevision).toBe(2))
  expect(readWorkflowDraft(key)?.content.nodes[0].name).toBe('保存期间的新修改')
  expect(screen.getByLabelText('草稿名称')).toHaveValue('保存期间的新修改')
})
it('LIFE04 ignores a save completion after the draft was discarded', async () => {
  const complete = pendingSave()
  const key = setup()
  await editAndSave()
  fireEvent.click(screen.getByRole('button', { name: '丢弃' }))
  await act(async () => complete({ ...workflow, draft_revision: 2 }))
  expect(readWorkflowDraft(key)).toBeNull()
  expect(screen.getByLabelText('草稿名称')).toHaveValue('开始')
})
it('preserves a new draft created while the saved object cache is synchronizing', async () => {
  const complete = pendingSave()
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const key = setup(client)
  await editAndSave()
  let release!: () => void
  const synchronization = new Promise<void>((resolve) => {
    release = resolve
  })
  const cancellation = vi
    .spyOn(client, 'cancelQueries')
    .mockImplementationOnce(() => synchronization)
  await act(async () => complete({ ...workflow, draft_revision: 2 }))
  await waitFor(() => expect(cancellation).toHaveBeenCalled())
  fireEvent.click(screen.getByRole('button', { name: '丢弃' }))
  fireEvent.change(screen.getByLabelText('草稿名称'), { target: { value: '丢弃后创建的新稿' } })
  await act(async () => release())
  expect(readWorkflowDraft(key)?.content.nodes[0].name).toBe('丢弃后创建的新稿')
  expect(screen.getByLabelText('草稿名称')).toHaveValue('丢弃后创建的新稿')
  cancellation.mockRestore()
})
it('LIFE05 preserves the local draft and its base revision on conflict', async () => {
  vi.mocked(updateWorkflowDraft).mockRejectedValue({
    response: {
      status: 409,
      data: {
        error: {
          code: 'WORKFLOW_REVISION_CONFLICT',
          message: '草稿版本冲突',
          trace_id: 'test-trace',
        },
      },
    },
  })
  const key = setup()
  await editAndSave()
  expect(readWorkflowDraft(key)?.baseRevision).toBe(1)
  expect(readWorkflowDraft(key)?.content.nodes[0].name).toBe('发起保存时的草稿')
  expect(screen.getByLabelText('草稿名称')).toHaveValue('发起保存时的草稿')
})

it('LIFE03 keeps the newly selected workflow unchanged when an older save completes', async () => {
  const complete = pendingSave()
  const key = setup()
  await editAndSave()
  fireEvent.click(screen.getByRole('button', { name: '切换流程' }))
  await waitFor(() => expect(screen.getByLabelText('草稿名称')).toHaveValue('另一个流程'))
  await act(async () => complete({ ...workflow, draft_revision: 2 }))
  expect(readWorkflowDraft(key)).toBeNull()
  expect(screen.getByLabelText('草稿名称')).toHaveValue('另一个流程')
})

it('LIFE12 blocks save, publish, and execute while a node edit is unapplied', async () => {
  setup()
  await waitFor(() => expect(screen.getByRole('button', { name: '保存' })).toBeEnabled())
  await waitFor(() => expect(screen.getByLabelText('草稿名称')).toHaveValue('开始'))
  fireEvent.click(screen.getByRole('button', { name: '暂存配置' }))
  fireEvent.click(screen.getByRole('button', { name: '保存' }))
  fireEvent.click(screen.getByRole('button', { name: '发布' }))
  fireEvent.click(screen.getByRole('button', { name: '运行' }))
  expect(updateWorkflowDraft).not.toHaveBeenCalled()
  expect(publishWorkflow).not.toHaveBeenCalled()
  expect(executeWorkflow).not.toHaveBeenCalled()
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})

it('cancels a publication confirmation after its workflow changes', async () => {
  setup()
  await waitFor(() => expect(screen.getByRole('button', { name: '保存' })).toBeEnabled())
  fireEvent.click(screen.getByRole('button', { name: '发布' }))
  const dialog = await screen.findByRole('dialog', { hidden: true })
  fireEvent.click(screen.getByRole('button', { name: '切换流程' }))
  await waitFor(() => expect(screen.getByLabelText('草稿名称')).toHaveValue('另一个流程'))
  await act(async () => {
    fireEvent.click(within(dialog).getByRole('button', { name: '发布服务器草稿', hidden: true }))
  })
  expect(publishWorkflow).not.toHaveBeenCalled()
})

it.each(['暂存配置', '构造未完成图'])(
  'LIFE06 rejects save-before-close when blocked by %s',
  async (action) => {
    setup()
    await waitFor(() => expect(screen.getByRole('button', { name: '保存' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: action }))
    fireEvent.click(screen.getByRole('button', { name: '保存后关闭' }))
    await expect(screen.findByText('保持打开')).resolves.toBeVisible()
    expect(updateWorkflowDraft).not.toHaveBeenCalled()
  },
)

async function openOffPageWorkflow() {
  await waitFor(() => expect(screen.getByRole('button', { name: '保存' })).toBeEnabled())
  fireEvent.click(screen.getByRole('button', { name: '切换流程' }))
  await waitFor(() => expect(screen.getByLabelText('草稿名称')).toHaveValue('另一个流程'))
}
function offPageCatalog() {
  vi.mocked(listWorkflows).mockResolvedValue({
    items: [workflow],
    total: 126,
    page: 1,
    page_size: 100,
  })
}

it('keeps an off-page saved graph and uses its returned revision for a second save', async () => {
  offPageCatalog()
  vi.mocked(updateWorkflowDraft).mockImplementation(
    async (_project, target, definition, revision) => ({
      ...target,
      draft_revision: revision! + 1,
      draft_definition: definition,
    }),
  )
  setup()
  await openOffPageWorkflow()
  for (const [name, revision] of [
    ['页外保存第一稿', 1],
    ['页外保存第二稿', 2],
  ] as const) {
    fireEvent.change(screen.getByLabelText('草稿名称'), { target: { value: name } })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))
    await waitFor(() => expect(updateWorkflowDraft).toHaveBeenCalledTimes(revision))
    await waitFor(() =>
      expect(readWorkflowDraft(workflowDraftKey(actor.id, 'one', secondWorkflow.id))).toBeNull(),
    )
    expect(screen.getByLabelText('草稿名称')).toHaveValue(name)
    expect(vi.mocked(updateWorkflowDraft).mock.calls[revision - 1][3]).toBe(revision)
  }
})

it.each([null, 1])(
  'runs an off-page workflow with the newly published version after v%s',
  async (currentVersion) => {
    offPageCatalog()
    let serverWorkflow = { ...secondWorkflow, current_version: currentVersion }
    vi.mocked(getWorkflow).mockImplementation(async () => serverWorkflow)
    const nextVersion = (currentVersion ?? 0) + 1
    vi.mocked(publishWorkflow).mockImplementation(async () => {
      serverWorkflow = { ...serverWorkflow, current_version: nextVersion }
      return { ...workflowVersion, workflow_id: secondWorkflow.id, version: nextVersion }
    })
    vi.mocked(executeWorkflow).mockResolvedValue({
      ...workflowRunningExecution,
      project_id: 'one',
      workflow_id: secondWorkflow.id,
    })
    setup()
    await openOffPageWorkflow()
    fireEvent.click(screen.getByRole('button', { name: '发布' }))
    const dialog = await screen.findByRole('dialog', { hidden: true })
    fireEvent.click(within(dialog).getByRole('button', { name: '发布服务器草稿', hidden: true }))
    await waitFor(() =>
      expect(screen.getByTestId('published-version')).toHaveTextContent(String(nextVersion)),
    )
    fireEvent.click(screen.getByRole('button', { name: '运行' }))
    await waitFor(() =>
      expect(executeWorkflow).toHaveBeenCalledWith(
        'one',
        secondWorkflow.id,
        expect.any(String),
        nextVersion,
      ),
    )
  },
)

it('does not let an old in-flight detail response overwrite an off-page save', async () => {
  offPageCatalog()
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  setup(client)
  await openOffPageWorkflow()
  let complete!: (value: typeof secondWorkflow) => void
  const oldDetail = new Promise<typeof secondWorkflow>((resolve) => {
    complete = resolve
  })
  vi.mocked(getWorkflow).mockReturnValueOnce(oldDetail)
  let refresh!: Promise<void>
  act(() => {
    refresh = client.refetchQueries({ queryKey: ['workflow', 'one', secondWorkflow.id] })
  })
  vi.mocked(updateWorkflowDraft).mockImplementation(async (_project, target, definition) => ({
    ...target,
    draft_revision: 2,
    draft_definition: definition,
  }))
  fireEvent.change(screen.getByLabelText('草稿名称'), { target: { value: '已保存的新图' } })
  fireEvent.click(screen.getByRole('button', { name: '保存' }))
  await waitFor(() =>
    expect(readWorkflowDraft(workflowDraftKey(actor.id, 'one', secondWorkflow.id))).toBeNull(),
  )
  await act(async () => {
    complete(secondWorkflow)
    await refresh
  })
  expect(screen.getByLabelText('草稿名称')).toHaveValue('已保存的新图')
  expect(client.getQueryData(['workflow', 'one', secondWorkflow.id])).toMatchObject({
    draft_revision: 2,
  })
})
