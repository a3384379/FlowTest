import { useCatalogQuery } from '../../lib/catalog-query'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { App } from 'antd'
import { useContext, useLayoutEffect, useMemo, useRef } from 'react'
import { UNSAFE_DataRouterContext, useLocation, useSearchParams } from 'react-router-dom'
import { apiErrorWithTrace, SessionBoundaryError } from '../../lib/api'
import { useProjectCapabilities } from '../projects/use-project-capabilities'
import { useProjectContext } from '../projects/use-project-context'
import {
  createAIJob,
  getAIStatus,
  getAIJob,
  listAIJobs,
  listAISuggestions,
  reviewAISuggestion,
  updateAISettings,
  type AIJobInput,
  type AISuggestion,
} from './ai-service'

type SuggestionReviewInput = {
  id: string
  decision: 'accept' | 'reject'
  content?: Record<string, unknown>
  note: string
}
export function useAIReview() {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const { projectId } = useProjectContext()
  const access = useProjectCapabilities()
  const canEdit = access.canEdit && access.permissions.isSuccess
  const canManageSecurity = access.canManageSecurity && access.permissions.isSuccess
  const [params, setParams] = useSearchParams()
  const commandCurrent = useAICommandContext(projectId)
  const status = useQuery({
    queryKey: ['ai-status', projectId],
    queryFn: () => getAIStatus(projectId!),
    enabled: Boolean(projectId),
  })
  const jobs = useCatalogQuery(
    'ai-jobs',
    projectId,
    (page) => listAIJobs(projectId!, page, 20),
    Boolean(projectId),
    '',
    {
      refetchInterval: (query) =>
        query.state.data?.items.some((job) => ['pending', 'running'].includes(job.status))
          ? 2000
          : false,
    },
  )
  const activeJobId = selectedJobIdentity(params, jobs.data?.items)
  const selectedJob = useQuery({
    queryKey: ['ai-job', projectId, activeJobId],
    queryFn: () => getAIJob(projectId!, activeJobId!),
    enabled: Boolean(projectId && activeJobId),
    refetchInterval: (query) =>
      query.state.data && ['pending', 'running'].includes(query.state.data.status) ? 2000 : false,
  })
  const canReview = canEdit && selectedJob.isSuccess && selectedJob.data.job_type !== 'change_set'
  const suggestions = useQuery({
    queryKey: ['ai-suggestions', projectId, activeJobId, selectedJob.data?.status],
    queryFn: () => listAISuggestions(activeJobId!),
    enabled: readyForSuggestions(
      projectId,
      activeJobId,
      selectedJob.isSuccess,
      selectedJob.data?.status,
    ),
  })
  const createMutation = useMutation({ mutationFn: createAIJob })
  const reviewMutation = useMutation({
    mutationFn: ({
      input,
      job,
    }: {
      input: SuggestionReviewInput
      job: string
      project: string
      suggestionType: AISuggestion['suggestion_type']
    }) =>
      reviewAISuggestion(
        input.id,
        input.decision,
        { content: input.content, note: input.note },
        job,
      ),
    onSuccess: (suggestion, { project }) =>
      invalidateAcceptedResource(queryClient, project, suggestion),
    onError: async (error, { project, job, input, suggestionType }) => {
      if (!(error instanceof SessionBoundaryError)) return
      await Promise.all([
        input.decision === 'accept'
          ? invalidateSuggestionResource(queryClient, project, suggestionType, 'none')
          : Promise.resolve(),
        queryClient.invalidateQueries({
          queryKey: ['ai-suggestions', project, job],
          refetchType: 'none',
        }),
      ])
    },
  })
  const settingsMutation = useMutation({
    mutationFn: ({ project, enabled }: { project: string; enabled: boolean }) =>
      updateAISettings(project, enabled),
  })
  function selectJob(id: string) {
    setParams((current) => {
      const next = new URLSearchParams(current)
      next.set('job', id)
      next.delete('suggestion')
      next.delete('decision')
      return next
    })
  }
  function selectSuggestion(id: string | null, decision: 'accept' | 'reject' = 'accept') {
    setParams((current) => {
      const next = new URLSearchParams(current)
      if (activeJobId) next.set('job', activeJobId)
      if (id) {
        next.set('suggestion', id)
        next.set('decision', decision)
      } else {
        next.delete('suggestion')
        next.delete('decision')
      }
      return next
    })
  }
  async function createJob(
    input: Omit<AIJobInput, 'project_id'>,
    onCreated?: () => void,
  ): Promise<boolean> {
    if (!projectId || !canEdit || !status.isSuccess || !status.data.enabled || !commandCurrent())
      return false
    const project = projectId
    try {
      const job = await createMutation.mutateAsync({ ...input, project_id: project })
      void queryClient.invalidateQueries({ queryKey: ['ai-jobs', project] })
      if (!commandCurrent()) return false
      onCreated?.()
      selectJob(job.id)
      void message.success('AI 任务已进入独立队列')
      return true
    } catch (error) {
      void queryClient.invalidateQueries({ queryKey: ['ai-jobs', project] })
      if (commandCurrent()) void message.error(apiErrorWithTrace(error))
      return false
    }
  }
  async function review(input: SuggestionReviewInput): Promise<AISuggestion | null> {
    const suggestion = suggestions.data?.find(
      (item) => item.id === input.id && item.review_status === 'pending',
    )
    if (!projectId || !activeJobId || !canReview || !commandCurrent() || !suggestion) return null
    const project = projectId,
      job = activeJobId
    try {
      const result = await reviewMutation.mutateAsync({
        input,
        job,
        project,
        suggestionType: suggestion.suggestion_type,
      })
      queryClient.setQueryData<AISuggestion[]>(
        ['ai-suggestions', project, job, 'completed'],
        (current) => current?.map((item) => (item.id === result.id ? result : item)),
      )
      if (!commandCurrent()) return null
      void message.success('审核结果已保存')
      return result
    } catch (error) {
      if (commandCurrent()) void message.error(apiErrorWithTrace(error))
      return null
    }
  }
  async function updateSampleSharing(enabled: boolean) {
    if (
      !projectId ||
      !canManageSecurity ||
      !status.isSuccess ||
      !status.data.enabled ||
      !commandCurrent()
    )
      return
    const project = projectId
    try {
      await settingsMutation.mutateAsync({ project, enabled })
      await queryClient.invalidateQueries({ queryKey: ['ai-status', project] })
      if (commandCurrent()) void message.success('AI 样本策略已更新')
    } catch (error) {
      if (commandCurrent()) void message.error(apiErrorWithTrace(error))
    }
  }
  return {
    projectId,
    canEdit,
    canManageSecurity,
    canReview,
    permissions: access.permissions,
    status,
    jobs,
    selectedJob,
    selectedJobId: activeJobId,
    selectJob,
    suggestions,
    createJob,
    creating: createMutation.isPending,
    review,
    reviewing: reviewMutation.isPending,
    updateSampleSharing,
    updatingSettings: settingsMutation.isPending,
    suggestionId: params.get('suggestion'),
    reviewDecision: params.get('decision') === 'reject' ? ('reject' as const) : ('accept' as const),
    selectSuggestion,
  }
}

async function invalidateAcceptedResource(
  client: ReturnType<typeof useQueryClient>,
  projectId: string,
  suggestion: AISuggestion,
): Promise<void> {
  if (suggestion.review_status !== 'accepted' || !suggestion.accepted_resource_id) return
  await invalidateSuggestionResource(client, projectId, suggestion.accepted_resource_type)
}

async function invalidateSuggestionResource(
  client: ReturnType<typeof useQueryClient>,
  projectId: string,
  type: string | null,
  refetchType: 'active' | 'none' = 'active',
): Promise<void> {
  const keys =
    type === 'workflow'
      ? ['workflows', 'workflow']
      : type === 'test_case'
        ? [
            'test-cases',
            'test-asset',
            'test-case-versions',
            'test-case-options',
            'asset-directory-counts',
            'asset-environment-options',
            'asset-environment-selected',
          ]
        : []
  await Promise.all(
    keys.map((key) => client.invalidateQueries({ queryKey: [key, projectId], refetchType })),
  )
}

function useAICommandContext(projectId: string | null) {
  const location = useLocation(),
    router = useContext(UNSAFE_DataRouterContext)
  const context = useMemo(() => ({ projectId, key: location.key }), [projectId, location.key])
  const active = useRef<typeof context | null>(context)
  useLayoutEffect(() => {
    active.current = context
    return () => {
      active.current = null
    }
  }, [context])
  return () =>
    active.current === context && (!router || router.router.state.location.key === location.key)
}

function readyForSuggestions(
  projectId: string | null,
  jobId: string | null,
  success: boolean,
  status?: string,
): boolean {
  return Boolean(projectId && jobId && success && status === 'completed')
}

function selectedJobIdentity(params: URLSearchParams, jobs?: { id: string }[]): string | null {
  return params.get('job') ?? jobs?.[0]?.id ?? null
}
