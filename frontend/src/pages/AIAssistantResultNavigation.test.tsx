import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App, ConfigProvider } from 'antd'
import { http, HttpResponse } from 'msw'
import { Link, useLocation, useSearchParams } from 'react-router-dom'
import { afterEach, expect, it } from 'vitest'
import { useAuthStore } from '../features/auth/auth-store'
import { DraftSessionProvider } from '../features/drafts/DraftSessionProvider'
import { useWorkflows } from '../features/workflows/use-workflows'
import { authenticateTestUser } from '../test/auth'
import { environment, project, user, workflow } from '../test/fixtures'
import ProjectTestProvider from '../test/ProjectTestProvider'
import { server } from '../test/server'
import type { TestCase } from '../lib/api'
import { listTestCases } from '../features/test-assets/test-asset-service'
import TestAssetsPage from './TestAssetsPage'
import AIAssistantPage from './AIAssistantPage'

const job = {
  id: 'synthetic-ai-job',
  project_id: project.id,
  job_type: 'workflow_draft',
  status: 'completed',
  input_sha256: 'a'.repeat(64),
  model_name: 'synthetic',
  created_at: workflow.created_at,
  updated_at: workflow.updated_at,
  completed_at: workflow.updated_at,
}
const foreignProject = { ...project, id: 'other-project', name: '另一个项目' }
const foreignWorkflow = { ...workflow, id: 'other-workflow', project_id: foreignProject.id }
const created = { ...workflow, id: 'synthetic-new-workflow', name: 'AI 新建的准确草稿' }
const suggestion = {
  id: 'synthetic-suggestion',
  job_id: job.id,
  suggestion_type: 'workflow',
  title: '合成工作流建议',
  content: { name: created.name, definition: created.draft_definition },
  review_status: 'pending',
  review_note: '',
  reviewed_by_id: null,
  reviewed_at: null,
  accepted_resource_type: null,
  accepted_resource_id: null,
}

afterEach(() => {
  localStorage.clear()
  useAuthStore.setState({ user: null })
})

it('opens the AI-created workflow using a production-fresh complete catalog in the real workflow consumer', async () => {
  authenticateTestUser(user)
  let foreignReads = 0
  let accepted = false
  let writes = 0
  let catalogReads = 0
  let catalogReadAt = 0
  const exactReads: string[] = []
  installWorkflowReads()
  server.use(
    http.get('/api/v1/projects', () =>
      HttpResponse.json({ items: [project, foreignProject], total: 2, page: 1, page_size: 100 }),
    ),
    http.get(`/api/v1/projects/${foreignProject.id}`, () => HttpResponse.json(foreignProject)),
    http.get(`/api/v1/projects/${foreignProject.id}/workflows`, () => {
      foreignReads += 1
      return HttpResponse.json({ items: [foreignWorkflow], total: 1, page: 1, page_size: 100 })
    }),
    http.get('/api/v1/ai/status', () =>
      HttpResponse.json({ enabled: true, model: 'synthetic', sample_sharing_enabled: false }),
    ),
    http.get('/api/v1/ai/jobs', () =>
      HttpResponse.json({ items: [job], total: 1, page: 1, page_size: 20 }),
    ),
    http.get(`/api/v1/ai/jobs/${job.id}`, () => HttpResponse.json(job)),
    http.get(`/api/v1/ai/jobs/${job.id}/suggestions`, () => HttpResponse.json([suggestion])),
    http.post(`/api/v1/ai/suggestions/${suggestion.id}/accept`, () => {
      writes += 1
      accepted = true
      return HttpResponse.json({
        ...suggestion,
        review_status: 'accepted',
        accepted_resource_type: 'workflow',
        accepted_resource_id: created.id,
      })
    }),
    http.get(`/api/v1/projects/${project.id}/workflows`, () => {
      catalogReads += 1
      catalogReadAt = Date.now()
      const items = accepted ? [created, workflow] : [workflow]
      return HttpResponse.json({ items, total: items.length, page: 1, page_size: 100 })
    }),
    http.get(`/api/v1/projects/${project.id}/workflows/:id`, ({ params }) => {
      exactReads.push(String(params.id))
      return HttpResponse.json(params.id === created.id ? created : workflow)
    }),
  )
  // Same 15s staleTime as main.tsx:19; no Infinity, fake clock or selection mocks.
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 15_000 }, mutations: { retry: false } },
  })
  client.setQueryData(['workflows', foreignProject.id, 'catalog', '', 1], {
    items: [foreignWorkflow],
    total: 1,
    page: 1,
    page_size: 100,
  })
  render(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <App>
        <QueryClientProvider client={client}>
          <ProjectTestProvider
            section="workflows"
            initialEntry={`/projects/${project.id}/workflows?focus=${workflow.id}`}
          >
            <DraftSessionProvider>
              <ResultRoute />
            </DraftSessionProvider>
          </ProjectTestProvider>
        </QueryClientProvider>
      </App>
    </ConfigProvider>,
  )
  await waitFor(() =>
    expect(screen.getByLabelText('实际所选工作流')).toHaveTextContent(workflow.id),
  )
  const firstCatalogAt = catalogReadAt
  expect(catalogReads).toBe(1)
  const browser = userEvent.setup()
  await browser.click(screen.getByRole('link', { name: '前往 AI 助手' }))
  const title = await screen.findByText(suggestion.title)
  await browser.click(within(title.closest('tr')!).getByRole('button', { name: /接受/ }))
  const dialogTitle = await screen.findByText('接受建议', { selector: '.ant-modal-title' })
  await browser.click(
    within(dialogTitle.closest('.ant-modal') as HTMLElement).getByRole('button', {
      name: '确认接受',
    }),
  )
  await browser.click(await screen.findByRole('link', { name: '打开流程草稿' }))
  await screen.findByRole('region', { name: '真实工作流消费者' })
  expect(writes).toBe(1)
  await waitFor(() => expect(screen.getByLabelText('实际所选工作流')).toHaveTextContent(created.id))
  expect(Date.now() - firstCatalogAt).toBeLessThan(15_000)
  expect(screen.getByLabelText('实际工作流名称')).toHaveTextContent(created.name)
  expect(catalogReads).toBe(2)
  await browser.click(screen.getByRole('link', { name: '查看另一项目流程' }))
  await waitFor(() =>
    expect(screen.getByLabelText('实际所选工作流')).toHaveTextContent(foreignWorkflow.id),
  )
  expect(foreignReads).toBe(0)
})

it('refreshes the case directory and opens the actual accepted case draft in its workspace', async () => {
  authenticateTestUser(user)
  const createdCase: TestCase = {
    id: 'accepted-case',
    project_id: project.id,
    folder_id: null,
    name: '接受后新用例',
    description: '人工审核的草稿',
    tags: [],
    is_template: false,
    current_version: null,
    created_by_id: user.id,
    created_at: workflow.created_at,
    updated_at: workflow.updated_at,
    draft_definition: {
      workflow_id: workflow.id,
      workflow_version: null,
      environment_id: environment.id,
      runtime_variables: {},
      runtime_headers: {},
    },
  }
  const caseJob = { ...job, job_type: 'schema_cases' }
  const caseSuggestion = {
    ...suggestion,
    suggestion_type: 'test_case',
    content: { name: createdCase.name, definition: createdCase.draft_definition },
  }
  let accepted = false
  let writes = 0
  let caseReads = 0
  let assetReads = 0
  installWorkflowReads()
  server.use(
    http.get('/api/v1/projects', () =>
      HttpResponse.json({ items: [project], total: 1, page: 1, page_size: 100 }),
    ),
    http.get('/api/v1/ai/status', () =>
      HttpResponse.json({ enabled: true, model: 'synthetic', sample_sharing_enabled: false }),
    ),
    http.get('/api/v1/ai/jobs', () =>
      HttpResponse.json({ items: [caseJob], total: 1, page: 1, page_size: 20 }),
    ),
    http.get(`/api/v1/ai/jobs/${job.id}`, () => HttpResponse.json(caseJob)),
    http.get(`/api/v1/ai/jobs/${job.id}/suggestions`, () => HttpResponse.json([caseSuggestion])),
    http.post(`/api/v1/ai/suggestions/${suggestion.id}/accept`, () => {
      accepted = true
      writes += 1
      return HttpResponse.json({
        ...caseSuggestion,
        review_status: 'accepted',
        accepted_resource_type: 'test_case',
        accepted_resource_id: createdCase.id,
      })
    }),
    http.get(`/api/v1/projects/${project.id}/workflows`, () =>
      HttpResponse.json({ items: [workflow], total: 1, page: 1, page_size: 100 }),
    ),
    http.get(`/api/v1/projects/${project.id}/environments`, () => HttpResponse.json([environment])),
    http.get(`/api/v1/projects/${project.id}/test-cases`, () => {
      caseReads += 1
      return HttpResponse.json({
        items: accepted ? [createdCase] : [],
        total: accepted ? 1 : 0,
        page: 1,
        page_size: 20,
      })
    }),
    http.get(`/api/v1/projects/${project.id}/test-cases/${createdCase.id}`, () => {
      assetReads += 1
      return HttpResponse.json(createdCase)
    }),
    http.get(`/api/v1/projects/${project.id}/test-cases/${createdCase.id}/versions`, () =>
      HttpResponse.json([]),
    ),
    http.get(`/api/v1/projects/${project.id}/test-cases/runs/latest`, () => HttpResponse.json([])),
    http.get(`/api/v1/projects/${project.id}/test-suites/runs/latest`, () => HttpResponse.json([])),
    http.get(`/api/v1/projects/${project.id}/test-suites`, () =>
      HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 }),
    ),
    http.get(`/api/v1/projects/${project.id}/folders`, () => HttpResponse.json([])),
    http.get(`/api/v1/projects/${project.id}/test-assets/directory-counts`, () =>
      HttpResponse.json({
        case_total: accepted ? 1 : 0,
        suite_total: 0,
        published_case_total: 0,
        unfiled_cases: accepted ? 1 : 0,
        unfiled_suites: 0,
        folders: [],
      }),
    ),
  )
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 15_000 } },
  })
  const scope = { order: 'updated_desc' } as const
  await client.fetchQuery({
    queryKey: ['test-cases', project.id, '', '', 'all', 1, scope],
    queryFn: () => listTestCases(project.id, '', '', 1, 20, 'all', scope),
  })
  render(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <App>
        <QueryClientProvider client={client}>
          <ProjectTestProvider
            section="ai"
            initialEntry={`/projects/${project.id}/ai?job=${job.id}`}
          >
            <DraftSessionProvider>
              <ResultRoute />
            </DraftSessionProvider>
          </ProjectTestProvider>
        </QueryClientProvider>
      </App>
    </ConfigProvider>,
  )
  const browser = userEvent.setup()
  const title = await screen.findByText(suggestion.title)
  await browser.click(within(title.closest('tr')!).getByRole('button', { name: /接受/ }))
  const dialogTitle = await screen.findByText('接受建议', { selector: '.ant-modal-title' })
  await browser.click(
    within(dialogTitle.closest('.ant-modal') as HTMLElement).getByRole('button', {
      name: '确认接受',
    }),
  )
  await browser.click(await screen.findByRole('link', { name: '打开用例草稿' }))
  const drawer = await screen.findByRole('dialog', { name: '测试资产详情' })
  expect(await within(drawer).findByRole('heading', { name: createdCase.name })).toBeVisible()
  expect(within(drawer).getByText('人工审核的草稿')).toBeVisible()
  await waitFor(() =>
    expect(screen.getAllByText(createdCase.name).some((element) => element.closest('tr'))).toBe(
      true,
    ),
  )
  expect(caseReads).toBe(2)
  expect(assetReads).toBe(1)
  expect(writes).toBe(1)
})

function ResultRoute() {
  const location = useLocation()
  return location.pathname.endsWith('/workflows') ? (
    <WorkflowReader />
  ) : location.pathname.endsWith('/assets') ? (
    <TestAssetsPage />
  ) : (
    <AIAssistantPage />
  )
}
function WorkflowReader() {
  const [params] = useSearchParams()
  const state = useWorkflows(params.get('focus') ?? undefined)
  return (
    <section aria-label="真实工作流消费者">
      <output aria-label="实际所选工作流">{state.selectedWorkflow?.id}</output>
      <output aria-label="实际工作流名称">{state.selectedWorkflow?.name}</output>
      <Link to={`/projects/${project.id}/ai?job=${job.id}`}>前往 AI 助手</Link>
      <Link to={`/projects/${foreignProject.id}/workflows?focus=${foreignWorkflow.id}`}>
        查看另一项目流程
      </Link>
    </section>
  )
}
function installWorkflowReads() {
  for (const path of [
    '/api/v1/projects/:projectId/apis',
    '/api/v1/projects/:projectId/files',
    '/api/v1/projects/:projectId/workflow-executions',
    '/api/v1/graphql/schemas',
    '/api/v1/grpc/descriptors',
    '/api/v1/event-sources',
  ])
    server.use(
      http.get(path, () => HttpResponse.json({ items: [], total: 0, page: 1, page_size: 100 })),
    )
  server.use(
    http.get('/api/v1/projects/:projectId/environments', () => HttpResponse.json([])),
    http.get('/api/v1/credentials', () => HttpResponse.json([])),
  )
}
