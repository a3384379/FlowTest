import { useQueryClient } from '@tanstack/react-query'
import { Typography } from 'antd'
import { Link, useInRouterContext, useLocation, useSearchParams } from 'react-router-dom'
import { projectPath } from '../features/projects/project-routing'

export function WorkflowResourceLink({
  to,
  label,
  projectId,
}: {
  to: string
  label: string
  projectId: string
}) {
  const inRouter = useInRouterContext()
  if (!inRouter) return <Typography.Link href={to}>{label}</Typography.Link>
  return <ResourceLinkWithReturn to={to} label={label} projectId={projectId} />
}

function ResourceLinkWithReturn({
  to,
  label,
  projectId,
}: {
  to: string
  label: string
  projectId: string
}) {
  const location = useLocation()
  const path = location.pathname + location.search + location.hash
  const target = new URL(to, window.location.origin)
  if (workflowReturnPath(path, projectId)) target.searchParams.set('return_to', path)
  return <Link to={target.pathname + target.search}>{label}</Link>
}

export function WorkflowResourceReturn({ projectId }: { projectId: string | null }) {
  const [params] = useSearchParams()
  const queryClient = useQueryClient()
  const path = projectId ? workflowReturnPath(params.get('return_to'), projectId) : null
  if (!path || !projectId) return null
  return (
    <Link
      to={path}
      onClick={() => {
        void queryClient.invalidateQueries({
          predicate: (query) => isWorkflowResourceQuery(query.queryKey, projectId),
          refetchType: 'none',
        })
      }}
    >
      返回流程编排
    </Link>
  )
}

const workflowResourceKeys = new Set([
  'apis',
  'artifacts',
  'credentials',
  'graphql-schemas',
  'grpc-descriptors',
  'event-sources',
  'workflows',
])

function isWorkflowResourceQuery(key: readonly unknown[], projectId: string): boolean {
  return typeof key[0] === 'string' && workflowResourceKeys.has(key[0]) && key[1] === projectId
}

function workflowReturnPath(value: string | null, projectId: string): string | null {
  if (!value || value.length > 8192 || !value.startsWith('/projects/') || value.includes('\\'))
    return null
  const url = new URL(value, window.location.origin)
  return url.origin === window.location.origin &&
    url.pathname === projectPath(projectId, 'workflows')
    ? url.pathname + url.search + url.hash
    : null
}
