import { getV3FeatureFlags } from '../capabilities/capability-service'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { App } from 'antd'
import { useLayoutEffect, useMemo, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'

import { apiErrorWithTrace } from '../../lib/api'
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
  const featureFlags = useQuery({
    queryKey: ['v3-feature-flags'],
    queryFn: getV3FeatureFlags,
    enabled: Boolean(projectId),
  })
  const featureEnabled = featureFlags.data?.performance_lab === true
  const catalogsEnabled = Boolean(projectId) && featureEnabled
  const [params, setParams] = useSearchParams()
  const scenarioId = params.get('scenario')
  const runId = params.get('run')
  const context = useMemo(() => ({ projectId, scenarioId, runId }), [projectId, scenarioId, runId])
  const activeContext = useRef<typeof context | null>(context)
  useLayoutEffect(() => {
    activeContext.current = context
    return () => {
      activeContext.current = null
    }
  }, [context])
  const isCurrent = () => activeContext.current === context
  const [scenarioPage, setScenarioPage] = useRouteScopedState(projectId, null, 1)
  const [runPage, setRunPage] = useRouteScopedState(projectId, null, 1)
  const latestRun = useQuery({
    queryKey: ['performance-runs', projectId, 'latest'],
    queryFn: () => listPerformanceRuns(required(projectId), 1, 1),
    enabled: catalogsEnabled,
    refetchInterval: (query) => (query.state.data?.items.some(isPendingRun) ? 2000 : false),
  })
  const scenarios = useQuery({
    queryKey: ['performance-scenarios', projectId, scenarioPage],
    queryFn: () => listPerformanceScenarios(required(projectId), scenarioPage),
    enabled: catalogsEnabled,
  })
  const runs = useQuery({
    queryKey: ['performance-runs', projectId, runPage],
    queryFn: () => listPerformanceRuns(required(projectId), runPage),
    enabled: catalogsEnabled,
    refetchInterval: (query) => (query.state.data?.items.some(isPendingRun) ? 2000 : false),
  })
  const scenario = useQuery({
    queryKey: ['performance-scenario', projectId, scenarioId],
    queryFn: () => getPerformanceScenario(required(projectId), required(scenarioId)),
    enabled: Boolean(catalogsEnabled && scenarioId && !runId),
  })
  const runDetail = useQuery({
    queryKey: ['performance-run', projectId, runId],
    queryFn: () => getPerformanceRun(required(projectId), required(runId)),
    enabled: Boolean(catalogsEnabled && runId),
    refetchInterval: (query) => (query.state.data && isPendingRun(query.state.data) ? 2000 : false),
  })
  const create = useMutation({
    mutationKey: ['performance-create', context],
    mutationFn: (input: { projectId: string; payload: PerformanceScenarioInput }) =>
      createPerformanceScenario(input.projectId, input.payload),
  })
  const version = useMutation({
    mutationKey: ['performance-version', context],
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
    mutationKey: ['performance-publish', context],
    mutationFn: (input: { projectId: string; scenarioId: string }) =>
      publishPerformanceScenario(input.projectId, input.scenarioId),
  })
  const run = useMutation({
    mutationKey: ['performance-run', context],
    mutationFn: (input: { projectId: string; scenarioId: string }) =>
      runPerformanceScenario(input.projectId, input.scenarioId),
  })

  function selectObject(key: 'scenario' | 'run', id: string) {
    setParams((current) => {
      const next = new URLSearchParams(current)
      next.delete('scenario')
      next.delete('run')
      next.set(key, id)
      return next
    })
  }

  async function refreshCatalogs(targetProject: string) {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['performance-scenarios', targetProject] }),
      queryClient.invalidateQueries({ queryKey: ['performance-scenario', targetProject] }),
      queryClient.invalidateQueries({ queryKey: ['performance-runs', targetProject] }),
    ])
  }

  async function withFeedback(action: () => Promise<unknown>, text: string, targetProject: string) {
    try {
      await action()
      await refreshCatalogs(targetProject)
      if (!isCurrent()) return false
      void message.success(text)
      return true
    } catch (error) {
      if (!isCurrent()) return false
      void message.error(apiErrorWithTrace(error))
      return false
    }
  }

  async function addScenario(payload: PerformanceScenarioInput) {
    if (!canMutate(featureEnabled, canEdit, permissions.isSuccess, projectId)) return false
    const targetProject = required(projectId)
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
    if (!canMutate(featureEnabled, canEdit, permissions.isSuccess, projectId)) return false
    const targetProject = required(projectId)
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
    if (!canMutate(featureEnabled, canEdit, permissions.isSuccess, projectId)) return
    const targetProject = required(projectId)
    await withFeedback(
      () => publish.mutateAsync({ projectId: targetProject, scenarioId: targetScenario }),
      '性能场景已发布',
      targetProject,
    )
  }

  async function startRun(targetScenario: string) {
    if (!canMutate(featureEnabled, canEdit, permissions.isSuccess, projectId)) return
    const targetProject = required(projectId)
    try {
      const queued = await run.mutateAsync({ projectId: targetProject, scenarioId: targetScenario })
      if (isCurrent()) {
        queryClient.setQueryData(['performance-run', targetProject, queued.id], queued)
        selectObject('run', queued.id)
        void message.success('性能任务已进入独立队列')
      }
      await refreshCatalogs(targetProject)
    } catch (error) {
      if (isCurrent()) void message.error(apiErrorWithTrace(error))
    }
  }

  return {
    featureFlags,
    featureEnabled,
    projectId,
    canEdit: canMutate(featureEnabled, canEdit, permissions.isSuccess, projectId),
    canExecute,
    permissions,
    latestRun,
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

function canMutate(
  enabled: boolean,
  permission: boolean,
  loaded: boolean,
  projectId: string | null,
): boolean {
  return enabled && permission && loaded && Boolean(projectId)
}
