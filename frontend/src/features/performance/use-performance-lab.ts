import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { App } from 'antd'

import { apiErrorMessage } from '../../lib/api'
import { useProjectContext } from '../projects/use-project-context'
import {
  createPerformanceScenario,
  listPerformanceRuns,
  listPerformanceScenarios,
  publishPerformanceScenario,
  runPerformanceScenario,
  type PerformanceScenarioInput,
} from './performance-service'

export function usePerformanceLab() {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const { projectId } = useProjectContext()
  const scenarios = useQuery({
    queryKey: ['performance-scenarios', projectId],
    queryFn: () => listPerformanceScenarios(required(projectId)),
    enabled: Boolean(projectId),
  })
  const runs = useQuery({
    queryKey: ['performance-runs', projectId],
    queryFn: () => listPerformanceRuns(required(projectId)),
    enabled: Boolean(projectId),
    refetchInterval: (query) =>
      query.state.data?.items.some((run) => ['queued', 'running'].includes(run.status))
        ? 2000
        : false,
  })
  const create = useMutation({
    mutationFn: (input: PerformanceScenarioInput) =>
      createPerformanceScenario(required(projectId), input),
  })
  const publish = useMutation({
    mutationFn: (scenarioId: string) => publishPerformanceScenario(required(projectId), scenarioId),
  })
  const run = useMutation({
    mutationFn: (scenarioId: string) => runPerformanceScenario(required(projectId), scenarioId),
  })

  async function addScenario(input: PerformanceScenarioInput) {
    try {
      await create.mutateAsync(input)
      await refresh()
      void message.success('性能场景已创建，请发布后运行')
      return true
    } catch (error) {
      void message.error(apiErrorMessage(error))
      return false
    }
  }

  async function publishScenario(scenarioId: string) {
    try {
      await publish.mutateAsync(scenarioId)
      await refresh()
      void message.success('性能场景已发布')
    } catch (error) {
      void message.error(apiErrorMessage(error))
    }
  }

  async function startRun(scenarioId: string) {
    try {
      await run.mutateAsync(scenarioId)
      await queryClient.invalidateQueries({ queryKey: ['performance-runs', projectId] })
      void message.success('性能任务已进入独立队列')
    } catch (error) {
      void message.error(apiErrorMessage(error))
    }
  }

  async function refresh() {
    await queryClient.invalidateQueries({ queryKey: ['performance-scenarios', projectId] })
  }

  return {
    projectId,
    scenarios,
    runs,
    addScenario,
    publishScenario,
    startRun,
    creating: create.isPending,
    publishing: publish.isPending,
    starting: run.isPending,
  }
}

function required(value: string | null): string {
  if (!value) throw new Error('请选择项目')
  return value
}
