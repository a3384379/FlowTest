import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { App } from 'antd'

import { apiErrorMessage } from '../../lib/api'
import { useRouteScopedState } from '../../lib/use-route-scoped-state'
import { useProjectCapabilities } from '../projects/use-project-capabilities'
import { useProjectContext } from '../projects/use-project-context'
import {
  createAIJob,
  getAIStatus,
  listAIJobs,
  listAISuggestions,
  reviewAISuggestion,
  updateAISettings,
  type AIJobInput,
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
  const { canEdit, canManageSecurity, permissions } = useProjectCapabilities()
  const [selectedJobId, setSelectedJobId] = useRouteScopedState<string | null>(
    projectId,
    null,
    null,
  )
  const status = useQuery({
    queryKey: ['ai-status', projectId],
    queryFn: () => getAIStatus(projectId!),
    enabled: Boolean(projectId),
  })
  const jobs = useQuery({
    queryKey: ['ai-jobs', projectId],
    queryFn: () => listAIJobs(projectId!),
    enabled: Boolean(projectId),
    refetchInterval: (query) =>
      query.state.data?.items.some((job) => ['pending', 'running'].includes(job.status))
        ? 2000
        : false,
  })
  const activeJobId = selectedJobId ?? jobs.data?.items[0]?.id ?? null
  const activeJobStatus = jobs.data?.items.find((job) => job.id === activeJobId)?.status ?? null
  const suggestions = useQuery({
    queryKey: ['ai-suggestions', projectId, activeJobId, activeJobStatus],
    queryFn: () => listAISuggestions(activeJobId!),
    enabled: Boolean(projectId && activeJobId),
  })
  const createMutation = useMutation({
    mutationFn: (input: AIJobInput) => createAIJob(input),
    onError: (error) => message.error(apiErrorMessage(error)),
  })
  const reviewMutation = useMutation({
    mutationFn: ({ id, decision, content, note }: SuggestionReviewInput) =>
      reviewAISuggestion(id, decision, { content, note }),
    onError: (error) => message.error(apiErrorMessage(error)),
  })
  const settingsMutation = useMutation({
    mutationFn: ({ project, enabled }: { project: string; enabled: boolean }) =>
      updateAISettings(project, enabled),
    onSuccess: async (_, input) => {
      await queryClient.invalidateQueries({ queryKey: ['ai-status', input.project] })
      message.success('AI 样本策略已更新')
    },
    onError: (error) => message.error(apiErrorMessage(error)),
  })

  async function createJob(input: Omit<AIJobInput, 'project_id'>) {
    if (!projectId || !canEdit) throw new Error('当前项目只读')
    const job = await createMutation.mutateAsync({ ...input, project_id: projectId })
    setSelectedJobId(job.id)
    await queryClient.invalidateQueries({ queryKey: ['ai-jobs', projectId] })
    message.success('AI 任务已进入独立队列')
  }

  async function review(input: SuggestionReviewInput) {
    if (!projectId || !canEdit) throw new Error('当前项目只读')
    await reviewMutation.mutateAsync(input)
    await queryClient.invalidateQueries({ queryKey: ['ai-suggestions', projectId, activeJobId] })
    message.success('审核结果已保存')
  }

  function updateSampleSharing(enabled: boolean) {
    if (projectId && canManageSecurity) settingsMutation.mutate({ project: projectId, enabled })
  }

  return {
    projectId,
    canEdit,
    canManageSecurity,
    permissions,
    status,
    jobs,
    selectedJobId: activeJobId,
    selectJob: setSelectedJobId,
    suggestions,
    createJob,
    creating: createMutation.isPending,
    review,
    reviewing: reviewMutation.isPending,
    updateSampleSharing,
    updatingSettings: settingsMutation.isPending,
  }
}
