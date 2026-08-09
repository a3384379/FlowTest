import { useQuery } from '@tanstack/react-query'

import { useProjectContext } from '../projects/use-project-context'
import { getDashboardSummary, listRecentExecutions } from './dashboard-service'

export function useDashboard() {
  const { projectId, currentProject } = useProjectContext()
  const summary = useQuery({
    queryKey: ['dashboard-summary', projectId],
    queryFn: () => getDashboardSummary(projectId),
  })
  const recent = useQuery({
    queryKey: ['dashboard-recent', projectId],
    queryFn: () => listRecentExecutions(projectId),
  })
  return { projectId, currentProject, summary, recent }
}
