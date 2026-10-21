import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { App as AntdApp, ConfigProvider } from 'antd'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { runTestCase } from '../features/test-assets/test-asset-service'
import type { TestCase, TestCaseVersion } from '../lib/api'
import { authenticateTestUser } from '../test/auth'
import { environment, project, user, workflow } from '../test/fixtures'
import { server } from '../test/server'
import { RunCaseDialog } from './TestAssetsPage'

const draftWorkflow = { ...workflow, name: '草稿流程', current_version: 9 }
const productionWorkflow = { ...workflow, id: 'production-workflow', name: '生产流程' }
const historicalWorkflow = { ...workflow, id: 'historical-workflow', name: '历史流程' }
const draftEnvironment = { ...environment, name: '测试环境' }
const productionEnvironment = { ...environment, id: 'production-environment', name: '生产环境' }
const historicalEnvironment = { ...environment, id: 'historical-environment', name: '历史环境' }
const item: TestCase = {
  id: 'case-run-review',
  project_id: project.id,
  folder_id: null,
  name: '运行确认用例',
  description: '',
  tags: [],
  is_template: false,
  current_version: 2,
  draft_fingerprint: 'f'.repeat(64),
  draft_definition: {
    workflow_id: draftWorkflow.id,
    workflow_version: 9,
    environment_id: draftEnvironment.id,
    runtime_variables: {},
    runtime_headers: {},
  },
  created_by_id: user.id,
  created_at: workflow.created_at,
  updated_at: workflow.updated_at,
}
const versions: TestCaseVersion[] = [
  {
    version: 2,
    workflow: historicalWorkflow,
    environment: historicalEnvironment,
    workflowVersion: 3,
  },
  {
    version: 1,
    workflow: productionWorkflow,
    environment: productionEnvironment,
    workflowVersion: 7,
  },
].map((entry) => ({
  id: `case-version-${entry.version}`,
  test_case_id: item.id,
  version: entry.version,
  definition: {
    ...item.draft_definition,
    workflow_id: entry.workflow.id,
    workflow_version: entry.workflowVersion,
    environment_id: entry.environment.id,
  },
  fingerprint: 'a'.repeat(64),
  change_note: '',
  created_by_id: user.id,
  created_at: workflow.created_at,
}))
const endpoint = `/api/v1/projects/${project.id}/test-cases/${item.id}`

beforeEach(() => {
  authenticateTestUser(user)
  server.use(http.get(`${endpoint}/versions`, () => HttpResponse.json(versions)))
})

describe('case run review', () => {
  it('confirms each selected published target independently from the draft before the explicit POST', async () => {
    const submitted: unknown[] = []
    installRunHandler(submitted)
    const dialog = renderReview()
    expect(submitted).toEqual([])
    expect(within(dialog).queryByText(/流程：草稿流程/)).not.toBeInTheDocument()
    fireEvent.click(within(dialog).getByLabelText('运行已发布用例版本'))
    expect(await within(dialog).findByText(/流程：历史流程/)).toHaveTextContent('历史环境')
    await chooseVersion(dialog, '用例 v1 · 流程 v7')
    expect(within(dialog).getByText(/流程：生产流程/)).toHaveTextContent('生产环境')
    expect(within(dialog).getByText(/流程：生产流程/)).toHaveTextContent('流程版本：v7')
    fireEvent.click(within(dialog).getByLabelText('发布已保存草稿并运行'))
    expect(within(dialog).getByText(/流程：草稿流程/)).toHaveTextContent('测试环境')
    fireEvent.click(within(dialog).getByLabelText('运行已发布用例版本'))
    expect(within(dialog).getByText(/流程：生产流程/)).toHaveTextContent('生产环境')
    expect(submitted).toEqual([])
    fireEvent.click(within(dialog).getByRole('button', { name: '运行已发布版本' }))
    await waitFor(() => expect(submitted).toEqual([{ source: 'published', version: 1 }]))
  })

  it('keeps the chosen source and version retryable after a temporary error without automatically resubmitting', async () => {
    const submitted: unknown[] = []
    installRunHandler(submitted, true)
    const dialog = renderReview(1)
    const submit = within(dialog).getByRole('button', { name: '运行已发布版本' })
    await waitFor(() => expect(submit).toBeEnabled())
    fireEvent.click(submit)
    await waitFor(() => expect(within(dialog).getByText(/运行服务暂不可用/)).toBeVisible())
    expect(within(dialog).getByLabelText('运行已发布用例版本')).toBeChecked()
    expect(
      within(dialog).getByRole('combobox', { name: '运行用例版本' }).closest('.ant-select'),
    ).toHaveTextContent('用例 v1 · 流程 v7')
    await act(async () => {})
    expect(submitted).toEqual([{ source: 'published', version: 1 }])
    expect(submit).toBeEnabled()
    fireEvent.click(submit)
    await waitFor(() =>
      expect(submitted).toEqual(Array(2).fill({ source: 'published', version: 1 })),
    )
  })

  it('shows frozen IDs when published resources are absent from the loaded directory', async () => {
    const dialog = renderReview(1, false)
    const target = await within(dialog).findByText(/流程：.*production-workflow/)
    expect(target).toHaveTextContent('production-environment')
    expect(target).toHaveTextContent('名称未加载')
    expect(target).not.toHaveTextContent('草稿流程')
    expect(target).not.toHaveTextContent('测试环境')
    expect(within(dialog).getByRole('button', { name: '运行已发布版本' })).toBeEnabled()
  })

  it('locks the submitted target and every dismissal path until the pending request finishes', async () => {
    const submitted: unknown[] = []
    const onClose = vi.fn()
    let release!: () => void
    server.use(
      http.post(`${endpoint}/runs`, async ({ request }) => {
        submitted.push(await request.json())
        await new Promise<void>((resolve) => {
          release = resolve
        })
        return HttpResponse.json({ execution_id: 'pending-execution' }, { status: 202 })
      }),
    )
    const dialog = renderReview(1, true, onClose)
    const submit = within(dialog).getByRole('button', { name: '运行已发布版本' })
    await waitFor(() => expect(submit).toBeEnabled())
    fireEvent.click(submit)
    await waitFor(() => expect(submitted).toHaveLength(1))
    try {
      expect(within(dialog).getByLabelText('发布已保存草稿并运行')).toBeDisabled()
      const version = within(dialog).getByRole('combobox', { name: '运行用例版本' })
      expect(version).toBeDisabled()
      const cancel = within(dialog).getByRole('button', { name: /取\s*消/ })
      expect(cancel).toBeDisabled()
      expect(within(dialog).queryByRole('button', { name: 'Close' })).not.toBeInTheDocument()
      fireEvent.click(within(dialog).getByLabelText('发布已保存草稿并运行'))
      fireEvent.mouseDown(version)
      fireEvent.click(cancel)
      fireEvent.click(dialog.closest('.ant-modal-wrap')!)
      fireEvent.keyDown(dialog, { key: 'Escape', code: 'Escape', keyCode: 27 })
      fireEvent.click(submit)
      expect(onClose).not.toHaveBeenCalled()
      expect(within(dialog).getByLabelText('运行已发布用例版本')).toBeChecked()
      expect(version.closest('.ant-select')).toHaveTextContent('用例 v1 · 流程 v7')
      expect(submitted).toEqual([{ source: 'published', version: 1 }])
    } finally {
      await act(async () => release())
    }
    const cancel = within(dialog).getByRole('button', { name: /取\s*消/ })
    await waitFor(() => expect(cancel).toBeEnabled())
    fireEvent.click(cancel)
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('does not display a draft target or allow submitting while the published definitions are loading', async () => {
    let release!: () => void
    server.use(
      http.get(`${endpoint}/versions`, async () => {
        await new Promise<void>((resolve) => {
          release = resolve
        })
        return HttpResponse.json(versions)
      }),
    )
    const dialog = renderReview(1)
    await waitFor(() =>
      expect(within(dialog).getByText('正在读取已发布版本的运行目标')).toBeVisible(),
    )
    expect(within(dialog).queryByText(/流程：草稿流程/)).not.toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: '运行已发布版本' })).toBeDisabled()
    await waitFor(() => expect(release).toBeDefined())
    await act(async () => release())
    expect(await within(dialog).findByText(/流程：生产流程/)).toHaveTextContent('生产环境')
  })

  it('reports a failed version read without replacing its target with the draft', async () => {
    server.use(
      http.get(`${endpoint}/versions`, () =>
        HttpResponse.json(
          {
            error: {
              code: 'UNAVAILABLE',
              message: '发布版本暂不可用',
              trace_id: 'case-version-trace',
            },
          },
          { status: 503 },
        ),
      ),
    )
    const dialog = renderReview(1)
    await waitFor(() => expect(within(dialog).getByText(/发布版本暂不可用/)).toBeVisible())
    expect(within(dialog).queryByText(/流程：草稿流程/)).not.toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: '运行已发布版本' })).toBeDisabled()
  })

  it('keeps the saved draft fingerprint contract when explicitly publishing and running the draft', async () => {
    const submitted: unknown[] = []
    installRunHandler(submitted)
    const dialog = renderReview()
    fireEvent.click(within(dialog).getByLabelText('发布已保存草稿并运行'))
    const submit = within(dialog).getByRole('button', { name: '发布并运行' })
    await waitFor(() => expect(submit).toBeEnabled())
    expect(within(dialog).getByText(/流程：草稿流程/)).toHaveTextContent('测试环境')
    expect(submitted).toEqual([])
    fireEvent.click(submit)
    await waitFor(() =>
      expect(submitted).toEqual([
        {
          source: 'draft',
          publish_draft: true,
          expected_draft_fingerprint: item.draft_fingerprint,
        },
      ]),
    )
  })
})

function renderReview(
  initialVersion?: number,
  includePublishedResources = true,
  onClose = () => {},
) {
  render(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <AntdApp>
        <RunCaseDialog
          item={item}
          initialVersion={initialVersion}
          projectId={project.id}
          workflows={
            includePublishedResources
              ? [draftWorkflow, productionWorkflow, historicalWorkflow]
              : [draftWorkflow]
          }
          environments={
            includePublishedResources
              ? [draftEnvironment, productionEnvironment, historicalEnvironment]
              : [draftEnvironment]
          }
          submitting={false}
          onClose={onClose}
          onRun={async (input) => {
            await runTestCase(project.id, item.id, input)
          }}
        />
      </AntdApp>
    </ConfigProvider>,
  )
  return screen.getByRole('dialog', { name: `运行测试用例：${item.name}` })
}

function installRunHandler(submitted: unknown[], failFirst = false) {
  server.use(
    http.post(`${endpoint}/runs`, async ({ request }) => {
      submitted.push(await request.json())
      if (failFirst && submitted.length === 1)
        return HttpResponse.json(
          {
            error: {
              code: 'UNAVAILABLE',
              message: '运行服务暂不可用',
              trace_id: 'run-review-trace',
            },
          },
          { status: 503 },
        )
      return HttpResponse.json({ execution_id: 'confirmed-execution' }, { status: 202 })
    }),
  )
}

async function chooseVersion(dialog: HTMLElement, label: string) {
  fireEvent.mouseDown(within(dialog).getByRole('combobox', { name: '运行用例版本' }))
  fireEvent.click(await screen.findByText(label, { selector: '.ant-select-item-option-content' }))
}
