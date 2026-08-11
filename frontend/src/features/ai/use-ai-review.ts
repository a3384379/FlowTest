import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { App } from 'antd'
import { useState } from 'react'

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

export function useAIReview() {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const { projectId } = useProjectContext()
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null)
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
    queryKey: ['ai-suggestions', activeJobId, activeJobStatus],
    queryFn: () => listAISuggestions(activeJobId!),
    enabled: Boolean(activeJobId),
  })
  const createMutation = useMutation({
    mutationFn: (input: Omit<AIJobInput, 'project_id'>) =>
      createAIJob({ ...input, project_id: projectId! }),
    onSuccess: async (job) => {
      setSelectedJobId(job.id)
      await queryClient.invalidateQueries({ queryKey: ['ai-jobs', projectId] })
      message.success('AI 任务已进入独立队列')
    },
    onError: () => message.error('AI 任务创建失败'),
  })
  const reviewMutation = useMutation({
    mutationFn: ({
      id,
      decision,
      content,
      note,
    }: {
      id: string
      decision: 'accept' | 'reject'
      content?: Record<string, unknown>
      note: string
    }) => reviewAISuggestion(id, decision, { content, note }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['ai-suggestions', activeJobId] })
      message.success('审核结果已保存')
    },
    onError: () => message.error('审核失败，请检查编辑后的内容'),
  })
  const settingsMutation = useMutation({
    mutationFn: (enabled: boolean) => updateAISettings(projectId!, enabled),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['ai-status', projectId] })
      message.success('AI 样本策略已更新')
    },
    onError: () => message.error('仅项目 Owner 可以修改样本策略'),
  })
  return {
    projectId,
    status,
    jobs,
    selectedJobId: activeJobId,
    selectJob: setSelectedJobId,
    suggestions,
    createJob: createMutation.mutateAsync,
    creating: createMutation.isPending,
    review: reviewMutation.mutateAsync,
    reviewing: reviewMutation.isPending,
    updateSampleSharing: settingsMutation.mutate,
    updatingSettings: settingsMutation.isPending,
  }
}
