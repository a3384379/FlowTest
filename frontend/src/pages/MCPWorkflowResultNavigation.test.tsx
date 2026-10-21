import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App, ConfigProvider } from 'antd'
import { http, HttpResponse } from 'msw'
import { Link, useLocation, useSearchParams } from 'react-router-dom'
import { afterEach, expect, it } from 'vitest'

import { useAuthStore } from '../features/auth/auth-store'
import { DraftSessionProvider } from '../features/drafts/DraftSessionProvider'
import type { MCPChangeSet } from '../features/mcp/mcp-change-set-service'
import { useProjectContext } from '../features/projects/use-project-context'
import { useWorkflows } from '../features/workflows/use-workflows'
import type { WorkflowDefinition } from '../lib/api'
import { authenticateTestUser } from '../test/auth'
import { project, user, workflow } from '../test/fixtures'
import ProjectTestProvider from '../test/ProjectTestProvider'
import { server } from '../test/server'
import MCPChangeSetsPage from './MCPChangeSetsPage'

const foreignProject = { ...project, id: 'other-project', name: '另一个项目' }
const foreignWorkflow = {
  ...workflow,
  id: 'other-workflow',
  project_id: foreignProject.id,
  name: '另一个项目的草稿',
  draft_revision: 17,
}
const changeSetId = 'workflow-change-set'
const itemId = 'workflow-change-item'
const controlNode: WorkflowDefinition['nodes'][number] = {
  id: 'group',
  type: 'capability',
  name: '物化后的节点',
  position: { x: 150, y: 0 },
  config: {},
  capability_id: 'flow.control.group',
  capability_version: '1.0.0',
  configuration: { body: { kind: 'inline', region_id: 'body' } },
  bindings: [],
}
const controlRegions: NonNullable<WorkflowDefinition['regions']> = [
  {
    id: 'body',
    owner_node_id: controlNode.id,
    role: 'body',
    nodes: [
      {
        id: 'wait',
        type: 'delay',
        name: '等待一秒',
        position: { x: 0, y: 0 },
        config: { seconds: 1 },
      },
    ],
    edges: [],
    entry_node_id: 'wait',
    exit_node_ids: ['wait'],
    inputs: {},
    outputs: {},
  },
]

afterEach(() => {
  localStorage.clear()
  useAuthStore.setState({ user: null })
})

it('opens the newly materialized off-page workflow instead of its fresh cached draft and preserves other projects', async () => {
  authenticateTestUser(user)
  let current = workflow
  let writes = 0
  const reads: string[] = []
  let proposal = workflowProposal()
  installWorkflowReads()
  server.use(
    http.get('/api/v1/projects', () =>
      HttpResponse.json({ items: [project, foreignProject], total: 2, page: 1, page_size: 100 }),
    ),
    http.get(`/api/v1/projects/${foreignProject.id}`, () => HttpResponse.json(foreignProject)),
    http.get('/api/v1/projects/:projectId/workflows', ({ params }) =>
      HttpResponse.json({
        items: Array.from({ length: 100 }, (_, index) => ({
          ...workflow,
          project_id: params.projectId,
          id: `listed-workflow-${index}`,
        })),
        total: 101,
        page: 1,
        page_size: 100,
      }),
    ),
    http.get('/api/v1/projects/:projectId/workflows/:workflowId', ({ params }) => {
      reads.push(String(params.projectId))
      return HttpResponse.json(params.projectId === foreignProject.id ? foreignWorkflow : current)
    }),
    http.get(`/api/v1/mcp/write/change-sets/${changeSetId}`, () =>
      HttpResponse.json({ data: proposal, warnings: [], trace_id: 'workflow-cache-trace' }),
    ),
    http.post(`/api/v1/mcp/write/change-sets/${changeSetId}/items/${itemId}/accept`, () => {
      writes += 1
      current = {
        ...workflow,
        draft_revision: 2,
        draft_definition: {
          ...workflow.draft_definition,
          schema_version: '4.0',
          nodes: [...workflow.draft_definition.nodes, controlNode],
          edges: [
            ...workflow.draft_definition.edges.map((edge) =>
              edge.id === 'api-end' ? { ...edge, target: controlNode.id } : edge,
            ),
            {
              id: 'group-end',
              source: controlNode.id,
              target: 'end',
              condition: null,
              mappings: [],
            },
          ],
          regions: controlRegions,
          run_policy: {
            request_budget: 100,
            max_runtime_seconds: null,
            cleanup_request_budget: null,
            force_cancel_skips_cleanup: false,
          },
        },
      }
      proposal = {
        ...proposal,
        status: 'accepted',
        items: [
          {
            ...proposal.items[0],
            review_status: 'accepted',
            materialized_resource_type: 'workflow',
            materialized_resource_id: workflow.id,
          },
        ],
      }
      return HttpResponse.json({ data: proposal, warnings: [], trace_id: 'accepted-cache-trace' })
    }),
  )
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  // Keep exact drafts fresh so expiry cannot conceal a missing invalidation.
  client.setQueryDefaults(['workflow'], { staleTime: Infinity })
  client.setQueryData(['workflow', project.id, workflow.id], workflow)
  client.setQueryData(['workflow', foreignProject.id, foreignWorkflow.id], foreignWorkflow)
  render(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <App>
        <QueryClientProvider client={client}>
          <ProjectTestProvider
            section="mcp-changes"
            initialEntry={`/projects/${project.id}/mcp-changes?focus=${changeSetId}`}
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
  await browser.click(await screen.findByRole('button', { name: '接受并物化' }))
  await browser.click(await screen.findByRole('link', { name: '查看物化工作流' }))
  const reader = await screen.findByRole('region', { name: '实际工作流草稿' })
  expect(await within(reader).findByText('物化后的节点')).toBeVisible()
  expect(within(reader).getByLabelText('草稿修订')).toHaveTextContent('2')
  expect(writes).toBe(1)
  expect(reads).toEqual([project.id])

  await browser.click(screen.getByRole('link', { name: '查看另一项目草稿' }))
  await waitFor(() => expect(screen.getByLabelText('草稿修订')).toHaveTextContent('17'))
  expect(screen.getByLabelText('工作流名称')).toHaveTextContent(foreignWorkflow.name)
  expect(reads).toEqual([project.id])
})

function ResultRoute() {
  const location = useLocation()
  const { projectId } = useProjectContext()
  return location.pathname.endsWith('/workflows') ? (
    <WorkflowDraftReader key={projectId} />
  ) : (
    <MCPChangeSetsPage />
  )
}

function WorkflowDraftReader() {
  const [params] = useSearchParams()
  const state = useWorkflows(params.get('focus') ?? undefined)
  return (
    <section aria-label="实际工作流草稿">
      <output aria-label="工作流名称">{state.selectedWorkflow?.name}</output>
      <output aria-label="草稿修订">{state.selectedWorkflow?.draft_revision}</output>
      {state.draftDefinition.nodes.map((node) => (
        <p key={node.id}>{node.name}</p>
      ))}
      <Link to={`/projects/${foreignProject.id}/workflows?focus=${foreignWorkflow.id}`}>
        查看另一项目草稿
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

function workflowProposal(): MCPChangeSet {
  return {
    id: changeSetId,
    project_id: project.id,
    title: '更新页外工作流',
    workflow_id: workflow.id,
    base_revision: 1,
    status: 'draft',
    source_type: 'mcp',
    source_ref: 'mcp://proposal/workflow-cache',
    actor_type: 'service_account',
    source_fingerprint: 'a'.repeat(64),
    created_by_id: user.id,
    created_at: workflow.created_at,
    updated_at: workflow.updated_at,
    applied_at: null,
    governance: {
      confidence: 0.9,
      risk_level: 'medium',
      requires_review: true,
      manual_approval_required: false,
      reason_codes: [],
    },
    approval: null,
    items: [
      {
        id: itemId,
        position: 0,
        item_type: 'workflow',
        action: 'update',
        title: '插入控制块',
        target_resource_id: workflow.id,
        proposed_content: {
          expected_revision: 1,
          edge_id: 'api-end',
          node: controlNode,
          regions: controlRegions,
          request_budget: 100,
        },
        review_status: 'pending',
        review_note: '',
        reviewed_by_id: null,
        reviewed_at: null,
        materialized_resource_type: null,
        materialized_resource_id: null,
      },
    ],
  }
}
