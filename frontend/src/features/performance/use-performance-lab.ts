import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { App } from 'antd'
import { useSearchParams } from 'react-router-dom'

import { apiErrorMessage } from '../../lib/api'
import { useRouteScopedState } from '../../lib/use-route-scoped-state'
import { useProjectContext } from '../projects/use-project-context'
import { useProjectCapabilities } from '../projects/use-project-capabilities'
import {
  createPerformanceScenario,
  createPerformanceScenarioVersion,
  getPerformanceRun,
  getPerformanceScenario,
  listPerformanceRuns,
  listPerformanceScenarios,
  publishPerformanceScenario,
  runPerformanceScenario,
  type PerformanceDefinition,
  type PerformanceScenarioInput,
} from './performance-service'

export function usePerformanceLab() {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const { projectId } = useProjectContext()
  const { canEdit, canExecute, permissions } = useProjectCapabilities()
  const [params, setParams] = useSearchParams()
  const scenarioId = params.get('scenario')
  const runId = params.get('run')
  const [scenarioPage, setScenarioPage] = useRouteScopedState(projectId, null, 1)
  const [runPage, setRunPage] = useRouteScopedState(projectId, null, 1)
  const scenarios = useQuery({
    queryKey: ['performance-scenarios', projectId, scenarioPage],
    queryFn: () => listPerformanceScenarios(required(projectId), scenarioPage),
    enabled: Boolean(projectId),
  })
  const runs = useQuery({
    queryKey: ['performance-runs', projectId, runPage],
    queryFn: () => listPerformanceRuns(required(projectId), runPage),
    enabled: Boolean(projectId),
    refetchInterval: (query) => (query.state.data?.items.some(isPendingRun) ? 2000 : false),
  })
  const scenario = useQuery({
    queryKey: ['performance-scenario', projectId, scenarioId],
    queryFn: () => getPerformanceScenario(required(projectId), required(scenarioId)),
    enabled: Boolean(projectId && scenarioId && !runId),
  })
  const runDetail = useQuery({
    queryKey: ['performance-run', projectId, runId],
    queryFn: () => getPerformanceRun(required(projectId), required(runId)),
    enabled: Boolean(projectId && runId),
    refetchInterval: (query) => (query.state.data && isPendingRun(query.state.data) ? 2000 : false),
  })
  const create = useMutation({
    mutationFn: (input: { projectId: string; payload: PerformanceScenarioInput }) =>
      createPerformanceScenario(input.projectId, input.payload),
  })
  const version = useMutation({
    mutationFn: (input: {
      projectId: string
      scenarioId: string
      description: string
      definition: PerformanceDefinition
    }) =>
      createPerformanceScenarioVersion(input.projectId, input.scenarioId, {
        description: input.description,
        definition: input.definition,
      }),
  })
  const publish = useMutation({
    mutationFn: (input: { projectId: string; scenarioId: string }) =>
      publishPerformanceScenario(input.projectId, input.scenarioId),
  })
  const run = useMutation({
    mutationFn: (input: { projectId: string; scenarioId: string }) =>
      runPerformanceScenario(input.projectId, input.scenarioId),
  })

  function selectObject(key: 'scenario' | 'run', id: string) {
    const next = new URLSearchParams(params)
    next.delete('scenario')
    next.delete('run')
    next.set(key, id)
    setParams(next)
  }

  async function withFeedback(action: () => Promise<unknown>, text: string, targetProject: string) {
    try {
      await action()
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['performance-scenarios', targetProject] }),
        queryClient.invalidateQueries({ queryKey: ['performance-scenario', targetProject] }),
        queryClient.invalidateQueries({ queryKey: ['performance-runs', targetProject] }),
      ])
      void message.success(text)
      return true
    } catch (error) {
      void message.error(apiErrorMessage(error))
      return false
    }
  }

  async function addScenario(payload: PerformanceScenarioInput) {
    if (!canEdit || !projectId) return false
    const targetProject = projectId
    return withFeedback(
      () => create.mutateAsync({ projectId: targetProject, payload }),
      '性能场景已创建，请发布后运行',
      targetProject,
    )
  }

  async function addVersion(
    targetScenario: string,
    description: string,
    definition: PerformanceDefinition,
  ) {
    if (!canEdit || !projectId) return false
    const targetProject = projectId
    return withFeedback(
      () =>
        version.mutateAsync({
          projectId: targetProject,
          scenarioId: targetScenario,
          description,
          definition,
        }),
      '新版本已创建，请审阅并发布后运行',
      targetProject,
    )
  }

  async function publishScenario(targetScenario: string) {
    if (!canEdit || !projectId) return
    const targetProject = projectId
    await withFeedback(
      () => publish.mutateAsync({ projectId: targetProject, scenarioId: targetScenario }),
      '性能场景已发布',
      targetProject,
    )
  }

  async function startRun(targetScenario: string) {
    if (!canEdit || !projectId) return
    const targetProject = projectId
    await withFeedback(
      () => run.mutateAsync({ projectId: targetProject, scenarioId: targetScenario }),
      '性能任务已进入独立队列',
      targetProject,
    )
  }

  return {
    projectId,
    canEdit,
    canExecute,
    permissions,
    scenarios,
    runs,
    scenario,
    runDetail,
    scenarioId,
    runId,
    scenarioPage,
    setScenarioPage,
    runPage,
    setRunPage,
    selectObject,
    addScenario,
    addVersion,
    publishScenario,
    startRun,
    creating: create.isPending,
    versioning: version.isPending,
    publishing: publish.isPending,
    starting: run.isPending,
  }
}

function isPendingRun(run: { status: string }) {
  return ['queued', 'running'].includes(run.status)
}

function required(value: string | null): string {
  if (!value) throw new Error('请选择项目或具体对象')
  return value
}
